"""Add has_linear column to workspaces

Revision ID: 002
"""

from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "workspaces",
        sa.Column("has_linear", sa.Boolean(), server_default="false", nullable=False),
    )


def downgrade():
    op.drop_column("workspaces", "has_linear")
