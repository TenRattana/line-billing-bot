"""Rich menus by user state:

    unregistered (default) -> main (linked on registration) <-> sales (alias switch)

`setup()` runs on app start. A menu's name carries a hash of its definition and
image, so changing either creates a fresh menu and deletes the outdated one.
Switching between main and sales happens in the LINE app via rich menu aliases.
"""

import hashlib
import io
import json
import logging
import math
import os
import re
from glob import glob

from linebot.v3.messaging import (
    ApiException,
    CreateRichMenuAliasRequest,
    RichMenuBulkLinkRequest,
    RichMenuRequest,
    UpdateRichMenuAliasRequest,
)
from PIL import Image, ImageDraw, ImageFont

from app.line import api as line_api

logger = logging.getLogger(__name__)

WIDTH, HEIGHT = 2500, 1024
BULK_LINK_LIMIT = 500
_MANAGED_NAME = re.compile(r"^[a-z]+-[0-9a-f]{10}$")  # menus this module created


def _alias(key: str) -> str:
    return f"billing-{key}"


def _postback(action: str, display_text: str) -> dict:
    return {"type": "postback", "data": f"action={action}", "displayText": display_text}


def _switch(key: str) -> dict:
    return {"type": "richmenuswitch", "richMenuAliasId": _alias(key), "data": "action=switch_menu"}


# key -> (columns, [(label, action)]); buttons fill a grid left-to-right.
MENUS = {
    "unregistered": (1, [
        ("ลงทะเบียน", _postback("start_registration", "ลงทะเบียน")),
    ]),
    "main": (2, [
        ("งานขาย", _switch("sales")),
        ("ข้อมูลของฉัน", _postback("my_profile", "ข้อมูลของฉัน")),
    ]),
    "sales": (2, [
        ("ส่งบิล", _postback("send_bill", "ส่งบิล")),
        ("เช็คงานค้าง", _postback("pending_bills", "เช็คงานค้าง")),
        ("ประวัติส่งบิล", _postback("bill_history", "ประวัติส่งบิล")),
        ("ย้อนกลับ", _switch("main")),
    ]),
}

# Menus the user switches between with richmenuswitch actions.
SWITCHABLE = ("main", "sales")

# Filled by setup(): key -> rich menu id.
rich_menu_ids: dict[str, str] = {}


def _font_path() -> str | None:
    # Needs a Thai-capable font; the Docker image installs fonts-tlwg-loma-ttf.
    candidates = [
        os.getenv("RICH_MENU_FONT", ""),
        *glob("/usr/share/fonts/*/tlwg/Loma*"),
        "C:/Windows/Fonts/tahoma.ttf",
    ]
    return next((path for path in candidates if path and os.path.isfile(path)), None)


def _fit_font(draw: ImageDraw.ImageDraw, label: str, max_width: float) -> ImageFont.FreeTypeFont:
    path = _font_path()

    if not path:
        # ponytail: fallback font has no Thai glyphs, set RICH_MENU_FONT if labels show boxes
        return ImageFont.load_default(90)

    size = 110
    while size > 40 and draw.textlength(label, font=ImageFont.truetype(path, size)) > max_width:
        size -= 5
    return ImageFont.truetype(path, size)


