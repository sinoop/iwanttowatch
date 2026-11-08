"""ai moods and explanations

Revision ID: 4a24521092c4
Revises: 1bedc0b85cf0
Create Date: 2026-11-08 05:48:36.878527
"""

import sqlalchemy as sa
from alembic import op

revision = "4a24521092c4"
down_revision = "1bedc0b85cf0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "explanations",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("tmdb_id", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tmdb_id"],
            ["titles.tmdb_id"],
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "tmdb_id"),
    )
    # Plain ADD COLUMN: rebuilding titles would cascade into the tables that point at it.
    op.add_column("titles", sa.Column("ai_moods", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("titles", "ai_moods")
    op.drop_table("explanations")
