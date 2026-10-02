"""add user identity profile

Revision ID: 7c1e4b2a9d10
Revises: 580cdba9a300
Create Date: 2026-09-26 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7c1e4b2a9d10'
down_revision: Union[str, Sequence[str], None] = '580cdba9a300'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('user_identities', sa.Column('display_name', sa.String(length=255), nullable=True))
    op.add_column('user_identities', sa.Column('picture_url', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('user_identities', 'picture_url')
    op.drop_column('user_identities', 'display_name')
