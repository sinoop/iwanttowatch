import secrets
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from iwanttowatch.api.deps import AdminUser, CurrentUser, DbSession
from iwanttowatch.jellyfin import API_KEY_SETTING as JELLYFIN_KEY_SETTING
from iwanttowatch.jellyfin import (
    STATUS_KEY,
    URL_SETTING,
    WEBHOOK_TOKEN_SETTING,
    JellyfinAuthError,
    JellyfinClient,
    JellyfinError,
)
from iwanttowatch.llm import (
    DEFAULT_GEMINI_MODEL,
    GEMINI_KEY_SETTING,
    MODEL_SETTING,
    OLLAMA_URL_SETTING,
    PROVIDER_SETTING,
    LlmError,
    make_provider,
)
from iwanttowatch.models import ConnectorStatus, LibraryItem, User, get_setting, set_setting
from iwanttowatch.tmdb import API_KEY_SETTING, TmdbAuthError, TmdbClient, TmdbError

router = APIRouter(prefix="/api/v1/settings")

LlmChoice = Literal["none", "ollama", "gemini"]


class LlmSettings(BaseModel):
    provider: LlmChoice
    model: str | None
    ollama_url: str | None
    gemini_configured: bool
    default_gemini_model: str = DEFAULT_GEMINI_MODEL


class JellyfinSettings(BaseModel):
    url: str | None
    linked_users: int
    library_movies: int
    # Items that couldn't be matched to a TMDb movie, as "Name (year)"; at most 20.
    unmatched: list[str]
    unmatched_count: int
    synced_at: datetime | None
    error: str | None
    webhook_at: datetime | None
    # Path and query of the webhook URL, including its secret token; admins only.
    webhook_path: str | None


class ServerSettings(BaseModel):
    tmdb_configured: bool
    llm: LlmSettings
    jellyfin: JellyfinSettings


class TmdbKey(BaseModel):
    # A v3 API key or a v4 API Read Access Token from themoviedb.org/settings/api.
    api_key: str = Field(min_length=16, max_length=1024)


class JellyfinUpdate(BaseModel):
    url: str = Field(min_length=1, max_length=500)
    # An API key from Jellyfin's Dashboard → API Keys. Omit to keep the stored key.
    api_key: str | None = Field(default=None, max_length=200)


class LlmUpdate(BaseModel):
    provider: LlmChoice
    model: str | None = Field(default=None, max_length=200)
    ollama_url: str | None = Field(default=None, max_length=500)
    # Omit to keep the stored Gemini key.
    gemini_api_key: str | None = Field(default=None, max_length=500)


def _utc(value: datetime | None) -> datetime | None:
    # SQLite returns stored UTC times without their time zone.
    return value.replace(tzinfo=UTC) if value else None


def _jellyfin_out(session: Session, is_admin: bool) -> JellyfinSettings:
    url = get_setting(session, URL_SETTING)
    sync = session.get(ConnectorStatus, STATUS_KEY)
    token = get_setting(session, WEBHOOK_TOKEN_SETTING)
    unmatched = (
        select(LibraryItem.name, LibraryItem.year)
        .where(LibraryItem.tmdb_id.is_(None))
        .distinct()
        .subquery()
    )
    return JellyfinSettings(
        url=url,
        linked_users=session.scalar(select(func.count()).where(User.jellyfin_user_id.is_not(None)))
        or 0,
        library_movies=session.scalar(select(func.count(LibraryItem.item_id.distinct()))) or 0,
        unmatched=[
            f"{name} ({year})" if year and str(year) not in name else name
            for name, year in session.execute(
                select(unmatched).order_by(unmatched.c.name).limit(20)
            )
        ],
        unmatched_count=session.scalar(select(func.count()).select_from(unmatched)) or 0,
        synced_at=_utc(sync.synced_at) if sync else None,
        error=sync.error if sync else None,
        webhook_at=_utc(sync.webhook_at) if sync else None,
        webhook_path=f"/api/v1/webhooks/jellyfin?token={token}" if is_admin and token else None,
    )


def _settings_out(session: Session, is_admin: bool) -> ServerSettings:
    # Secrets are never returned, only whether they are set.
    provider = get_setting(session, PROVIDER_SETTING)
    return ServerSettings(
        tmdb_configured=get_setting(session, API_KEY_SETTING) is not None,
        jellyfin=_jellyfin_out(session, is_admin),
        llm=LlmSettings(
            provider="ollama"
            if provider == "ollama"
            else "gemini"
            if provider == "gemini"
            else "none",
            model=get_setting(session, MODEL_SETTING),
            ollama_url=get_setting(session, OLLAMA_URL_SETTING),
            gemini_configured=get_setting(session, GEMINI_KEY_SETTING) is not None,
        ),
    )


