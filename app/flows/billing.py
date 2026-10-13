import logging
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from linebot.v3.webhooks import (
    FileMessageContent,
    ImageMessageContent,
    TextMessageContent,
)

from app import attachments, audit, billing_repository
from app.audit import Action
from app.flex.screens import billing as screens
from app.flows import registry
from app.identity import repository
from app.line import api as line_api
from app.mock import function
from app.session import store

logger = logging.getLogger(__name__)

HISTORY_DAYS = 7
TYPED_MAX = 100  # typed search text


# =========================================================
# Helpers
# =========================================================


def _bind_postback_context(node, context: str) -> None:
    """Append flow/screen context to every postback in the flex tree."""
    if isinstance(node, dict):
        if node.get("type") == "postback" and isinstance(node.get("data"), str):
            node["data"] = f"{node['data']}&{context}" if node["data"] else context

        for child in node.values():
            _bind_postback_context(child, context)

    elif isinstance(node, list):
        for child in node:
            _bind_postback_context(child, context)


async def _all_choices(session: dict) -> list[dict]:
    """Everything the current list step may pick from, before any search.

    Invoices already sent are hidden (and customers with none left), so a bill
    is never sent twice and its stored slip never overwritten.
    """
    if session["step"] == "customer":
        customers = function.customers_for(session["emp_code"])
        sent = await billing_repository.sent_invoice_ids(
            [invoice["invoice_no"] for customer in customers for invoice in customer["invoices"]]
        )

        if not sent:
            return customers

        remaining = (
            function.with_invoices(c, [i for i in c["invoices"] if i["invoice_no"] not in sent])
            for c in customers
        )
        return [customer for customer in remaining if customer["invoices"]]

    invoices = session["customer"]["invoices"]  # already limited to the employee's group
    sent = await billing_repository.sent_invoice_ids([invoice["invoice_no"] for invoice in invoices])
    return [invoice for invoice in invoices if invoice["invoice_no"] not in sent]


async def _search(session: dict, query: str) -> list[dict]:
    fields = ("customer_name", "customer_code") if session["step"] == "customer" else ("invoice_no", "voucher")
    needle = query.casefold()
    return [item for item in await _all_choices(session) if any(needle in item[f].casefold() for f in fields)]


async def _is_sent(invoice: dict) -> bool:
    return bool(await billing_repository.sent_invoice_ids([invoice["invoice_no"]]))


async def _build_current_screen(session: dict) -> dict | None:
    step, customer, invoice = session["step"], session["customer"], session["invoice"]

    if step == "customer":
        customers = await (_search(session, session["query"]) if session["query"] else _all_choices(session))
        return screens.customer_screen(customers, page=session["page"], query=session["query"])

    if not customer:
        return None

    if step == "invoice":
        invoices = await (_search(session, session["query"]) if session["query"] else _all_choices(session))
        return screens.invoice_screen(customer, invoices, page=session["page"], query=session["query"])

    if not invoice:
        return None

    if step == "attachment":
        return screens.attachment_screen(customer, invoice)

    if step == "confirm" and session["attachments"]:
        return screens.confirm_screen(customer, invoice, session["attachments"])

    return None


async def _send_current_screen(user_id: str, reply_token: str) -> None:
    session = store.get_session(user_id)
    flex_message = session and await _build_current_screen(session)

    if not flex_message:
        await line_api.reply_text(reply_token, "ไม่สามารถเรียกหน้าปัจจุบันได้ กรุณายกเลิกแล้วเริ่มใหม่")
        return

    # Postbacks carry the screen they came from so stale buttons are rejected.
    screen_id = uuid.uuid4().hex
    _bind_postback_context(
        flex_message,
        urlencode(
            {
                "flow_id": session["flow_id"],
                "screen_step": session["step"],
                "screen_id": screen_id,
            }
        ),
    )

    await line_api.reply_flex(reply_token, flex_message)
    store.mark_screen_sent(user_id, screen_id)


async def _open_invoice(user_id: str, reply_token: str, session: dict, invoice: dict, *, searched: bool) -> None:
    store.set_invoice(user_id, invoice)
    await audit.record(
        Action.INVOICE_OPENED,
        actor=audit.employee(session["emp_code"]),
        emp_code=session["emp_code"],
        invoice_no=invoice["invoice_no"],
        detail={
            "customer_code": session["customer"]["customer_code"],
            "customer_name": session["customer"]["customer_name"],
            "via": "search" if searched else "list",
        },
    )
    await _send_current_screen(user_id, reply_token)


