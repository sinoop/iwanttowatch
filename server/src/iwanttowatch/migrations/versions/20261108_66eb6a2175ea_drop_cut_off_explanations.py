"""drop cut off explanations

Revision ID: 66eb6a2175ea
Revises: 4a24521092c4
Create Date: 2026-11-08 08:58:50.414355
"""

from alembic import op

revision = "66eb6a2175ea"
down_revision = "4a24521092c4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # "Why this?" answers used to be cut at exactly 300 characters, often mid-sentence.
    # Forget those so the button returns and the next answer is kept whole.
    op.execute("DELETE FROM explanations WHERE length(text) = 300")


def downgrade() -> None:
    pass
