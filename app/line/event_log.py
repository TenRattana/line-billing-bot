"""webhook_events: one row per LINE event, for dedupe and troubleshooting."""

from datetime import datetime, timezone

from linebot.v3.webhooks import Event
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from app.db.models.webhook_event import WebhookEvent
from app.db.session import SessionLocal


async def claim(event: Event) -> int | None:
    """Log the event and return its row id; None if it was seen before (a redelivery).

    The unique webhook_event_id decides, so two copies arriving at once can't both pass.
    """
    delivery = getattr(event, "delivery_context", None)

    async with SessionLocal() as session:
        row = WebhookEvent(
            webhook_event_id=event.webhook_event_id,
            line_user_id=getattr(event.source, "user_id", None),
            event_type=event.type,
            is_redelivery=bool(delivery and delivery.is_redelivery),
            payload=event.to_dict(),
        )
        session.add(row)

        try:
            await session.commit()
        except IntegrityError:
            return None

        return row.id


async def finish(row_id: int, status: str, error: str | None = None) -> None:
    async with SessionLocal() as session:
        await session.execute(
            update(WebhookEvent)
            .where(WebhookEvent.id == row_id)
            .values(status=status, error=error, processed_at=datetime.now(timezone.utc))
        )
        await session.commit()