def _billing_postback(action: str):
    """Register a postback that only runs when it comes from the screen on display.

    The handler is called as handler(user_id, reply_token, params, session).
    """

    def decorator(handler):
        @registry.register_postback(action)
        async def wrapper(*, user_id: str, reply_token: str, params: dict) -> None:
            session = store.get_session(user_id)

            if not session or (
                session["flow_id"],
                session["step"],
                session["screen_id"],
            ) != (
                params.get("flow_id"),
                params.get("screen_step"),
                params.get("screen_id"),
            ):
                # A double tap lands on the screen that just replaced this one: ignore it.
                if session and not store.can_resend_ui(user_id):
                    return

                await line_api.reply_text(
                    reply_token,
                    "รายการนี้หมดอายุแล้ว กด \"เช็คงานค้าง\" ที่เมนูเพื่อเรียกหน้าปัจจุบัน",
                )
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
    if store.get_session(user_id) and not store.can_resend_ui(user_id):
        return

    employee = await repository.get_employee_by_line_user_id(user_id)
    store.new_session(user_id, employee.emp_code)
    await _send_current_screen(user_id, reply_token)


@registry.register_postback("pending_bills")
async def pending_bills(*, user_id: str, reply_token: str, params: dict) -> None:
    """เช็คงานค้าง: bring back the screen of the bill in progress."""
    session = store.get_session(user_id)

    if not session:
        await line_api.reply_text(reply_token, "ไม่มีงานค้าง กด \"ส่งบิล\" ที่เมนูเพื่อเริ่มส่งบิล")
        return

    if not store.can_resend_ui(user_id):
        return

    # A session whose screen can't be rebuilt would leave the user without buttons.
    if not await _build_current_screen(session):
        store.clear_session(user_id)
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
        store.update(user_id, page=int(page))

    await _send_current_screen(user_id, reply_token)


@_billing_postback("clear_search")
async def clear_search(user_id: str, reply_token: str, params: dict, session: dict) -> None:
    store.update(user_id, query="", page=0)
    await _send_current_screen(user_id, reply_token)


@_billing_postback("select_customer")
async def select_customer(user_id: str, reply_token: str, params: dict, session: dict) -> None:
    code = params.get("customer_code")
    customer = next((c for c in await _all_choices(session) if c["customer_code"] == code), None)

    if not customer:  # not in this employee's group, or nothing left to send
        await line_api.reply_text(reply_token, "ไม่พบลูกค้ารายนี้ในกลุ่มของคุณ หรือส่งบิลครบแล้ว")
        return

    store.set_customer(user_id, customer)
    await _send_current_screen(user_id, reply_token)


@_billing_postback("change_customer")
async def change_customer(user_id: str, reply_token: str, params: dict, session: dict) -> None:
    store.reset_customer(user_id)
    await _send_current_screen(user_id, reply_token)


@_billing_postback("select_invoice")
async def select_invoice(user_id: str, reply_token: str, params: dict, session: dict) -> None:
    number = params.get("invoice_no")
    invoice = next((i for i in await _all_choices(session) if i["invoice_no"] == number), None)

    if not invoice:
        await line_api.reply_text(reply_token, "ไม่พบบิลนี้ของลูกค้ารายนี้ หรือบิลนี้ส่งไปแล้ว")
        return

    await _open_invoice(user_id, reply_token, session, invoice, searched=False)


@_billing_postback("back_to_invoices")
async def back_to_invoices(user_id: str, reply_token: str, params: dict, session: dict) -> None:
    store.set_customer(user_id, session["customer"])
    await _send_current_screen(user_id, reply_token)


@_billing_postback("confirm_send")
async def confirm_send(user_id: str, reply_token: str, params: dict, session: dict) -> None:
    customer, invoice = session["customer"], session["invoice"]
    attached = session["attachments"]

    if not (customer and invoice and attached):
        await line_api.reply_text(reply_token, "ไม่พบบิลที่ต้องการส่ง")
        return

    if await _is_sent(invoice):  # sent meanwhile (e.g. from another device): don't record it twice
        store.clear_session(user_id, keep_files=True)  # same path as the sent slip
        await line_api.reply_text(reply_token, "บิลนี้ถูกส่งไปแล้ว ไม่ได้ส่งซ้ำ")
        return

    # TODO: เปลี่ยน block นี้เป็น mail service จริงในขั้นถัดไป
    logger.info(
        "SEND INVOICE (%s / %s): %s",
        invoice["invoice_no"],
        customer["customer_code"],
        [attachment["file_path"] for attachment in attached],
    )

    # Recorded (with its audit row) before replying, so the user never sees
    # success for an unsaved send.
    await billing_repository.record_send(
        emp_code=session["emp_code"],
        customer=customer,
        invoice=invoice,
        attachments=attached,
    )

    store.clear_session(user_id, keep_files=True)
    await line_api.reply_flex(reply_token, screens.success_screen(customer, invoice, attached))


