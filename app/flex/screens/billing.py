import math
from datetime import datetime

from app import attachments as attachment_files
from app.flex import theme
from app.flex.components import (
    baht,
    billing_screen,
    box,
    build_screen,
    cancel_button,
    info_card,
    info_row,
    list_card,
    list_row,
    primary_button,
    secondary_button,
    section_title,
    selectable_item,
    summary_card,
    text,
    thai_datetime,
    title_row,
)

PAGE_SIZE = 10  # a flex bubble has a size limit; a sales group has 100+ customers

def fmt_date(value):
    try:
        return datetime.fromisoformat(value).strftime("%d-%m-%Y")
    except (TypeError, ValueError):
        return "-"

def _paged(items: list, page: int, query: str, what: str) -> tuple[list, int, list, str]:
    """(rows on this page, number of the first row, footer buttons, footer note)."""
    pages = max(1, math.ceil(len(items) / PAGE_SIZE))
    page = min(max(page, 0), pages - 1)

    nav = []
    if page > 0:
        nav.append(secondary_button(label="‹ ก่อนหน้า", data=f"action=page&page={page - 1}"))
    if page < pages - 1:
        nav.append(secondary_button(label="ถัดไป ›", data=f"action=page&page={page + 1}"))

    buttons = [box("horizontal", *nav, spacing="sm")] if nav else []
    if query:
        buttons.append(secondary_button(label="ล้างคำค้น", data="action=clear_search"))

    found = f"ผลค้นหา \"{query}\" · " if query else ""
    where = f"หน้า {page + 1}/{pages} · " if pages > 1 else ""
    note = f"{found}{where}พิมพ์{what}เพื่อค้นหา"

    return items[page * PAGE_SIZE:(page + 1) * PAGE_SIZE], page * PAGE_SIZE + 1, buttons, note


def _rows_or_empty(rows: list, empty_text: str) -> list:
    return rows or [text(empty_text, size="sm", color=theme.TEXT_MUTED, align="center", wrap=True)]


def customer_screen(customers: list[dict], *, page: int, query: str) -> dict:
    rows, first, buttons, note = _paged(customers, page, query, "ชื่อหรือรหัสลูกค้า")

    return billing_screen(
        step=1,
        alt_text="เลือกลูกค้า",
        title="เลือกลูกค้า",
        subtitle=f"ลูกค้าในกลุ่มของคุณ {len(customers):,} ราย",
        contents=_rows_or_empty(
            [
                selectable_item(
                    index=index,
                    title=customer["customer_name"],
                    subtitle=customer["customer_code"],
                    detail=f"ยอด {baht(customer['total_outstanding'])} · {customer['invoice_count']} บิล",
                    action_data=f"action=select_customer&customer_code={customer['customer_code']}",
                )
                for index, customer in enumerate(rows, start=first)
            ],
            "ไม่มีลูกค้าในกลุ่มของคุณ",
        ),
        footer=[*buttons, cancel_button()],
        footer_note=note,
    )


def invoice_screen(customer: dict, invoices: list[dict], *, page: int, query: str) -> dict:
    rows, first, buttons, note = _paged(invoices, page, query, "เลขบิล")

    return billing_screen(
        step=2,
        alt_text=f"เลือกบิลของ {customer['customer_name']}",
        title="เลือกใบแจ้งหนี้",
        subtitle=f"{customer['customer_name']} · {len(invoices):,} บิล",
        contents=_rows_or_empty(
            [
                selectable_item(
                    index=index,
                    title=invoice["invoice_no"],
                    subtitle=baht(invoice["outstanding"]),
                    detail=(
                        f"วันออกบิล {fmt_date(invoice.get('invoice_date'))} "
                        f"ครบกำหนด {fmt_date(invoice.get('due_date'))}"
                    ),
                    action_data=f"action=select_invoice&invoice_no={invoice['invoice_no']}",
                )
                for index, invoice in enumerate(rows, start=first)
            ],
            "ไม่มีบิลของลูกค้ารายนี้",
        ),
        footer=[
            *buttons,
            secondary_button(label="← เปลี่ยนลูกค้า", data="action=change_customer"),
            cancel_button(),
        ],
        footer_note=note,
    )


def attachment_screen(customer: dict, invoice: dict) -> dict:
    message = billing_screen(
        step=3,
        alt_text=f"แนบไฟล์สำหรับ {invoice['invoice_no']}",
        title="แนบไฟล์สลิป",
        subtitle="ส่งรูปหรือไฟล์ที่ต้องการแนบกับใบแจ้งหนี้",
        contents=[
            info_card(
                ("เลขที่บิล", invoice["invoice_no"]),
                ("ลูกค้า", customer["customer_name"]),
                ("ยอดค้างชำระ", baht(invoice["outstanding"]), True),
            ),
            box(
                "vertical",
                text("📎 แนบไฟล์สลิป", size="md", weight="bold", color=theme.PRIMARY),
                text(
                    "เลือกรูป หรือแนบไฟล์ จากเมนูของ LINE ได้เลย",
                    size="sm",
                    color=theme.TEXT_SECONDARY,
                    wrap=True,
                ),
                spacing="md",
                paddingAll="18px",
                backgroundColor=theme.PRIMARY_SOFT,
                cornerRadius=theme.CARD_RADIUS,
            ),
        ],
        footer=[
            secondary_button(label="← เลือกบิลใหม่", data="action=back_to_invoices"),
            cancel_button(),
        ],
        footer_note="เมื่อรับไฟล์เรียบร้อย ระบบจะพาไปขั้นตอนยืนยันอัตโนมัติ",
    )

    message["quickReply"] = {
        "items": [
            {"type": "action", "action": {"type": "cameraRoll", "label": "🖼️ เลือกรูป"}},
        ]
    }

    return message


