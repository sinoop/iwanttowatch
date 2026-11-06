from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import text
from starlette.middleware.sessions import SessionMiddleware

from iwanttowatch.api import auth, imports, library, reactions
from iwanttowatch.api import settings as settings_api
from iwanttowatch.config import Settings
from iwanttowatch.db import create_db_engine, upgrade_database
from iwanttowatch.imports import ImportWorker

SESSION_MAX_AGE = 30 * 24 * 3600


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    engine = create_db_engine(settings.database_url)
    upgrade_database(engine)

    app = FastAPI(title="iWantToWatch", version="0.1.0")
    app.state.engine = engine
    app.state.tmdb_base_url = settings.tmdb_base_url
    app.state.import_worker = ImportWorker(engine, settings.tmdb_base_url)
    app.state.import_worker.start()
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.resolve_secret_key(),
        session_cookie="iwanttowatch_session",
        max_age=SESSION_MAX_AGE,
        same_site="lax",
    )
    for module in (auth, settings_api, imports, library, reactions):
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
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404)
        file = (static_dir / path).resolve()
        if path and file.is_file() and file.is_relative_to(static_dir):
            return FileResponse(file)
        return FileResponse(index)