@_billing_postback("cancel_send")
async def cancel_send(user_id: str, reply_token: str, params: dict, session: dict) -> None:
    await audit.record(
        Action.INVOICE_CANCELLED,
        actor=audit.employee(session["emp_code"]),
        emp_code=session["emp_code"],
        invoice_no=session["invoice"]["invoice_no"] if session["invoice"] else None,
        detail={"step": session["step"], "files": len(session["attachments"])},
    )
    store.clear_session(user_id)
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
    session = store.get_session(user_id)

    if not session:
        await line_api.reply_text(reply_token, "ยังไม่มีรายการส่งบิล กด \"ส่งบิล\" ที่เมนูเพื่อเริ่ม")
        return

    if session["step"] != "attachment":
        await line_api.reply_text(reply_token, "ตอนนี้ไม่ได้อยู่ในขั้นตอนแนบไฟล์ กรุณาใช้หน้าล่าสุด")
        return

    # File events state their size, so skip downloading oversized files.
    if getattr(message, "file_size", 0) > attachments.MAX_FILE_SIZE:
        await audit.record(
            Action.FILE_REJECTED,
            actor=audit.employee(session["emp_code"]),
            emp_code=session["emp_code"],
            invoice_no=session["invoice"]["invoice_no"],
            detail={
                "line_message_id": message.id,
                "original_filename": getattr(message, "file_name", None),
                "file_size": message.file_size,
                "reason": attachments.TOO_LARGE_ERROR,
            },
        )
        await line_api.reply_text(reply_token, attachments.TOO_LARGE_ERROR)
        return

    if await _is_sent(session["invoice"]):  # sent meanwhile: its stored slip must not be overwritten
        store.clear_session(user_id)
        await line_api.reply_text(reply_token, "บิลนี้ถูกส่งไปแล้ว กด \"ส่งบิล\" ที่เมนูเพื่อเลือกบิลอื่น")
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

    invoice_no = session["invoice"]["invoice_no"]
    invoice_date = session["invoice"]["invoice_date"]
    customer_id = session["customer"]["customer_code"]
    province = session["invoice"]["province"]

    file_facts = {
        "line_message_id": message_id,
        "original_filename": filename,
        "mime_type": content_type,
        "file_size": len(content),
    }

    if error:
        await audit.record(
            Action.FILE_REJECTED,
            actor=audit.employee(session["emp_code"]),
            emp_code=session["emp_code"],
            invoice_no=invoice_no,
            detail={**file_facts, "reason": error},
        )
        await line_api.reply_text(reply_token, error)
        return

    attachment = attachments.save(
        content=content,
        mime_type=content_type,
        filename=filename,
        invoice_id=invoice_no,
        invoice_date=invoice_date,
        customer_id=customer_id,
        province=province,
        line_message_id=message_id,
        user_id=user_id,
    )
    await audit.record(
        Action.FILE_UPLOADED,
        actor=audit.employee(session["emp_code"]),
        emp_code=session["emp_code"],
        invoice_no=invoice_no,
        detail={**file_facts, "stored_path": attachment["file_path"]},
    )
    store.add_attachment(user_id, attachment)

    await _send_current_screen(user_id, reply_token)


# =========================================================
# Typed Search (for lists too long to tap through)
# =========================================================


@registry.register_message("text")
async def receive_text(*, user_id: str, reply_token: str, message: TextMessageContent) -> None:
    """On the customer / invoice list, typed text searches it (name, code or invoice number).

    One match is picked right away; several narrow the list; none keeps the screen as it was.
    """
    session = store.get_session(user_id)
    query = message.text.strip()

    if not session or session["step"] not in ("customer", "invoice") or not query:
        return

    if len(query) > TYPED_MAX:
        await line_api.reply_text(reply_token, f"ข้อความยาวเกิน {TYPED_MAX} ตัวอักษร")
        return

    matches = await _search(session, query)  # always the whole list, not inside an earlier search

    if not matches:
        what = "ลูกค้า" if session["step"] == "customer" else "บิล"
        await line_api.reply_text(reply_token, f"ไม่พบ{what}ที่ตรงกับ \"{query}\" ลองพิมพ์ใหม่อีกครั้ง")
        return

    if len(matches) > 1:
        store.update(user_id, query=query, page=0)
    elif session["step"] == "customer":
        store.set_customer(user_id, matches[0])
    else:
        await _open_invoice(user_id, reply_token, session, matches[0], searched=True)
        return

    await _send_current_screen(user_id, reply_token)
