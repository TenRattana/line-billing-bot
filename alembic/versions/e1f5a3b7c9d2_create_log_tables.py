"""create log tables: audit_logs, webhook_events

Revision ID: e1f5a3b7c9d2
Revises: c7d2e9f4a1b6
Create Date: 2026-09-28 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e1f5a3b7c9d2'
down_revision: Union[str, Sequence[str], None] = 'c7d2e9f4a1b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('audit_logs',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('action', sa.String(length=32), nullable=False),
    sa.Column('actor_type', sa.String(length=16), nullable=False),
    sa.Column('actor_label', sa.String(length=64), nullable=False),
    sa.Column('emp_code', sa.String(length=50), nullable=True),
    sa.Column('line_user_id', sa.String(length=64), nullable=True),
    sa.Column('invoice_no', sa.String(length=100), nullable=True),
    sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_audit_logs_at', 'audit_logs', ['at'])
    op.create_index('ix_audit_logs_action_at', 'audit_logs', ['action', 'at'])
    op.create_index('ix_audit_logs_emp_code_at', 'audit_logs', ['emp_code', 'at'])
    op.create_index('ix_audit_logs_invoice_no_at', 'audit_logs', ['invoice_no', 'at'])

    op.create_table('webhook_events',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('webhook_event_id', sa.String(length=64), nullable=False),
    sa.Column('line_user_id', sa.String(length=64), nullable=True),
    sa.Column('event_type', sa.String(length=32), nullable=False),
    sa.Column('is_redelivery', sa.Boolean(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('received_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('webhook_event_id')
    )
    op.create_index('ix_webhook_events_received_at', 'webhook_events', ['received_at'])
    op.create_index('ix_webhook_events_line_user_id', 'webhook_events', ['line_user_id'])
    op.create_index('ix_webhook_events_status', 'webhook_events', ['status'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('webhook_events')
    op.drop_table('audit_logs')
