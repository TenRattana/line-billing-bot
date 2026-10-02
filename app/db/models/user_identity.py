from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
)

from app.db.base import Base


class UserIdentity(Base):
    __tablename__ = "user_identities"

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "external_id",
            name="uq_user_identity_provider_external",
        ),
        UniqueConstraint(
            "provider",
            "emp_code",
            name="uq_user_identity_provider_employee",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )

    emp_code: Mapped[str] = mapped_column(
        String(50),
        ForeignKey(
            "employees.emp_code",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    provider: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    external_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    # Provider profile snapshot taken at registration (LINE displayName / pictureUrl).
    display_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    picture_url: Mapped[str | None] = mapped_column(
        Text,
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
