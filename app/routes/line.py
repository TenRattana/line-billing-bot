import logging
import traceback

from fastapi import (
    APIRouter,
    Header,
    HTTPException,
    Request,
)
from linebot.v3 import WebhookParser
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import Event

from app.config import LINE_CHANNEL_SECRET
from app.line import event_log
from app.line.dispatcher import dispatch_event

logger = logging.getLogger(__name__)

router = APIRouter()
parser = WebhookParser(LINE_CHANNEL_SECRET)


@router.post("/callback")
async def callback(
    request: Request,
    x_line_signature: str = Header(),
):
    try:
        events = parser.parse((await request.body()).decode("utf-8"), x_line_signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature") from None
    except ValueError:  # bad UTF-8 or JSON
        raise HTTPException(status_code=400, detail="Invalid body") from None

    # One failing event must not drop the rest of the batch. We still return 200:
    # the failure is in webhook_events, and a redelivery is deduped anyway.
    for event in events:
        try:
            await _handle(event)
        except Exception:
            logger.exception("Failed to handle %s event", getattr(event, "type", "?"))

    return {"status": "ok"}


async def _handle(event: Event) -> None:
    if not getattr(event, "webhook_event_id", None):
        return  # an event type the SDK doesn't know

    row_id = await event_log.claim(event)

    if row_id is None:
        logger.info("Skipped duplicate event %s", event.webhook_event_id)
        return

    try:
        handled = await dispatch_event(event)
    except Exception:
        await event_log.finish(row_id, "failed", traceback.format_exc()[-4000:])
        raise

    await event_log.finish(row_id, "processed" if handled else "skipped")
