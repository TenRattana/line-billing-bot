from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
)

from app.db.base import Base
from app.db.models.audit_log import JSONType


class BillSend(Base):
    """One confirmed "ส่งบิล". Customer fields are a snapshot at send time."""

    __tablename__ = "bill_sends"

    __table_args__ = (
        Index("ix_bill_sends_emp_code_sent_at", "emp_code", "sent_at"),
        Index("ix_bill_sends_invoice_id", "invoice_id"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )

    emp_code: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("employees.emp_code"),
        nullable=False,
    )

    invoice_id: Mapped[str] = mapped_column(String(50), nullable=False)
    customer_id: Mapped[str] = mapped_column(String(50), nullable=False)
    customer_name: Mapped[str] = mapped_column(String(255), nullable=False)
    customer_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    attachment_count: Mapped[int] = mapped_column(Integer, nullable=False)

    # The slips sent: [{"path", "mime_type", "original_filename", "file_size"}]
    files: Mapped[list | None] = mapped_column(JSONType, nullable=True)

    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
