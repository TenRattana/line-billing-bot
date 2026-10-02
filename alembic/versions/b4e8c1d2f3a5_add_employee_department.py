"""add employee department

Revision ID: b4e8c1d2f3a5
Revises: 9a3d5f7b1c2e
Create Date: 2026-09-26 23:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b4e8c1d2f3a5'
down_revision: Union[str, Sequence[str], None] = '9a3d5f7b1c2e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('employees', sa.Column('emp_department', sa.String(length=150), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('employees', 'emp_department')
