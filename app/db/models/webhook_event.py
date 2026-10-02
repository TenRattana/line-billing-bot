from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
)

from app.db.base import Base
from app.db.models.audit_log import JSONType


class WebhookEvent(Base):
    """Every event LINE delivered, one row each (ported from line_oa).

    1. Dedupe: LINE redelivers an event it isn't sure we got, with the same
       webhook_event_id; the unique key makes each event run once.
    2. Troubleshooting: "I sent it but nothing happened" -> did it arrive,
       and did it fail (error)?
    """

    __tablename__ = "webhook_events"

    __table_args__ = (
        Index("ix_webhook_events_received_at", "received_at"),
        Index("ix_webhook_events_line_user_id", "line_user_id"),
        Index("ix_webhook_events_status", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    webhook_event_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    line_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    is_redelivery: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # received -> processed / skipped (nothing to do for it) / failed
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="received")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)

    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
