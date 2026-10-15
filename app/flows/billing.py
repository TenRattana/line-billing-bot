import logging
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from linebot.v3.webhooks import (
    FileMessageContent,
    ImageMessageContent,
    TextMessageContent,
)

from app import audit
from app.audit import Action
from app.billing import attachments, receivables
from app.billing import repository as billing_repository
from app.billing import session as billing_session
from app.config import BILLING_LIFF_URL, TEST_TEXT_COMMANDS_ENABLED
from app.flex.screens import billing as screens
from app.flows import registry
from app.identity import repository
from app.line import api as line_api

logger = logging.getLogger(__name__)

HISTORY_DAYS = 7
TYPED_MAX = 100  # typed search text
EXPIRED_TEXT = "รายการนี้หมดอายุแล้ว กด \"เช็คงานค้าง\" ที่เมนูเพื่อเรียกหน้าปัจจุบัน"


# =========================================================
# Helpers
# =========================================================


def _bind_screen_context(node, context: str) -> None:
    """Append flow/screen context to every postback, and to every LIFF link, in the flex tree.

    A LIFF link opens without asking the bot, so the LIFF hands the context back to
    the API, which turns a stale screen away like a stale postback.
    """
    if isinstance(node, dict):
        if node.get("type") == "postback" and isinstance(node.get("data"), str):
            node["data"] = f"{node['data']}&{context}" if node["data"] else context
        elif node.get("type") == "uri" and str(node.get("uri", "")).startswith(BILLING_LIFF_URL):
            node["uri"] = f"{node['uri']}{'&' if '?' in node['uri'] else '?'}{context}"

        for child in node.values():
            _bind_screen_context(child, context)

    elif isinstance(node, list):
        for child in node:
            _bind_screen_context(child, context)


def is_current_screen(user_id: str, params: dict) -> bool:
    """Whether params (flow_id, screen_step, screen_id) are from the screen on display."""
    session = billing_session.get_session(user_id)
    return bool(session) and (session["flow_id"], session["step"], session["screen_id"]) == (
        params.get("flow_id"),
        params.get("screen_step"),
        params.get("screen_id"),
    )


async def _unsent_customers(emp_code: str) -> list[dict]:
    """The employee's customers with only invoices not sent yet (and none with nothing left).

    So a bill is never sent twice and its stored slip never overwritten.
    """
    customers = receivables.customers_for(emp_code)
    sent = await billing_repository.sent_invoice_ids(
        [invoice["invoice_no"] for customer in customers for invoice in customer["invoices"]]
    )

    if not sent:
        return customers

    remaining = (
        receivables.with_invoices(c, [i for i in c["invoices"] if i["invoice_no"] not in sent]) for c in customers
    )
    return [customer for customer in remaining if customer["invoices"]]


async def _search(session: dict, query: str) -> list[dict]:
    needle = query.casefold()
    return [
        customer
        for customer in await _unsent_customers(session["emp_code"])
        if needle in customer["customer_name"].casefold() or needle in customer["customer_code"].casefold()
    ]


async def _sent_of(invoices: list[dict]) -> set[str]:
    return await billing_repository.sent_invoice_ids([invoice["invoice_no"] for invoice in invoices])


async def _record_per_invoice(action: Action, session: dict, detail: dict) -> None:
    """Audit rows name one invoice each; a bill of several gets a row per invoice."""
    for invoice_no in [i["invoice_no"] for i in session["invoices"]] or [None]:
        await audit.record(
            action,
            actor=audit.employee(session["emp_code"]),
            emp_code=session["emp_code"],
            invoice_no=invoice_no,
            detail=detail,
        )


async def _build_current_screen(session: dict) -> dict | None:
    step, customer, invoices = session["step"], session["customer"], session["invoices"]

    if step == "customer":
        query = session["query"]
        customers = await (_search(session, query) if query else _unsent_customers(session["emp_code"]))
        return screens.customer_screen(customers, page=session["page"], query=query)

    if not (customer and invoices):
        return None

    if step == "attachment":
        return screens.attachment_screen(customer, invoices)

    if step == "confirm" and session["attachments"]:
        return screens.confirm_screen(customer, invoices, session["attachments"])

    return None


async def _send_current_screen(user_id: str, reply_token: str | None) -> None:
    """Reply to the chat event, or push when there is none (reply_token None)."""
    session = billing_session.get_session(user_id)
    flex_message = session and await _build_current_screen(session)

    if not flex_message:
        error = "ไม่สามารถเรียกหน้าปัจจุบันได้ กรุณายกเลิกแล้วเริ่มใหม่"
        await (line_api.reply_text(reply_token, error) if reply_token else line_api.push_text(user_id, error))
        return

    # Postbacks and LIFF links carry the screen they came from so stale ones are rejected.
    screen_id = uuid.uuid4().hex
    _bind_screen_context(
        flex_message,
        urlencode(
            {
                "flow_id": session["flow_id"],
                "screen_step": session["step"],
                "screen_id": screen_id,
            }
        ),
    )

    await (line_api.reply_flex(reply_token, flex_message) if reply_token else line_api.push_flex(user_id, flex_message))
    billing_session.mark_screen_sent(user_id, screen_id)


