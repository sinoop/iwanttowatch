"""household child profiles

Revision ID: 4cba2eb9e6af
Revises: 66eb6a2175ea
Create Date: 2026-11-08 22:58:20.305026
"""

from datetime import date

import sqlalchemy as sa
from alembic import op

from iwanttowatch.children import age_for_certificate

revision = "4cba2eb9e6af"
down_revision = "66eb6a2175ea"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("is_child", sa.Boolean(), nullable=False, server_default=sa.false())
        )

    connection = op.get_bind()
    connection.execute(sa.text("UPDATE users SET is_child = 1 WHERE parent_id IS NOT NULL"))
    year = date.today().year
    children = connection.execute(
        sa.text(
            "SELECT id, region, max_certificate FROM users"
            " WHERE is_child = 1 AND birth_year IS NULL"
        )
    )
    for child_id, region, max_certificate in children.fetchall():
        age = age_for_certificate(region, max_certificate or "")
        birth_year = year - (age if age is not None else 7)
        connection.execute(
            sa.text("UPDATE users SET birth_year = :birth_year WHERE id = :id"),
            {"birth_year": birth_year, "id": child_id},
        )

    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_constraint("fk_users_parent_id_users", type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_users_parent_id"))
        batch_op.drop_column("parent_pin_hash")
        batch_op.drop_column("parent_id")


def downgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("parent_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("parent_pin_hash", sa.String(), nullable=True))
        batch_op.create_foreign_key(
            "fk_users_parent_id_users", "users", ["parent_id"], ["id"], ondelete="CASCADE"
        )
        batch_op.create_index(batch_op.f("ix_users_parent_id"), ["parent_id"], unique=False)
        batch_op.drop_column("is_child")
