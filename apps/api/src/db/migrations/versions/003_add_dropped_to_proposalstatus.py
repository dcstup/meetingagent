"""Add 'dropped' value to proposalstatus enum

Revision ID: 003
Revises: 002
Create Date: 2026-02-28
"""

from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PostgreSQL requires ALTER TYPE ... ADD VALUE to extend an enum.
    # IF NOT EXISTS guard prevents failure if rerun.
    op.execute("ALTER TYPE proposalstatus ADD VALUE IF NOT EXISTS 'dropped'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values; downgrade is a no-op.
    pass
