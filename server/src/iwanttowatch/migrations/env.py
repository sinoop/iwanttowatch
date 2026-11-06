from alembic import context
from sqlalchemy import Connection

from iwanttowatch import models  # noqa: F401  (registers tables on Base.metadata)
from iwanttowatch.config import Settings
from iwanttowatch.db import Base, create_db_engine


def run(connection: Connection) -> None:
    # Batch mode lets migrations alter SQLite tables, which lack most ALTER TABLE forms.
    context.configure(connection=connection, target_metadata=Base.metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


# The app passes its own connection; the `alembic` CLI falls back to the configured database.
connection = context.config.attributes.get("connection")
if connection is not None:
    run(connection)
else:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    with create_db_engine(settings.database_url).begin() as cli_connection:
        run(cli_connection)
