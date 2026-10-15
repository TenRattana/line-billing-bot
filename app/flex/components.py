from datetime import datetime
from typing import Any

from app.config import BANGKOK
from app.flex import theme

FlexComponent = dict[str, Any]


# =========================================================
# Primitives
# =========================================================


def text(value: str, **props: Any) -> FlexComponent:
    return {"type": "text", "text": value, **props}


def box(layout: str, *contents: FlexComponent, **props: Any) -> FlexComponent:
    return {"type": "box", "layout": layout, **props, "contents": list(contents)}


def baht(amount: float) -> str:
    return f"{amount:,.2f} บาท"


_THAI_MONTHS = "ม.ค. ก.พ. มี.ค. เม.ย. พ.ค. มิ.ย. ก.ค. ส.ค. ก.ย. ต.ค. พ.ย. ธ.ค.".split()


def thai_datetime(value: datetime) -> str:
    """e.g. 26 ก.ย. 14:30 (Bangkok time)."""
    local = value.astimezone(BANGKOK)
    return f"{local.day} {_THAI_MONTHS[local.month - 1]} {local:%H:%M}"


def button(
    style: str,
    *,
    label: str,
    data: str,
    display_text: str | None = None,
    **props: Any,
) -> FlexComponent:
    action = {"type": "postback", "label": label, "data": data}

    if display_text:
        action["displayText"] = display_text

    return {"type": "button", "style": style, **props, "action": action}


def primary_button(*, label: str, data: str) -> FlexComponent:
    return button("primary", label=label, data=data, height="sm", color=theme.PRIMARY)


def secondary_button(*, label: str, data: str) -> FlexComponent:
    return button("secondary", label=label, data=data, height="sm")


# =========================================================
# Building blocks
# =========================================================


def _pill(value: str, *, color: str, background: str) -> FlexComponent:
    return box(
        "vertical",
        text(value, size="xs", weight="bold", color=color, align="center"),
        backgroundColor=background,
        cornerRadius="12px",
        paddingStart="10px",
        paddingEnd="10px",
        paddingTop="4px",
        paddingBottom="4px",
        flex=0,
    )


def screen_header(
    *,
    label: str,
    title: str,
    subtitle: str,
    step: int | None,
    total_steps: int | None,
    background_color: str | None,
) -> FlexComponent:
    top = [
        text(
            label,
            size="sm",
            weight="bold",
            color=theme.WHITE,
            flex=1,
        )
    ]

    if step is not None and total_steps is not None:
        top.append(_pill(f"{step} / {total_steps}", color=theme.WHITE, background=theme.PRIMARY_DARK,))

    return box(
        "vertical",
        box("horizontal", *top, alignItems="center"),
        text(title, size="xl", weight="bold", color=theme.WHITE, wrap=True,),
        text(subtitle, size="sm", color=theme.HEADER_SUBTITLE, wrap=True,),
        backgroundColor=(background_color if background_color is not None else theme.PRIMARY),
        paddingAll="20px",
        spacing="md",
    )


def title_row(left: FlexComponent, right: FlexComponent) -> FlexComponent:
    return box("horizontal", left, right, alignItems="center")


def section_title(value: str) -> FlexComponent:
    return text(value, size="xs", weight="bold", color=theme.TEXT_SECONDARY)


def info_row(*, label: str, value: str, emphasis: bool = False) -> FlexComponent:
    return box(
        "horizontal",
        text(label, size="sm", color=theme.TEXT_SECONDARY, flex=3, wrap=True),
        text(
            value,
            size="sm",
            weight="bold" if emphasis else "regular",
            color=theme.PRIMARY if emphasis else theme.TEXT_PRIMARY,
            align="end",
            flex=5,
            wrap=True,
        ),
        spacing="md",
    )


def summary_card(contents: list[FlexComponent]) -> FlexComponent:
    return box(
        "vertical",
        *contents,
        spacing="md",
        paddingAll="16px",
        backgroundColor=theme.SURFACE,
        cornerRadius=theme.CARD_RADIUS,
        borderWidth="1px",
        borderColor=theme.BORDER_LIGHT,
    )


def info_card(*rows: tuple) -> FlexComponent:
    """Summary card of info rows: (label, value) or (label, value, emphasis)."""
    return summary_card([info_row(label=label, value=value, emphasis=bool(flag)) for label, value, *flag in rows])