async def _start_new_bill(user_id: str, reply_token: str) -> None:
    employee = await repository.get_employee_by_line_user_id(user_id)
    billing_session.new_session(user_id, employee.emp_code)
    await _send_current_screen(user_id, reply_token)


async def start_selected(user_id: str, emp_code: str, customer: dict, invoices: list[dict]) -> None:
    """Invoices picked in LIFF (already checked): a new bill straight at the attachment step, pushed to the chat."""
    session = billing_session.new_session(user_id, emp_code)  # replaces the bill in progress, like "ส่งบิล"
    billing_session.set_selection(user_id, customer, invoices)
    await _record_per_invoice(
        Action.INVOICE_OPENED,
        session,
        {"customer_code": customer["customer_code"], "customer_name": customer["customer_name"], "via": "liff"},
    )
    await _send_current_screen(user_id, None)


def _billing_postback(action: str):
    """Register a postback that only runs when it comes from the screen on display.

    The handler is called as handler(user_id, reply_token, params, session).
    """

    def decorator(handler):
        @registry.register_postback(action)
        async def wrapper(*, user_id: str, reply_token: str, params: dict) -> None:
            session = billing_session.get_session(user_id)

            if not is_current_screen(user_id, params):
                # A double tap lands on the screen that just replaced this one: ignore it.
                if session and not billing_session.can_resend_ui(user_id):
                    return

                await line_api.reply_text(reply_token, EXPIRED_TEXT)
                return

            await handler(user_id, reply_token, params, session)

        return wrapper

    return decorator


# =========================================================
# Sales Menu
# =========================================================


@registry.register_postback("send_bill")
async def send_bill(*, user_id: str, reply_token: str, params: dict) -> None:
    """Always a new bill; the one in progress (if any) is replaced."""
    # Tapping the menu repeatedly would restart and resend the screen each time.
    if billing_session.get_session(user_id) and not billing_session.can_resend_ui(user_id):
        return

    await _start_new_bill(user_id, reply_token)


@registry.register_postback("pending_bills")
async def pending_bills(*, user_id: str, reply_token: str, params: dict) -> None:
    """เช็คงานค้าง: bring back the screen of the bill in progress."""
    session = billing_session.get_session(user_id)

    if not session:
        await line_api.reply_text(reply_token, "ไม่มีงานค้าง กด \"ส่งบิล\" ที่เมนูเพื่อเริ่มส่งบิล")
        return

    if not billing_session.can_resend_ui(user_id):
        return

    # A session whose screen can't be rebuilt would leave the user without buttons.
    if not await _build_current_screen(session):
        billing_session.clear_session(user_id)
        await line_api.reply_text(reply_token, "งานที่ค้างไว้ใช้ต่อไม่ได้แล้ว กด \"ส่งบิล\" ที่เมนูเพื่อเริ่มใหม่")
        return

    await _send_current_screen(user_id, reply_token)


@registry.register_postback("bill_history")
async def bill_history(*, user_id: str, reply_token: str, params: dict) -> None:
    employee = await repository.get_employee_by_line_user_id(user_id)
    sends = await billing_repository.list_sends(
        emp_code=employee.emp_code,
        since=datetime.now(timezone.utc) - timedelta(days=HISTORY_DAYS),
    )

    await line_api.reply_flex(reply_token, screens.history_screen(sends, days=HISTORY_DAYS))


# =========================================================
# Postback Actions
# =========================================================


@_billing_postback("page")
async def change_page(user_id: str, reply_token: str, params: dict, session: dict) -> None:
    page = params.get("page", "")

    if page.isdigit():  # the screen clamps it to the last page
        billing_session.update(user_id, page=int(page))

    await _send_current_screen(user_id, reply_token)


@_billing_postback("clear_search")
async def clear_search(user_id: str, reply_token: str, params: dict, session: dict) -> None:
    billing_session.update(user_id, query="", page=0)
    await _send_current_screen(user_id, reply_token)


@_billing_postback("change_customer")
async def change_customer(user_id: str, reply_token: str, params: dict, session: dict) -> None:
    """"Back" from any step: pick a customer again (the files of the dropped bill are deleted)."""
    billing_session.reset_customer(user_id)
    await _send_current_screen(user_id, reply_token)


@_billing_postback("confirm_send")
async def confirm_send(user_id: str, reply_token: str, params: dict, session: dict) -> None:
    customer, invoices = session["customer"], session["invoices"]
    attached = session["attachments"]

    if not (customer and invoices and attached):
        await line_api.reply_text(reply_token, "ไม่พบบิลที่ต้องการส่ง")
        return

    sent = await _sent_of(invoices)
    if sent:  # sent meanwhile (e.g. from another device): don't record it twice
        for attachment in attached:  # a sent invoice's copy has the same path as its sent slip
            if attachment["invoice_no"] not in sent:
                attachments.delete(attachment)
        billing_session.clear_session(user_id, keep_files=True)
        await line_api.reply_text(reply_token, f"บิล {', '.join(sorted(sent))} ถูกส่งไปแล้ว ไม่ได้ส่งซ้ำ")
        return

    # TODO: เปลี่ยน block นี้เป็น mail service จริงในขั้นถัดไป
    logger.info(
        "SEND INVOICE (%s / %s): %s",
        [invoice["invoice_no"] for invoice in invoices],
        customer["customer_code"],
        [attachment["file_path"] for attachment in attached],
    )

    # Recorded (with its audit rows) before replying, so the user never sees
    # success for an unsaved send.
    await billing_repository.record_send(
        emp_code=session["emp_code"],
        customer=customer,
        invoices=invoices,
        attachments=attached,
    )

    billing_session.clear_session(user_id, keep_files=True)
    await line_api.reply_flex(reply_token, screens.success_screen(customer, invoices, attached))


