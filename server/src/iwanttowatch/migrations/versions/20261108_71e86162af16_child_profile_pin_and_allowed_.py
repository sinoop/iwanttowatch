"""child profile pin and allowed certificates

Revision ID: 71e86162af16
Revises: 1d22cd1e7f09
Create Date: 2026-11-08 02:42:12.261426
"""

import json

import sqlalchemy as sa
from alembic import op

from iwanttowatch.children import allowed_certificates

revision = "71e86162af16"
down_revision = "1d22cd1e7f09"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("allowed_certificates", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("parent_pin_hash", sa.String(), nullable=True))

    connection = op.get_bind()
    children = connection.execute(
        sa.text("SELECT id, region, max_certificate FROM users WHERE parent_id IS NOT NULL")
    )
    for child_id, region, max_certificate in children.fetchall():
        allowed = allowed_certificates(region, max_certificate or "", None)
        connection.execute(
            sa.text("UPDATE users SET allowed_certificates = :allowed WHERE id = :id"),
            {"allowed": json.dumps(allowed), "id": child_id},
        )
    # Films cached before certificates were stored have none, which hides them from
    # children; refetch them on the next feed build instead of after 30 days.
    connection.execute(
        sa.text(
            "UPDATE titles SET fetched_at = '2000-01-01 00:00:00.000000'"
            " WHERE certifications = '{}'"
        )
    )


def downgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("parent_pin_hash")
        batch_op.drop_column("allowed_certificates")
