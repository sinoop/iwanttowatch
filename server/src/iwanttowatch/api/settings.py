import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from iwanttowatch import __version__, imdb
from iwanttowatch.api import mcp
from iwanttowatch.api.deps import AdminUser, CurrentUser, DbSession
from iwanttowatch.db import utcnow
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
    GEMINI_MODEL_SETTING,
    OLLAMA_MODEL_SETTING,
    OLLAMA_URL_SETTING,
    ORDER_SETTING,
    LlmError,
    ProviderName,
    llm_order,
    make_provider,
)
from iwanttowatch.models import (
    ConnectorStatus,
    LibraryItem,
    LlmCall,
    Title,
    User,
    get_setting,
    set_setting,
)
from iwanttowatch.tmdb import API_KEY_SETTING, TmdbAuthError, TmdbClient, TmdbError

router = APIRouter(prefix="/api/v1/settings")


class LlmSettings(BaseModel):
    # The providers in use, asked in this order until one answers; empty means off.
    order: list[ProviderName]
    ollama_url: str | None
    ollama_model: str | None
    gemini_configured: bool
    gemini_model: str | None
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


class ImdbSettings(BaseModel):
    enabled: bool
    # When IMDb's ratings file was last downloaded, and why the last download failed.
    updated_at: datetime | None
    error: str | None
    # Films in the catalogue that have an IMDb rating.
    rated_films: int


class ServerSettings(BaseModel):
    # The running release, from the package metadata (pyproject.toml).
    version: str
    tmdb_configured: bool
    # Whether an admin created a key for the read-only debugging MCP server at /mcp.
    mcp_enabled: bool
    llm: LlmSettings
    jellyfin: JellyfinSettings
    imdb: ImdbSettings


class ImdbUpdate(BaseModel):
    enabled: bool


class LlmCallOut(BaseModel):
    id: int
    created_at: datetime
    purpose: str
    provider: str
    model: str
    # Whose taste the call was about, for suggestions and personas.
    user: str | None
    system: str
    prompt: str
    reply: str | None
    error: str | None
    duration_ms: int


class LlmActivity(BaseModel):
    last_hour: int
    last_day: int
    failed_last_day: int
    # Newest first.
    calls: list[LlmCallOut]


class TmdbKey(BaseModel):
    # A v3 API key or a v4 API Read Access Token from themoviedb.org/settings/api.
    api_key: str = Field(min_length=16, max_length=1024)


class JellyfinUpdate(BaseModel):
    url: str = Field(min_length=1, max_length=500)
    # An API key from Jellyfin's Dashboard → API Keys. Omit to keep the stored key.
    api_key: str | None = Field(default=None, max_length=200)


class LlmOrder(BaseModel):
    order: list[ProviderName]


class LlmUpdate(BaseModel):
    provider: ProviderName
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


def _imdb_out(session: Session) -> ImdbSettings:
    state = session.get(ConnectorStatus, imdb.STATUS_KEY)
    return ImdbSettings(
        enabled=imdb.enabled(session),
        updated_at=_utc(state.synced_at) if state else None,
        error=state.error if state else None,
        rated_films=session.scalar(select(func.count()).where(Title.imdb_votes.is_not(None))) or 0,
    )


