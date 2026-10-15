"""Registration: employee code -> full name -> confirm -> save.

The code and name are checked against the central employees table before
anything is shown or saved, so knowing a code alone reveals nothing. The saved
name and department come from that table.
"""

from app import audit
from app.config import PUBLIC_BASE_URL
from app.audit import Action
from app.flex.screens import registration as registration_screen
from app.flows import registry
from app.identity import (
    directory,
    registration_store,
    repository,
)
from app.identity.directory import Verdict
from app.line import api as line_api
from app.line import richmenu

EMPLOYEE_CODE_MAX = 30
FULL_NAME_MAX = 120
NAME_ATTEMPTS_MAX = 3

_REGISTER_FAILURES = {
    "already_registered": "บัญชี LINE นี้ลงทะเบียนแล้ว",
    "line_already_registered": "บัญชี LINE นี้ถูกลงทะเบียนกับพนักงานคนอื่นแล้ว",
    "employee_already_registered": "รหัสพนักงานนี้ถูกลงทะเบียนกับบัญชี LINE อื่นแล้ว",
}


def _rejection(verdict: Verdict, code: str) -> str:
    match verdict:
        case Verdict.NOT_FOUND:
            return (
                f"ไม่พบรหัสพนักงาน {code} ในระบบ กรุณาตรวจสอบรหัสแล้วลองใหม่อีกครั้ง "
                "ถ้ายังไม่ได้ กรุณาติดต่อแอดมิน"
            )
        case Verdict.NAME_MISMATCH:
            return (
                f"ชื่อ-นามสกุลไม่ตรงกับรหัส {code} ในระบบ "
                "พิมพ์ทั้งชื่อและนามสกุลตามที่ใช้ในบริษัท (จะใส่คำนำหน้าหรือไม่ก็ได้)"
            )
        case _:
            return "ขณะนี้ตรวจสอบข้อมูลพนักงานไม่ได้ กรุณาลองใหม่อีกครั้งในอีกสักครู่"


async def _rejected(line_user_id: str, reason: str, *, code: str, emp_code: str | None = None, **detail) -> None:
    """Audit a refused attempt. Never logs the typed name (personal data)."""
    await audit.record(
        Action.EMPLOYEE_REJECTED,
        actor=audit.line_user(line_user_id),
        emp_code=emp_code,
        line_user_id=line_user_id,
        detail={"reason": reason, "code": code[:EMPLOYEE_CODE_MAX], **detail},
    )


async def start_registration(
    *,
    line_user_id: str,
    reply_token: str,
) -> None:
    profile = await line_api.get_profile(line_user_id)
    display_name = profile.display_name if profile else None

    registration_store.start_registration(
        line_user_id,
        display_name=display_name,
        picture_url=profile.picture_url if profile else None,
    )

    if display_name:
        text = (
            f"สวัสดีคุณ {display_name} 👋\n"
            "ยินดีต้อนรับสู่บริการสอบถามข้อมูล\n\n"
            "กรุณากรอกรหัสพนักงานเพื่อยืนยันตัวตน"
        )
    else:
        text = (
            "ยินดีต้อนรับสู่บริการสอบถามข้อมูล 👋\n\n"
            "กรุณากรอกรหัสพนักงานเพื่อยืนยันตัวตน"
        )

    await line_api.reply_text_and_image(
        reply_token,
        text,
        f"{PUBLIC_BASE_URL}/assets/img/KFM_Logo.png",
    )

@registry.register_postback("start_registration")
async def start_registration_postback(*, user_id: str, reply_token: str, params: dict) -> None:
    await start_registration(line_user_id=user_id, reply_token=reply_token)


async def handle_text(*, line_user_id: str, reply_token: str, text: str) -> None:
    """Typed text from an unregistered user, routed by registration step."""
    registration = registration_store.get_registration(line_user_id)

    if not registration:
        await start_registration(line_user_id=line_user_id, reply_token=reply_token)
        return

    value = text.strip()

    if registration["step"] == "confirm":
        await line_api.reply_text(reply_token, "กรุณาใช้หน้ายืนยันตัวตนล่าสุด")
    elif not value:
        await line_api.reply_text(reply_token, "ข้อความว่าง กรุณาพิมพ์ใหม่อีกครั้ง")
    elif registration["step"] == "employee_code":
        await _receive_code(line_user_id, reply_token, value)
    else:
        await _receive_name(line_user_id, reply_token, registration, value)