@_billing_postback("cancel_send")
async def cancel_send(user_id: str, reply_token: str, params: dict, session: dict) -> None:
    await _record_per_invoice(
        Action.INVOICE_CANCELLED,
        session,
        {"step": session["step"], "files": len(session["attachments"])},
    )
    billing_session.clear_session(user_id)
    await line_api.reply_text(reply_token, "ยกเลิกการส่งบิลแล้ว")


# =========================================================
# Message Attachments
# =========================================================


@registry.register_message("image", "file")
async def receive_attachment(
    *,
    user_id: str,
    reply_token: str,
    message: ImageMessageContent | FileMessageContent,
) -> None:
    session = billing_session.get_session(user_id)

    if not session:
        await line_api.reply_text(reply_token, "ยังไม่มีรายการส่งบิล กด \"ส่งบิล\" ที่เมนูเพื่อเริ่ม")
        return

    if session["step"] != "attachment":
        await line_api.reply_text(reply_token, "ตอนนี้ไม่ได้อยู่ในขั้นตอนแนบไฟล์ กรุณาใช้หน้าล่าสุด")
        return

    # File events state their size, so skip downloading oversized files.
    if getattr(message, "file_size", 0) > attachments.MAX_FILE_SIZE:
        await _record_per_invoice(
            Action.FILE_REJECTED,
            session,
            {
                "line_message_id": message.id,
                "original_filename": getattr(message, "file_name", None),
                "file_size": message.file_size,
                "reason": attachments.TOO_LARGE_ERROR,
            },
        )
        await line_api.reply_text(reply_token, attachments.TOO_LARGE_ERROR)
        return

    sent = await _sent_of(session["invoices"])
    if sent:  # sent meanwhile: its stored slip must not be overwritten
        billing_session.clear_session(user_id)
        await line_api.reply_text(
            reply_token, f"บิล {', '.join(sorted(sent))} ถูกส่งไปแล้ว กด \"ส่งบิล\" ที่เมนูเพื่อเลือกบิลอื่น"
        )
        return

    message_id = message.id
    filename = getattr(message, "file_name", None)
    content, content_type = await line_api.get_message_content(message_id)

    error = attachments.validate(
        message_type=message.type,
        filename=filename,
        mime_type=content_type,
        file_size=len(content),
    )

    file_facts = {
        "line_message_id": message_id,
        "original_filename": filename,
        "mime_type": content_type,
        "file_size": len(content),
    }

    if error:
        await _record_per_invoice(Action.FILE_REJECTED, session, {**file_facts, "reason": error})
        await line_api.reply_text(reply_token, error)
        return

    saved = attachments.save_copies(
        invoices=session["invoices"],
        customer_id=session["customer"]["customer_code"],
        content=content,
        mime_type=content_type,
        filename=filename,
        line_message_id=message_id,
        user_id=user_id,
    )
    for attachment in saved:
        await audit.record(
            Action.FILE_UPLOADED,
            actor=audit.employee(session["emp_code"]),
            emp_code=session["emp_code"],
            invoice_no=attachment["invoice_no"],
            detail={**file_facts, "stored_path": attachment["file_path"]},
        )
    billing_session.add_attachments(user_id, saved)

    await _send_current_screen(user_id, reply_token)


# =========================================================
# Typed Search (for lists too long to tap through)
# =========================================================


@registry.register_message("text")
async def receive_text(*, user_id: str, reply_token: str, message: TextMessageContent) -> None:
    """On the customer list, typed text searches it (name or code).

    Matches narrow the list (a customer is opened in LIFF by tapping it); none keeps the screen as it was.
    """
    session = billing_session.get_session(user_id)
    query = message.text.strip()

    if TEST_TEXT_COMMANDS_ENABLED and query == "ส่งบิล":
        await _start_new_bill(user_id, reply_token)
        return

    if not session or session["step"] != "customer" or not query:
        return

    if len(query) > TYPED_MAX:
        await line_api.reply_text(reply_token, f"ข้อความยาวเกิน {TYPED_MAX} ตัวอักษร")
        return

    matches = await _search(session, query)  # always the whole list, not inside an earlier search

    if not matches:
        await line_api.reply_text(reply_token, f"ไม่พบลูกค้าที่ตรงกับ \"{query}\" ลองพิมพ์ใหม่อีกครั้ง")
        return

    billing_session.update(user_id, query=query, page=0)
    await _send_current_screen(user_id, reply_token)