def _attachment_row(attachment: dict, index: int) -> dict:
    mime_type = attachment["mime_type"]
    file_type = attachment_files.type_label(mime_type)
    file_size = attachment_files.format_file_size(attachment["file_size"])

    return box(
        "horizontal",
        text("🖼️" if mime_type.startswith("image/") else "📄", size="lg", flex=0, gravity="center"),
        box(
            "vertical",
            text(
                attachment.get("original_filename") or f"รูปภาพสลิป {index}",
                size="sm",
                weight="bold",
                color=theme.TEXT_PRIMARY,
                wrap=True,
            ),
            text(f"{file_type} · {file_size}", size="xs", color=theme.TEXT_SECONDARY),
            spacing="xs",
            flex=1,
        ),
        text("✓", size="md", weight="bold", color=theme.SUCCESS, flex=0, gravity="center"),
        spacing="md",
        paddingAll="12px",
        backgroundColor=theme.SURFACE,
        cornerRadius=theme.ITEM_RADIUS,
    )


def confirm_screen(customer: dict, invoice: dict, attachments: list[dict]) -> dict:
    return billing_screen(
        step=4,
        alt_text=f"ยืนยันส่งบิล {invoice['invoice_no']}",
        title="ตรวจสอบและยืนยัน",
        subtitle="ตรวจสอบข้อมูลและไฟล์แนบก่อนส่งใบแจ้งหนี้",
        contents=[
            summary_card(
                [
                    text(invoice["invoice_no"], size="lg", weight="bold", color=theme.TEXT_PRIMARY),
                    {"type": "separator", "color": theme.BORDER},
                    info_row(label="ยอดค้างชำระ", value=baht(invoice["outstanding"]), emphasis=True),
                    info_row(label="วันที่บิล", value=fmt_date(invoice["invoice_date"])),
                    info_row(label="ครบกำหนด", value=fmt_date(invoice["due_date"])),
                ]
            ),
            summary_card(
                [
                    section_title("ข้อมูลผู้รับ"),
                    info_row(label="ลูกค้า", value=customer["customer_name"]),
                    info_row(label="รหัสลูกค้า", value=customer["customer_code"]),
                ]
            ),
            summary_card(
                [
                    title_row(
                        text("ไฟล์แนบ", size="sm", weight="bold", color=theme.TEXT_PRIMARY, flex=1),
                        text(
                            f"{len(attachments)} ไฟล์",
                            size="xs",
                            weight="bold",
                            color=theme.PRIMARY,
                            align="end",
                            flex=0,
                        ),
                    ),
                    *(
                        _attachment_row(attachment, index)
                        for index, attachment in enumerate(attachments, start=1)
                    ),
                ]
            ),
        ],
        footer=[
            primary_button(label="ยืนยันส่งบิล", data="action=confirm_send"),
            cancel_button(),
        ],
    )


def success_screen(customer: dict, invoice: dict, attachments: list[dict]) -> dict:
    return billing_screen(
        step=4,
        alt_text=f"ส่งบิล {invoice['invoice_no']} เรียบร้อยแล้ว",
        title="ดำเนินการสำเร็จ",
        subtitle="ใบแจ้งหนี้ถูกส่งเรียบร้อยแล้ว",
        background_color=theme.SUCCESS,
        contents=[
            summary_card(
                [
                    text("✅", size="3xl", align="center"),
                    text("ส่งบิลเรียบร้อยแล้ว", size="lg", weight="bold", align="center", color=theme.SUCCESS),
                    text(
                        "ระบบดำเนินการส่งใบแจ้งหนี้เรียบร้อยแล้ว",
                        size="sm",
                        align="center",
                        color=theme.TEXT_SECONDARY,
                        wrap=True,
                    ),
                ]
            ),
            info_card(
                ("เลขที่บิล", invoice["invoice_no"]),
                ("ลูกค้า", customer["customer_name"]),
                ("ยอดค้างชำระ", baht(invoice["outstanding"]), True),
                ("ที่อยู่บิล", invoice["province"]),
                ("ไฟล์แนบ", f"{len(attachments)} ไฟล์"),
            ),
        ],
        footer_note="หากต้องการส่งบิลรายการอื่น กด \"ส่งบิล\" ที่เมนู",
    )


def history_screen(sends: list, *, days: int) -> dict:
    """Bill sends (BillSend rows), newest first."""
    total = sum(send.amount for send in sends)

    return build_screen(
        label="งานขาย",
        alt_text=f"ประวัติการส่งบิล {len(sends)} รายการ",
        title="ประวัติการส่งบิล",
        subtitle=f"{days} วันล่าสุด · {len(sends)} รายการ · รวม {baht(total)}",
        contents=[
            list_card(
                [
                    list_row(
                        title=send.invoice_id,
                        subtitle=f"{send.customer_name} · {send.attachment_count} ไฟล์",
                        value=baht(send.amount),
                        note=thai_datetime(send.sent_at),
                    )
                    for send in sends
                ],
                empty_text=f"ยังไม่มีการส่งบิลใน {days} วันที่ผ่านมา",
            )
        ],
    )
