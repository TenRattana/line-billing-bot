from urllib.parse import urlencode

from app.flex import theme
from app.flex.components import (
    box,
    build_screen,
    button,
    info_card,
    text,
    thai_datetime,
)


def _row(label: str, value: str) -> dict:
    return box(
        "horizontal",
        text(label, size="sm", color=theme.TEXT_SECONDARY, flex=3),
        text(value, size="sm", weight="bold", wrap=True, flex=5),
        spacing="md",
    )


def build_registration_confirm_flex(emp_code: str, person: dict, *, line_display_name: str | None = None) -> dict:
    """Shown only after code + name were verified; `person` is the directory record."""

    def data(action: str) -> str:
        return urlencode({"action": action, "emp_code": emp_code})

    return {
        "type": "flex",
        "altText": "ยืนยันข้อมูลพนักงาน",
        "contents": {
            "type": "bubble",
            "size": "kilo",
            "body": box(
                "vertical",
                text("ยืนยันตัวตน", weight="bold", size="xl"),
                text(
                    "กรุณาตรวจสอบข้อมูลพนักงานก่อนยืนยันการลงทะเบียน",
                    size="sm",
                    color=theme.TEXT_SECONDARY,
                    wrap=True,
                ),
                {"type": "separator"},
                _row("รหัสพนักงาน", emp_code),
                _row("ชื่อ", person["name"]),
                _row("แผนก", person["department"] or "-"),
                _row("บัญชี LINE", line_display_name or "-"),
                spacing="lg",
            ),
            "footer": box(
                "vertical",
                button(
                    "primary",
                    label="ยืนยันตัวตน",
                    data=data("confirm_registration"),
                    display_text="ยืนยันตัวตน",
                ),
                button(
                    "secondary",
                    label="ยกเลิก",
                    data=data("cancel_registration"),
                    display_text="ยกเลิกการลงทะเบียน",
                ),
                spacing="sm",
            ),
        },
    }


def profile_screen(employee, identity) -> dict:
    """"ข้อมูลของฉัน": the employee record and its LINE binding."""
    return build_screen(
        label="ข้อมูลของฉัน",
        alt_text=f"ข้อมูลของ {employee.emp_full}",
        title=employee.emp_full,
        subtitle=f"รหัสพนักงาน {employee.emp_code}",
        contents=[
            info_card(
                ("แผนก", employee.emp_department or "-"),
                ("อีเมล", employee.emp_email or "-"),
                ("เบอร์โทร", employee.emp_phone or "-"),
            ),
            info_card(
                ("บัญชี LINE", identity.display_name or "-"),
                ("ลงทะเบียนเมื่อ", thai_datetime(identity.create_at)),
            ),
        ],
    )
