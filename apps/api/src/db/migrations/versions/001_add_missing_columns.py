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
    # workspaces
    op.add_column(
        "workspaces",
        sa.Column("has_google_calendar", sa.Boolean(), server_default="false", nullable=False),
    )

    # meeting_sessions — adapter columns
    op.add_column(
        "meeting_sessions",
        sa.Column("adapter_type", sa.String(32), server_default="recall", nullable=True),
    )
    op.add_column(
        "meeting_sessions",
        sa.Column("adapter_session_id", sa.String(255), nullable=True),
    )

    # proposals — gate scoring columns
    op.add_column("proposals", sa.Column("gate_scores", sa.JSON(), nullable=True))
    op.add_column("proposals", sa.Column("gate_avg_score", sa.Float(), nullable=True))
    op.add_column("proposals", sa.Column("gate_readiness", sa.Integer(), nullable=True))
    op.add_column("proposals", sa.Column("gate_evidence_quote", sa.Text(), nullable=True))
    op.add_column("proposals", sa.Column("gate_missing_info", sa.JSON(), nullable=True))
    op.add_column("proposals", sa.Column("gate_passed", sa.Boolean(), nullable=True))

    # utterances — widen timestamp from int to bigint
    op.alter_column("utterances", "timestamp_ms", type_=sa.BigInteger(), existing_type=sa.Integer())


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