def list_row(*, title: str, subtitle: str, value: str, note: str) -> FlexComponent:
    """Compact read-only row: title/subtitle on the left, value/note on the right."""
    return box(
        "horizontal",
        box(
            "vertical",
            text(title, size="sm", weight="bold", color=theme.TEXT_PRIMARY),
            text(subtitle, size="xs", color=theme.TEXT_SECONDARY, wrap=True),
            flex=3,
        ),
        box(
            "vertical",
            text(value, size="sm", weight="bold", color=theme.PRIMARY, align="end"),
            text(note, size="xs", color=theme.TEXT_MUTED, align="end"),
            flex=2,
        ),
        spacing="md",
    )


def list_card(rows: list[FlexComponent], *, empty_text: str, limit: int = 15) -> FlexComponent:
    """Rows split by separators; overflow collapses into a "+N more" line."""
    if not rows:
        return summary_card([text(empty_text, size="sm", color=theme.TEXT_MUTED, align="center", wrap=True)])

    contents = []

    for row in rows[:limit]:
        if contents:
            contents.append({"type": "separator", "color": theme.BORDER_LIGHT})
        contents.append(row)

    if len(rows) > limit:
        contents.append(text(f"และอีก {len(rows) - limit} รายการ", size="xs", color=theme.TEXT_MUTED, align="center"))

    return summary_card(contents)


def selectable_item(
    *,
    index: int,
    title: str,
    subtitle: str,
    uri: str,
    detail: str | None = None,
) -> FlexComponent:
    lines = [
        text(title, size="sm", weight="bold", color=theme.TEXT_PRIMARY, wrap=True),
        text(subtitle, size="xs", color=theme.TEXT_MUTED, wrap=True),
    ]

    if detail:
        lines.append(text(detail, size="xs", color=theme.TEXT_SECONDARY, wrap=True))

    return box(
        "horizontal",
        box(
            "vertical",
            text(f"{index:02}", size="sm", weight="bold", color=theme.PRIMARY, align="center"),
            width="42px",
            height="42px",
            flex=0,
            backgroundColor=theme.PRIMARY_LIGHT,
            cornerRadius="21px",
            justifyContent="center",
        ),
        box("vertical", *lines, flex=1, spacing="xs"),
        text("›", size="xl", color=theme.TEXT_MUTED, gravity="center", align="end", flex=0),
        spacing="md",
        paddingAll="14px",
        backgroundColor=theme.SURFACE,
        cornerRadius=theme.ITEM_RADIUS,
        borderWidth="1px",
        borderColor=theme.BORDER_LIGHT,
        alignItems="center",
        action={"type": "uri", "uri": uri},
    )


# =========================================================
# Screens
# =========================================================


def build_screen(
    *,
    alt_text: str,
    label: str,
    title: str,
    subtitle: str,
    contents: list[FlexComponent],
    step: int | None = None,
    total_steps: int | None = None,
    footer: list[FlexComponent] | None = None,
    footer_note: str | None = None,
    background_color:str | None = None,
) -> dict:
    body = [
        screen_header(
            label=label,
            title=title,
            subtitle=subtitle,
            step=step,
            total_steps=total_steps,
            background_color=background_color
        ),
        box("vertical", *contents, paddingAll=theme.PAGE_PADDING, spacing="md"),
    ]

    if footer_note:
        body.append(
            box(
                "vertical",
                text(footer_note, size="xs", color=theme.TEXT_MUTED, align="center", wrap=True),
                paddingStart="16px",
                paddingEnd="16px",
                paddingBottom="16px",
            )
        )

    bubble: dict[str, Any] = {
        "type": "bubble",
        "size": "mega",
        "body": box("vertical", *body, paddingAll="0px"),
    }

    if footer:
        bubble["footer"] = box("vertical", *footer, spacing="sm", paddingAll="16px")

    return {"type": "flex", "altText": alt_text, "contents": bubble}


def billing_screen(*, step: int, **kwargs: Any) -> dict:
    """The 3-step "ส่งบิล" flow: customer (then invoices in LIFF), attachment, confirm/result."""
    return build_screen(label="ส่งบิล", step=step, total_steps=3, **kwargs)


def cancel_button() -> FlexComponent:
    # A fresh dict each call: postback data is mutated when a screen is sent.
    return secondary_button(label="ยกเลิก", data="action=cancel_send")