@router.get("")
def read_settings(user: CurrentUser, session: DbSession) -> ServerSettings:
    return _settings_out(session, user.is_admin)


@router.put("/tmdb")
def set_tmdb_key(
    body: TmdbKey, _admin: AdminUser, request: Request, session: DbSession
) -> ServerSettings:
    api_key = body.api_key.strip()
    client = TmdbClient(api_key, request.app.state.engine, request.app.state.tmdb_base_url)
    try:
        client.get("/configuration")
    except TmdbAuthError as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "TMDb rejected this key") from error
    except TmdbError as error:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "Couldn't reach TMDb to check the key; try again"
        ) from error
    set_setting(session, API_KEY_SETTING, api_key)
    session.commit()
    return _settings_out(session, True)


@router.put("/jellyfin")
def set_jellyfin(
    body: JellyfinUpdate, _admin: AdminUser, request: Request, session: DbSession
) -> ServerSettings:
    """Connect a Jellyfin server; the API key is checked first, then a full sync starts."""
    url = body.url.strip().rstrip("/")
    api_key = (body.api_key or "").strip() or get_setting(session, JELLYFIN_KEY_SETTING)
    if not api_key:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Enter a Jellyfin API key")
    try:
        JellyfinClient(url, api_key).server_name()
    except JellyfinAuthError as error:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Jellyfin rejected this API key"
        ) from error
    except JellyfinError as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(error)) from error
    set_setting(session, URL_SETTING, url)
    set_setting(session, JELLYFIN_KEY_SETTING, api_key)
    if get_setting(session, WEBHOOK_TOKEN_SETTING) is None:
        set_setting(session, WEBHOOK_TOKEN_SETTING, secrets.token_urlsafe(24))
    session.commit()
    request.app.state.jellyfin_worker.request_full_sync()
    return _settings_out(session, True)


@router.delete("/jellyfin")
def disconnect_jellyfin(_admin: AdminUser, session: DbSession) -> ServerSettings:
    """Stop syncing. Watch history already synced stays; the library listing goes."""
    for key in (URL_SETTING, JELLYFIN_KEY_SETTING, WEBHOOK_TOKEN_SETTING):
        set_setting(session, key, None)
    session.execute(delete(LibraryItem))
    session.execute(delete(ConnectorStatus).where(ConnectorStatus.connector == STATUS_KEY))
    session.commit()
    return _settings_out(session, True)


@router.post("/jellyfin/sync", status_code=status.HTTP_202_ACCEPTED)
def sync_jellyfin(_admin: AdminUser, request: Request) -> None:
    request.app.state.jellyfin_worker.request_full_sync()


@router.put("/llm")
def set_llm(body: LlmUpdate, _admin: AdminUser, session: DbSession) -> ServerSettings:
    """Choose Ollama, Gemini, or no LLM. A short test prompt checks the choice first."""
    if body.provider == "none":
        set_setting(session, PROVIDER_SETTING, None)
        session.commit()
        return _settings_out(session, True)

    gemini_key = (body.gemini_api_key or "").strip() or get_setting(session, GEMINI_KEY_SETTING)
    ollama_url = (body.ollama_url or "").strip() or None
    model = (body.model or "").strip() or (
        DEFAULT_GEMINI_MODEL if body.provider == "gemini" else ""
    )
    if body.provider == "ollama" and not (ollama_url and model):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Enter the Ollama URL and a model name")
    if body.provider == "gemini" and not gemini_key:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Enter a Gemini API key")
    try:
        llm = make_provider(body.provider, model, ollama_url, gemini_key)
        if not llm.generate("Answer with one word.", "Say OK."):
            raise LlmError("The model returned an empty answer")
    except LlmError as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Test failed: {error}") from error

    set_setting(session, PROVIDER_SETTING, body.provider)
    set_setting(session, MODEL_SETTING, model)
    if body.provider == "ollama":
        set_setting(session, OLLAMA_URL_SETTING, ollama_url)
    else:
        set_setting(session, GEMINI_KEY_SETTING, gemini_key)
    session.commit()
    return _settings_out(session, True)
