from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import text
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.sessions import SessionMiddleware

from iwanttowatch import __version__
from iwanttowatch.api import (
    auth,
    backup,
    backups,
    children,
    declutter,
    feed,
    imports,
    invites,
    jellyfin,
    library,
    mcp,
    radar,
    reactions,
    streaming,
    together,
    vote,
)
from iwanttowatch.api import settings as settings_api
from iwanttowatch.backups import BackupWorker, back_up
from iwanttowatch.config import Settings
from iwanttowatch.db import create_db_engine, upgrade_database, upgrade_pending
from iwanttowatch.feed import FeedWorker
from iwanttowatch.imports import ImportWorker
from iwanttowatch.jellyfin import JellyfinWorker

SESSION_MAX_AGE = 30 * 24 * 3600
IMMUTABLE = "public, max-age=31536000, immutable"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    engine = create_db_engine(settings.database_url)
    backup_dir = settings.backup_dir or settings.data_dir / "backups"
    # A copy from before the upgrade, in case a migration goes wrong.
    if upgrade_pending(engine):
        back_up(engine, backup_dir, before_upgrade=True)
    upgrade_database(engine)

    app = FastAPI(title="iWantToWatch", version=__version__)
    app.state.engine = engine
    app.state.tmdb_base_url = settings.tmdb_base_url
    app.state.data_dir = settings.data_dir
    app.state.feed_worker = FeedWorker(engine, settings.tmdb_base_url, settings.data_dir)
    app.state.feed_worker.start()
    # A finished import changes the user's taste, so their feed is rebuilt.
    app.state.import_worker = ImportWorker(
        engine, settings.tmdb_base_url, on_done=app.state.feed_worker.request
    )
    app.state.import_worker.start()
    app.state.jellyfin_worker = JellyfinWorker(engine, settings.tmdb_base_url)
    app.state.jellyfin_worker.start()
    app.state.backup_dir = backup_dir
    BackupWorker(engine, backup_dir).start()
    # Text compresses well: the web app's script is about a third of its size gzipped.
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.resolve_secret_key(),
        session_cookie="iwanttowatch_session",
        max_age=SESSION_MAX_AGE,
        same_site="lax",
    )
    modules = (
        auth, settings_api, imports, library, reactions, jellyfin, streaming, feed, backup,
        backups, together, children, vote, invites, mcp, declutter, radar,
    )  # fmt: skip
    for module in modules:
        app.include_router(module.router)

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"status": "ok"}

    if settings.static_dir is not None:
        _serve_web_app(app, settings.static_dir.resolve())
    return app


def _serve_web_app(app: FastAPI, static_dir: Path) -> None:
    """Serve the built single-page app; unknown non-API paths get index.html."""
    index = static_dir / "index.html"

    @app.get("/{path:path}", include_in_schema=False)
    def web_app(path: str) -> FileResponse:
        # MCP clients look under .well-known for OAuth; they must get a 404, not the app.
        if path == "api" or path.startswith(("api/", ".well-known/")):
            raise HTTPException(404)
        file = (static_dir / path).resolve()
        if path and file.is_file() and file.is_relative_to(static_dir):
            # Built assets have a content hash in their name, so they never change.
            if path.startswith("assets/"):
                return FileResponse(file, headers={"Cache-Control": IMMUTABLE})
            return FileResponse(file)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
