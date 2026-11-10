"""backfill_reactions_from_ratings

Revision ID: f6ce9db43c48
Revises: 2ba3239edb5d
Create Date: 2026-11-10 12:05:11.239516
"""

from alembic import op

revision = "f6ce9db43c48"
down_revision = "2ba3239edb5d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE user_titles
        SET reaction = CASE
            WHEN rating >= 9.0 THEN 'loved'
            WHEN rating >= 6.0 THEN 'liked'
            ELSE 'disliked'
        END
        WHERE reaction IS NULL AND rating IS NOT NULL
        """
    )


def downgrade() -> None:
    pass