async def _receive_code(line_user_id: str, reply_token: str, code: str) -> None:
    if len(code) > EMPLOYEE_CODE_MAX:
        await line_api.reply_text(reply_token, f"รหัสพนักงานยาวเกิน {EMPLOYEE_CODE_MAX} ตัวอักษร")
        return

    code = directory.normalize_code(code)
    verdict, person = await directory.lookup(code)

    if verdict is not Verdict.OK:
        if verdict is Verdict.NOT_FOUND:  # UNAVAILABLE is an outage, not the user's doing
            await _rejected(line_user_id, "code_not_found", code=code)
        await line_api.reply_text(reply_token, _rejection(verdict, code))
        return

    # One code, one LINE account.
    if await repository.is_code_registered(code):
        await _rejected(line_user_id, "code_already_bound", code=code, emp_code=code)
        await line_api.reply_text(
            reply_token,
            f"รหัส {code} ถูกลงทะเบียนไว้แล้ว ถ้าเป็นรหัสของคุณจริง กรุณาติดต่อแอดมินเพื่อย้ายบัญชี",
        )
        return

    # The name step checks against this result: no second lookup.
    registration_store.update(line_user_id, step="full_name", emp_code=code, person=person, name_attempts=0)
    await line_api.reply_text(reply_token, "กรุณาพิมพ์ชื่อ-นามสกุลของคุณ")


async def _receive_name(line_user_id: str, reply_token: str, registration: dict, full_name: str) -> None:
    if len(full_name) > FULL_NAME_MAX:
        await line_api.reply_text(reply_token, f"ชื่อยาวเกิน {FULL_NAME_MAX} ตัวอักษร")
        return

    code, person = registration["emp_code"], registration["person"]

    if not directory.name_matches(person, full_name):
        # Limited attempts, or anyone could keep guessing the name behind a code.
        attempts = registration["name_attempts"] + 1
        await _rejected(
            line_user_id,
            "name_mismatch",
            code=code,
            emp_code=code,
            attempt=attempts,
            locked=attempts >= NAME_ATTEMPTS_MAX,
        )

        if attempts < NAME_ATTEMPTS_MAX:
            registration_store.update(line_user_id, name_attempts=attempts)
            await line_api.reply_text(
                reply_token,
                f"{_rejection(Verdict.NAME_MISMATCH, code)}\n\nพิมพ์ชื่อ-นามสกุลอีกครั้ง (เหลืออีก {NAME_ATTEMPTS_MAX - attempts} ครั้ง)",
            )
            return

        registration_store.update(line_user_id, step="employee_code", emp_code=None, person=None, name_attempts=0)
        await line_api.reply_text(
            reply_token,
            f"{_rejection(Verdict.NAME_MISMATCH, code)}\n\nพิมพ์ผิดครบ {NAME_ATTEMPTS_MAX} ครั้งแล้ว "
            "เริ่มใหม่ กรุณากรอกรหัสพนักงาน",
        )
        return

    registration_store.update(line_user_id, step="confirm")

    await line_api.reply_flex(
        reply_token,
        registration_screen.build_registration_confirm_flex(
            code,
            person,
            line_display_name=registration["display_name"],
        ),
    )


