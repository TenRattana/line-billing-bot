from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    Index,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
)

from app.db.base import Base

JSONType = JSON().with_variant(JSONB(), "postgresql")


class AuditLog(Base):
    """Who did what, to what, when (ported from line_oa).

    Unlike webhook_events (raw input from LINE), this records what the system
    decided to do, so it reads as the timeline of a bill or an employee.

    Rows are history: no foreign keys, so they outlive the rows they mention,
    and actor_label / detail stay readable after those rows change.
    """

    __tablename__ = "audit_logs"

    __table_args__ = (
        Index("ix_audit_logs_at", "at"),
        Index("ix_audit_logs_action_at", "action", "at"),
        Index("ix_audit_logs_emp_code_at", "emp_code", "at"),
        Index("ix_audit_logs_invoice_no_at", "invoice_no", "at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # <thing>.<verb>, e.g. invoice.submitted, so a group filters as "invoice.%"
    action: Mapped[str] = mapped_column(String(32), nullable=False)

    # Who: employee / line_user (not registered yet) / admin
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    # emp_code, LINE user id, or the admin's OS user name
    actor_label: Mapped[str] = mapped_column(String(64), nullable=False)

    # What it was done to; empty when it doesn't apply
    emp_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    line_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    invoice_no: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Extra facts, e.g. why a file was rejected or where it was stored
    detail: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
