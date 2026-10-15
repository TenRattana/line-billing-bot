import asyncio
import logging
from urllib.parse import parse_qs
from weakref import WeakValueDictionary

from linebot.v3.webhooks import (
    Event,
    FollowEvent,
    MessageEvent,
    PostbackEvent,
    TextMessageContent,
)

# Importing the package runs every flow's registry decorators.
from app.flows import registration as registration_flow
from app.flows.registry import (
    get_message_handler,
    get_postback_handler,
)
from app.identity import (
    registration_store,
    repository,
)
from app.line import api as line_api

logger = logging.getLogger(__name__)


_user_locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()

_REGISTRATION_ACTIONS = {
    "start_registration",
    "confirm_registration",
    "cancel_registration",
}


def user_lock(user_id: str) -> asyncio.Lock:
    lock = _user_locks.get(user_id)

    if lock is None:
        lock = _user_locks[user_id] = asyncio.Lock()

    return lock


def _parse_postback_params(event: PostbackEvent) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(event.postback.data).items()}


async def dispatch_event(event: Event) -> bool:
    """False when the event is ignored (group chats, unfollow, ...), for webhook_events."""

    if getattr(event.source, "type", None) != "user":
        return False

    user_id = getattr(event.source, "user_id", None)
    reply_token = getattr(event, "reply_token", None)

    if not user_id or not reply_token or not isinstance(
        event,
        (MessageEvent, PostbackEvent, FollowEvent),
    ):
        return False

    async with user_lock(user_id):
        employee = await repository.get_employee_by_line_user_id(user_id)

        if employee is None:
            await _dispatch_unregistered(
                event,
                user_id,
                reply_token,
            )
        else:
            await _dispatch_registered(
                event,
                user_id,
                reply_token,
                employee,
            )

    return True


async def _dispatch_registered(event: Event, user_id: str, reply_token: str, employee) -> None:
    params = _parse_postback_params(event) if isinstance(event, PostbackEvent) else {}

    # Unblocked / re-added the bot, or tapped "ลงทะเบียน" on the default menu:
    # already bound, so only the employee code is asked again.
    if isinstance(event, FollowEvent) or params.get("action") == "start_registration":
        await registration_flow.start_reverify(line_user_id=user_id, reply_token=reply_token, employee=employee)
        return

    registration = registration_store.get_registration(user_id)

    if registration and registration["step"] == "reverify":
        if isinstance(event, MessageEvent) and isinstance(event.message, TextMessageContent):
            await registration_flow.handle_reverify(
                line_user_id=user_id,
                reply_token=reply_token,
                employee=employee,
                text=event.message.text,
            )
        else:
            await line_api.reply_text(reply_token, "กรุณากรอกรหัสพนักงานเพื่อเข้าใช้งานต่อ")
        return

    if isinstance(event, MessageEvent):
        await _dispatch_message(event, user_id, reply_token)
    elif isinstance(event, PostbackEvent):
        await _dispatch_postback(params, user_id, reply_token)


async def _dispatch_unregistered(event: Event, user_id: str, reply_token: str) -> None:
    if isinstance(event, PostbackEvent):
        params = _parse_postback_params(event)

        # Unregistered users may only execute registration postbacks.
        if params.get("action") in _REGISTRATION_ACTIONS:
            await _dispatch_postback(params, user_id, reply_token)
            return

    registration = registration_store.get_registration(user_id)

    # "reverify" left over from before an admin released this LINE account: start over.
    if registration is None or registration["step"] == "reverify" or isinstance(event, FollowEvent):
        await registration_flow.start_registration(line_user_id=user_id, reply_token=reply_token)
        return

    if isinstance(event, MessageEvent) and isinstance(event.message, TextMessageContent):
        await registration_flow.handle_text(
            line_user_id=user_id,
            reply_token=reply_token,
            text=event.message.text,
        )
        return

    if isinstance(event, PostbackEvent):
        text = "กรุณาลงทะเบียนให้เสร็จก่อนใช้งานเมนูอื่น"
    elif registration["step"] == "employee_code":
        text = "กรุณากรอกรหัสพนักงานเป็นข้อความ"
    elif registration["step"] == "full_name":
        text = "กรุณาพิมพ์ชื่อ-นามสกุลเป็นข้อความ"
    else:
        text = "กรุณาใช้หน้ายืนยันตัวตนล่าสุด"

    await line_api.reply_text(reply_token, text)


async def _dispatch_message(event: MessageEvent, user_id: str, reply_token: str) -> None:
    handler = get_message_handler(event.message.type)

    if handler:
        await handler(user_id=user_id, reply_token=reply_token, message=event.message)


async def _dispatch_postback(params: dict[str, str], user_id: str, reply_token: str) -> None:
    action = params.get("action")
    handler = get_postback_handler(action)

    if not handler:
        logger.warning("Unknown postback action: %s", action)
        return

    await handler(user_id=user_id, reply_token=reply_token, params=params)
