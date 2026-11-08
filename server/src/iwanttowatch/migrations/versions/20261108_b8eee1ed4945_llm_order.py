"""llm order: one chosen provider becomes an ordered list, with a model per provider

Revision ID: b8eee1ed4945
Revises: 94a79790ce86
Create Date: 2026-11-08 05:00:04.484564
"""

import sqlalchemy as sa
from alembic import op

revision = "b8eee1ed4945"
down_revision = "94a79790ce86"
branch_labels = None
depends_on = None


def upgrade() -> None:
    settings = sa.table("app_settings", sa.column("key", sa.String), sa.column("value", sa.Text))
    conn = op.get_bind()
    stored = dict(
        conn.execute(
            sa.select(settings.c.key, settings.c.value).where(
                settings.c.key.in_(["llm_provider", "llm_model"])
            )
        ).all()
    )
    provider, model = stored.get("llm_provider"), stored.get("llm_model")
    if provider in ("ollama", "gemini"):
        op.bulk_insert(settings, [{"key": "llm_order", "value": provider}])
        if model:
            op.bulk_insert(settings, [{"key": f"{provider}_model", "value": model}])
    op.execute(settings.delete().where(settings.c.key.in_(["llm_provider", "llm_model"])))


def downgrade() -> None:
    settings = sa.table("app_settings", sa.column("key", sa.String), sa.column("value", sa.Text))
    conn = op.get_bind()
    stored = dict(conn.execute(sa.select(settings.c.key, settings.c.value)).all())
    provider = (stored.get("llm_order") or "").split(",")[0]
    if provider in ("ollama", "gemini"):
        rows = [{"key": "llm_provider", "value": provider}]
        if model := stored.get(f"{provider}_model"):
            rows.append({"key": "llm_model", "value": model})
        op.bulk_insert(settings, rows)
    op.execute(
        settings.delete().where(settings.c.key.in_(["llm_order", "ollama_model", "gemini_model"]))
    )