@registry.register_postback("confirm_registration")
async def confirm_registration(*, user_id: str, reply_token: str, params: dict) -> None:
    registration = registration_store.get_registration(user_id)

    if not registration:
        await line_api.reply_text(reply_token, "รายการลงทะเบียนนี้หมดอายุแล้ว กรุณาเริ่มลงทะเบียนใหม่")
        return

    if registration["step"] != "confirm":
        await line_api.reply_text(reply_token, "ยังไม่มีข้อมูลพนักงานสำหรับยืนยัน")
        return

    emp_code = registration["emp_code"]

    if params.get("emp_code") != emp_code:
        await line_api.reply_text(reply_token, "รายการยืนยันนี้หมดอายุแล้ว กรุณาใช้รายการล่าสุด")
        return

    status, employee = await repository.register_line_identity(
        line_user_id=user_id,
        emp_code=emp_code,
        person=registration["person"],
        display_name=registration["display_name"],
        picture_url=registration["picture_url"],
    )

    registration_store.clear_registration(user_id)

    if status != "registered":
        await _rejected(user_id, status, code=emp_code, emp_code=emp_code)
        await line_api.reply_text(reply_token, _REGISTER_FAILURES.get(status, "ไม่สามารถลงทะเบียนได้"))
        return

    await richmenu.link_main(user_id)
    await line_api.reply_text(
        reply_token,
        f"ลงทะเบียนเรียบร้อยแล้ว ✅\nยินดีต้อนรับคุณ {employee.emp_full}\n"
        f"รหัสพนักงาน {employee.emp_code}\n\nกด \"งานขาย\" ที่เมนูด้านล่างเพื่อเริ่มใช้งาน",
    )


# --------------------------------------------------------------------------
# Returning users (already bound, e.g. after block -> unblock)
# --------------------------------------------------------------------------

async def start_reverify(*, line_user_id: str, reply_token: str, employee) -> None:
    """Hide the work menus until the bound employee code is typed again."""
    registration_store.start_reverify(
        line_user_id,
        emp_code=employee.emp_code,
    )

    await richmenu.unlink(line_user_id)
    await line_api.reply_text(
        reply_token,
        f"ยินดีต้อนรับกลับคุณ {employee.emp_full} 👋\n\n"
        "เพื่อยืนยันตัวตน กรุณากรอกรหัสพนักงานของคุณก่อนเข้าใช้งาน",
    )


async def handle_reverify(*, line_user_id: str, reply_token: str, employee, text: str) -> None:
    code = directory.normalize_code(text)

    # One LINE account per employee: only the code bound to this account works.
    if code != employee.emp_code:
        await audit.record(
            Action.EMPLOYEE_REJECTED,
            actor=audit.employee(employee.emp_code),
            emp_code=employee.emp_code,
            line_user_id=line_user_id,
            detail={"reason": "reverify_code_mismatch", "code": code[:EMPLOYEE_CODE_MAX]},
        )
        await line_api.reply_text(
            reply_token,
            "รหัสพนักงานไม่ตรงกับที่ผูกไว้กับบัญชี LINE นี้ กรุณาลองใหม่\n"
            "บัญชี LINE 1 บัญชีใช้ได้กับพนักงาน 1 คนเท่านั้น "
            "ถ้าต้องการเปลี่ยนบัญชี กรุณาติดต่อแอดมิน",
        )
        return

    registration_store.clear_registration(line_user_id)
    await audit.record(
        Action.EMPLOYEE_REVERIFIED,
        actor=audit.employee(employee.emp_code),
        emp_code=employee.emp_code,
        line_user_id=line_user_id,
    )
    await richmenu.link_main(line_user_id)
    await line_api.reply_text(
        reply_token,
        "ยืนยันตัวตนเรียบร้อย ✅\nกด \"งานขาย\" ที่เมนูด้านล่างเพื่อใช้งานต่อ",
    )


@registry.register_postback("cancel_registration")
async def cancel_registration(*, user_id: str, reply_token: str, params: dict) -> None:
    registration = registration_store.get_registration(user_id)

    if not registration:
        await line_api.reply_text(reply_token, "รายการลงทะเบียนนี้หมดอายุแล้ว")
        return

    emp_code = registration["emp_code"]

    if emp_code and params.get("emp_code") != emp_code:
        await line_api.reply_text(reply_token, "รายการนี้หมดอายุแล้ว กรุณาใช้รายการล่าสุด")
        return

    registration_store.clear_registration(user_id)
    await line_api.reply_text(reply_token, "ยกเลิกการลงทะเบียนแล้ว")
