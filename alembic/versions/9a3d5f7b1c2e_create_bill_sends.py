"""create bill sends

Revision ID: 9a3d5f7b1c2e
Revises: 7c1e4b2a9d10
Create Date: 2026-09-26 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9a3d5f7b1c2e'
down_revision: Union[str, Sequence[str], None] = '7c1e4b2a9d10'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('bill_sends',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('emp_code', sa.String(length=50), nullable=False),
    sa.Column('invoice_id', sa.String(length=50), nullable=False),
    sa.Column('customer_id', sa.String(length=50), nullable=False),
    sa.Column('customer_name', sa.String(length=255), nullable=False),
    sa.Column('customer_email', sa.String(length=255), nullable=False),
    sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('attachment_count', sa.Integer(), nullable=False),
    sa.Column('sent_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['emp_code'], ['employees.emp_code']),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_bill_sends_emp_code_sent_at', 'bill_sends', ['emp_code', 'sent_at'])
    op.create_index('ix_bill_sends_invoice_id', 'bill_sends', ['invoice_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_bill_sends_invoice_id', table_name='bill_sends')
    op.drop_index('ix_bill_sends_emp_code_sent_at', table_name='bill_sends')
    op.drop_table('bill_sends')
