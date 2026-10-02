from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    String,
    func,
)
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
)

from app.db.base import Base


class Employee(Base):
    __tablename__ = "employees"

    emp_code: Mapped[str] = mapped_column(
        String(50),
        primary_key=True,
    )

    emp_fn: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    emp_ln: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    emp_full: Mapped[str] = mapped_column(
        String(300),
        nullable=False,
    )

    emp_department: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    emp_email: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    emp_phone: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    create_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    update_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="true",
    )
