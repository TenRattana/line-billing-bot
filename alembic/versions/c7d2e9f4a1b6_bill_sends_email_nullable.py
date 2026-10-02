"""bill sends email nullable

Revision ID: c7d2e9f4a1b6
Revises: b4e8c1d2f3a5
Create Date: 2026-09-28 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7d2e9f4a1b6'
down_revision: Union[str, Sequence[str], None] = 'b4e8c1d2f3a5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column('bill_sends', 'customer_email', existing_type=sa.String(length=255), nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("UPDATE bill_sends SET customer_email = '' WHERE customer_email IS NULL")
    op.alter_column('bill_sends', 'customer_email', existing_type=sa.String(length=255), nullable=False)
