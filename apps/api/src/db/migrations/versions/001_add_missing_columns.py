"""add missing columns: adapter fields, gate fields, bigint timestamp

Revision ID: 001
Revises:
Create Date: 2026-02-28
"""

from alembic import op
import sqlalchemy as sa

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Use raw SQL with IF NOT EXISTS so this migration is safe to re-run on a
    # database where some or all columns were applied manually before Alembic
    # tracking was set up.

    # workspaces
    op.execute(
        "ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS has_google_calendar BOOLEAN NOT NULL DEFAULT false"
    )

    # meeting_sessions — adapter columns
    op.execute(
        "ALTER TABLE meeting_sessions ADD COLUMN IF NOT EXISTS adapter_type VARCHAR(32) DEFAULT 'recall'"
    )
    op.execute(
        "ALTER TABLE meeting_sessions ADD COLUMN IF NOT EXISTS adapter_session_id VARCHAR(255)"
    )

    # proposals — gate scoring columns
    op.execute("ALTER TABLE proposals ADD COLUMN IF NOT EXISTS gate_scores JSONB")
    op.execute("ALTER TABLE proposals ADD COLUMN IF NOT EXISTS gate_avg_score FLOAT")
    op.execute("ALTER TABLE proposals ADD COLUMN IF NOT EXISTS gate_readiness INTEGER")
    op.execute("ALTER TABLE proposals ADD COLUMN IF NOT EXISTS gate_evidence_quote TEXT")
    op.execute("ALTER TABLE proposals ADD COLUMN IF NOT EXISTS gate_missing_info JSONB")
    op.execute("ALTER TABLE proposals ADD COLUMN IF NOT EXISTS gate_passed BOOLEAN")

    # utterances — widen timestamp from int to bigint (idempotent: ALTER TYPE to same type is a no-op)
    op.execute(
        "ALTER TABLE utterances ALTER COLUMN timestamp_ms TYPE BIGINT USING timestamp_ms::BIGINT"
    )


def downgrade() -> None:
    op.alter_column("utterances", "timestamp_ms", type_=sa.Integer(), existing_type=sa.BigInteger())

    op.drop_column("proposals", "gate_passed")
    op.drop_column("proposals", "gate_missing_info")
    op.drop_column("proposals", "gate_evidence_quote")
    op.drop_column("proposals", "gate_readiness")
    op.drop_column("proposals", "gate_avg_score")
    op.drop_column("proposals", "gate_scores")

    op.drop_column("meeting_sessions", "adapter_session_id")
    op.drop_column("meeting_sessions", "adapter_type")

    op.drop_column("workspaces", "has_google_calendar")
