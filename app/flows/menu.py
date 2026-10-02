from app.flex.screens import registration as registration_screen
from app.flows import registry
from app.identity import repository
from app.line import api as line_api


@registry.register_postback("my_profile")
async def my_profile(*, user_id: str, reply_token: str, params: dict) -> None:
    employee, identity = await repository.get_line_identity(user_id)
    await line_api.reply_flex(reply_token, registration_screen.profile_screen(employee, identity))


@registry.register_postback("switch_menu")
async def switch_menu(*, user_id: str, reply_token: str, params: dict) -> None:
    """LINE switches the menu itself (richmenuswitch); the postback needs no reply."""