def _cells(columns: int, count: int) -> list[tuple[int, int, int, int]]:
    """(x, y, width, height) of each grid cell."""
    rows = math.ceil(count / columns)
    width, height = WIDTH // columns, HEIGHT // rows
    return [((i % columns) * width, (i // columns) * height, width, height) for i in range(count)]


def _render(columns: int, labels: list[str]) -> bytes:
    """Placeholder image: one tile per button."""
    image = Image.new("RGB", (WIDTH, HEIGHT), "#315EFB")
    draw = ImageDraw.Draw(image)

    for (x, y, width, height), label in zip(_cells(columns, len(labels)), labels, strict=True):
        draw.rounded_rectangle((x + 16, y + 16, x + width - 16, y + height - 16), radius=28, fill="#2448C8")
        font = _fit_font(draw, label, width - 120)
        draw.text((x + width / 2, y + height / 2), label, font=font, fill="#FFFFFF", anchor="mm")

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _definition(columns: int, buttons: list[tuple[str, dict]]) -> dict:
    return {
        "size": {"width": WIDTH, "height": HEIGHT},
        "selected": True,
        "name": "",
        "chatBarText": "เมนู",
        "areas": [
            {"bounds": {"x": x, "y": y, "width": width, "height": height}, "action": action}
            for (x, y, width, height), (_, action) in zip(_cells(columns, len(buttons)), buttons, strict=True)
        ],
    }


async def _ensure_menu(key: str, existing: dict[str, str]) -> str:
    columns, buttons = MENUS[key]
    definition = _definition(columns, buttons)
    image = _render(columns, [label for label, _ in buttons])

    digest = hashlib.sha1(json.dumps(definition, sort_keys=True).encode() + image).hexdigest()[:10]
    definition["name"] = name = f"{key}-{digest}"

    if name in existing:
        return existing[name]

    menu_id = (await (await line_api.messaging()).create_rich_menu(RichMenuRequest.from_dict(definition))).rich_menu_id
    await (await line_api.blob()).set_rich_menu_image(menu_id, image, _headers={"Content-Type": "image/png"})
    logger.info("Created rich menu %s (%s)", name, menu_id)
    return menu_id


async def setup(registered_line_user_ids: list[str]) -> None:
    messaging = await line_api.messaging()
    existing = {
        menu.name: menu.rich_menu_id
        for menu in (await messaging.get_rich_menu_list()).richmenus
        if _MANAGED_NAME.match(menu.name)
    }

    for key in MENUS:
        rich_menu_ids[key] = await _ensure_menu(key, existing)

    # Point aliases at the current menus before deleting the old ones they may reference.
    aliases = {
        alias.rich_menu_alias_id: alias.rich_menu_id
        for alias in (await messaging.get_rich_menu_alias_list()).aliases
    }

    for key in SWITCHABLE:
        alias, menu_id = _alias(key), rich_menu_ids[key]

        if alias not in aliases:
            await messaging.create_rich_menu_alias(
                CreateRichMenuAliasRequest(rich_menu_alias_id=alias, rich_menu_id=menu_id)
            )
        elif aliases[alias] != menu_id:
            await messaging.update_rich_menu_alias(alias, UpdateRichMenuAliasRequest(rich_menu_id=menu_id))

    for menu_id in set(existing.values()) - set(rich_menu_ids.values()):
        await messaging.delete_rich_menu(menu_id)

    await messaging.set_default_rich_menu(rich_menu_ids["unregistered"])

    # Registered users start from the main menu after every deploy.
    for start in range(0, len(registered_line_user_ids), BULK_LINK_LIMIT):
        await messaging.link_rich_menu_id_to_users(
            RichMenuBulkLinkRequest(
                rich_menu_id=rich_menu_ids["main"],
                user_ids=registered_line_user_ids[start : start + BULK_LINK_LIMIT],
            )
        )


async def unlink(line_user_id: str) -> None:
    """Back to the default (ลงทะเบียน) menu."""
    try:
        await (await line_api.messaging()).unlink_rich_menu_id_from_user(line_user_id)
    except ApiException as error:
        logger.warning("Unlink rich menu failed for %s: HTTP %s", line_user_id, error.status)


async def link_main(line_user_id: str) -> None:
    menu_id = rich_menu_ids.get("main")

    if not menu_id:
        return

    # Registration already succeeded; a menu failure must not break the reply.
    # Next app start re-links every registered user anyway.
    try:
        await (await line_api.messaging()).link_rich_menu_id_to_user(line_user_id, menu_id)
    except ApiException as error:
        logger.warning("Link rich menu failed for %s: HTTP %s", line_user_id, error.status)
