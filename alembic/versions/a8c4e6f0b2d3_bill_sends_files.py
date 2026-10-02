"""bill_sends.files: the slips of each send (backfilled from the audit log)

Revision ID: a8c4e6f0b2d3
Revises: f2a6b8c0d4e1
Create Date: 2026-09-30 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a8c4e6f0b2d3'
down_revision: Union[str, Sequence[str], None] = 'f2a6b8c0d4e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('bill_sends', sa.Column('files', postgresql.JSONB(astext_type=sa.Text()), nullable=True))

    # Sends made before this column: their "invoice.submitted" audit row lists the file paths.
    op.execute("""
        UPDATE bill_sends AS b
        SET files = (
            SELECT jsonb_agg(jsonb_build_object('path', path))
            FROM audit_logs AS a, jsonb_array_elements_text(a.detail -> 'files') AS path
            WHERE a.id = (
                SELECT id FROM audit_logs
                WHERE action = 'invoice.submitted' AND invoice_no = b.invoice_id
                ORDER BY abs(extract(epoch FROM at - b.sent_at))
                LIMIT 1
            )
        )
        WHERE b.files IS NULL
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('bill_sends', 'files')
