"""ai review ratings

Revision ID: 497013f768dc
Revises: 4e5996350eee
Create Date: 2026-11-08 03:45:13.327034
"""

import sqlalchemy as sa
from alembic import op

revision = "497013f768dc"
down_revision = "4e5996350eee"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("ai_picks", schema=None) as batch_op:
        batch_op.add_column(sa.Column("rating", sa.Double(), nullable=True))
        # Picks from before the review were all films the LLM added.
        batch_op.add_column(
            sa.Column("added", sa.Boolean(), nullable=False, server_default=sa.true())
        )


def downgrade() -> None:
    with op.batch_alter_table("ai_picks", schema=None) as batch_op:
        batch_op.drop_column("added")
        batch_op.drop_column("rating")