def _settings_out(session: Session, is_admin: bool) -> ServerSettings:
    # Secrets are never returned, only whether they are set.
    return ServerSettings(
        version=__version__,
        tmdb_configured=get_setting(session, API_KEY_SETTING) is not None,
        mcp_enabled=get_setting(session, mcp.KEY_SETTING) is not None,
        jellyfin=_jellyfin_out(session, is_admin),
        imdb=_imdb_out(session),
        llm=LlmSettings(
            order=llm_order(session),
            ollama_url=get_setting(session, OLLAMA_URL_SETTING),
            ollama_model=get_setting(session, OLLAMA_MODEL_SETTING),
            gemini_configured=get_setting(session, GEMINI_KEY_SETTING) is not None,
            gemini_model=get_setting(session, GEMINI_MODEL_SETTING),
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


def _set_order(session: Session, order: list[ProviderName]) -> None:
    set_setting(session, ORDER_SETTING, ",".join(order) or None)


@router.put("/llm/order")
def order_llms(body: LlmOrder, _admin: AdminUser, session: DbSession) -> ServerSettings:
    """Which provider is asked first; the next answers when it fails."""
    if sorted(body.order) != sorted(llm_order(session)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "List each provider in use once")
    _set_order(session, body.order)
    session.commit()
    return _settings_out(session, True)


@router.delete("/llm/{provider}")
def remove_llm(provider: ProviderName, _admin: AdminUser, session: DbSession) -> ServerSettings:
    """Stop using a provider; its settings stay for turning it back on."""
    _set_order(session, [name for name in llm_order(session) if name != provider])
    session.commit()
    return _settings_out(session, True)


@router.put("/llm")
def set_llm(body: LlmUpdate, _admin: AdminUser, session: DbSession) -> ServerSettings:
    """Set up Ollama or Gemini, after a short test prompt. A new provider is asked after
    the ones already in use."""
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
        llm = make_provider(session, "test", body.provider, model, ollama_url, gemini_key)
        if not llm.generate("Answer with one word.", "Say OK."):
            raise LlmError("The model returned an empty answer")
    except LlmError as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Test failed: {error}") from error

    if body.provider == "ollama":
        set_setting(session, OLLAMA_URL_SETTING, ollama_url)
        set_setting(session, OLLAMA_MODEL_SETTING, model)
    else:
        set_setting(session, GEMINI_KEY_SETTING, gemini_key)
        set_setting(session, GEMINI_MODEL_SETTING, model)
    order = llm_order(session)
    if body.provider not in order:
        _set_order(session, [*order, body.provider])
    session.commit()
    return _settings_out(session, True)


@router.put("/imdb")
def set_imdb(
    body: ImdbUpdate, _admin: AdminUser, request: Request, session: DbSession
) -> ServerSettings:
    """Use IMDb's ratings for films' quality, under IMDb's non-commercial terms. Turning
    them on rebuilds every feed, which downloads them; turning them off removes them."""
    users = session.scalars(select(User.id)).all()
    worker = request.app.state.feed_worker
    if body.enabled:
        set_setting(session, imdb.SETTING, "on")
        session.commit()
        for user_id in users:
            worker.request(user_id)
    else:
        set_setting(session, imdb.SETTING, None)
        imdb.forget_ratings(session, request.app.state.data_dir)
        for user_id in users:
            worker.rescore_soon(user_id)
    return _settings_out(session, True)


class McpKey(BaseModel):
    # Shown once; only its hash is stored.
    key: str


@router.post("/mcp")
def create_mcp_key(_admin: AdminUser, session: DbSession) -> McpKey:
    """A key for the debugging MCP server, replacing any earlier one."""
    key = mcp.create_key(session)
    session.commit()
    return McpKey(key=key)


@router.delete("/mcp")
def remove_mcp_key(_admin: AdminUser, session: DbSession) -> ServerSettings:
    """Turn the MCP server off by forgetting its key."""
    set_setting(session, mcp.KEY_SETTING, None)
    session.commit()
    return _settings_out(session, True)


@router.get("/llm/calls")
def read_llm_calls(
    _admin: AdminUser, session: DbSession, limit: int = Query(50, ge=1, le=200)
) -> LlmActivity:
    """Recent calls to the LLM with their prompts and replies, and how many were made."""
    now = utcnow()

    def count(since: timedelta, failed: bool = False) -> int:
        query = select(func.count()).where(LlmCall.created_at >= now - since)
        if failed:
            query = query.where(LlmCall.error.is_not(None))
        return session.scalar(query) or 0

    rows = session.execute(
        select(LlmCall, User.display_name)
        .outerjoin(User, User.id == LlmCall.user_id)
        .order_by(LlmCall.id.desc())
        .limit(limit)
    ).all()
    return LlmActivity(
        last_hour=count(timedelta(hours=1)),
        last_day=count(timedelta(days=1)),
        failed_last_day=count(timedelta(days=1), failed=True),
        calls=[
            LlmCallOut(
                id=call.id,
                created_at=call.created_at.replace(tzinfo=UTC),
                purpose=call.purpose,
                provider=call.provider,
                model=call.model,
                user=name,
                system=call.system,
                prompt=call.prompt,
                reply=call.reply,
                error=call.error,
                duration_ms=call.duration_ms,
            )
            for call, name in rows
        ],
    )
