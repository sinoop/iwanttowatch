import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from iwanttowatch import __version__, imdb, radarr
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


class RadarrProfile(BaseModel):
    id: int
    name: str


class RadarrRootFolder(BaseModel):
    id: int
    path: str
    free_space: int | None = None


class RadarrSettings(BaseModel):
    configured: bool
    url: str | None = None
    quality_profile_id: int | None = None
    root_folder_path: str | None = None
    minimum_availability: str = radarr.DEFAULT_MIN_AVAILABILITY
    auto_sync_shortlist: bool = False
    profiles: list[RadarrProfile] = Field(default_factory=list)
    root_folders: list[RadarrRootFolder] = Field(default_factory=list)
    language_root_folders: dict[str, str] = Field(default_factory=dict)
    error: str | None = None


class ServerSettings(BaseModel):
    # The running release, from the package metadata (pyproject.toml).
    version: str
    tmdb_configured: bool
    # Whether an admin created a key for the read-only debugging MCP server at /mcp.
    mcp_enabled: bool
    llm: LlmSettings
    jellyfin: JellyfinSettings
    imdb: ImdbSettings
    radarr: RadarrSettings


class RadarrUpdate(BaseModel):
    url: str = Field(min_length=1, max_length=500)
    api_key: str | None = Field(default=None, max_length=200)
    quality_profile_id: int | None = None
    root_folder_path: str | None = None
    minimum_availability: str = radarr.DEFAULT_MIN_AVAILABILITY
    language_root_folders: dict[str, str] = Field(default_factory=dict)
    auto_sync_shortlist: bool = False


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
    total: int
    page: int
    total_pages: int
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


def _radarr_out(session: Session, is_admin: bool) -> RadarrSettings:
    url = get_setting(session, radarr.URL_SETTING)
    if not url:
        return RadarrSettings(configured=False, url=None)
    profile_id_str = get_setting(session, radarr.QUALITY_PROFILE_SETTING)
    profile_id = int(profile_id_str) if profile_id_str and profile_id_str.isdigit() else None
    root_folder = get_setting(session, radarr.ROOT_FOLDER_SETTING)
    min_avail = (
        get_setting(session, radarr.MIN_AVAILABILITY_SETTING) or radarr.DEFAULT_MIN_AVAILABILITY
    )

    profiles: list[RadarrProfile] = []
    root_folders: list[RadarrRootFolder] = []
    error: str | None = None

    if is_admin:
        client = radarr.client_from_settings(session)
        if client:
            try:
                raw_profiles = client.quality_profiles()
                profiles = [
                    RadarrProfile(id=p["id"], name=p["name"])
                    for p in raw_profiles
                    if "id" in p and "name" in p
                ]
                raw_folders = client.root_folders()
                root_folders = [
                    RadarrRootFolder(
                        id=f.get("id", idx), path=f["path"], free_space=f.get("freeSpace")
                    )
                    for idx, f in enumerate(raw_folders, 1)
                    if "path" in f
                ]
            except radarr.RadarrError as err:
                error = str(err)

    return RadarrSettings(
        configured=True,
        url=url,
        quality_profile_id=profile_id,
        root_folder_path=root_folder,
        minimum_availability=min_avail,
        auto_sync_shortlist=radarr.is_auto_sync_enabled(session),
        profiles=profiles,
        root_folders=root_folders,
        language_root_folders=radarr.get_language_root_folders(session),
        error=error,
    )


def _settings_out(session: Session, is_admin: bool) -> ServerSettings:
    # Secrets are never returned, only whether they are set.
    return ServerSettings(
        version=__version__,
        tmdb_configured=get_setting(session, API_KEY_SETTING) is not None,
        mcp_enabled=get_setting(session, mcp.KEY_SETTING) is not None,
        jellyfin=_jellyfin_out(session, is_admin),
        imdb=_imdb_out(session),
        radarr=_radarr_out(session, is_admin),
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


@router.put("/radarr")
def set_radarr(body: RadarrUpdate, _admin: AdminUser, session: DbSession) -> ServerSettings:
    """Connect a Radarr server; verifies credentials and discovers profiles and folders."""
    url = body.url.strip().rstrip("/")
    api_key = (body.api_key or "").strip() or get_setting(session, radarr.API_KEY_SETTING)
    if not api_key:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "An API key is required to connect to Radarr"
        )
    client = radarr.RadarrClient(url, api_key)
    try:
        client.system_status()
        profiles = client.quality_profiles()
        root_folders = client.root_folders()
    except radarr.RadarrAuthError as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Radarr rejected this API key") from error
    except radarr.RadarrError as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(error)) from error

    profile_id = body.quality_profile_id
    if profile_id is None and profiles:
        profile_id = profiles[0].get("id")

    root_folder = body.root_folder_path
    if root_folder is None and root_folders:
        root_folder = root_folders[0].get("path")

    radarr.save_settings(
        session,
        url=url,
        api_key=api_key,
        quality_profile_id=profile_id,
        root_folder_path=root_folder,
        minimum_availability=body.minimum_availability,
        language_root_folders=body.language_root_folders,
        auto_sync_shortlist=body.auto_sync_shortlist,
    )
    session.commit()
    return _settings_out(session, True)


@router.delete("/radarr")
def disconnect_radarr(_admin: AdminUser, session: DbSession) -> ServerSettings:
    """Disconnect and clear Radarr configuration."""
    radarr.clear_settings(session)
    session.commit()
    return _settings_out(session, True)


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
    _admin: AdminUser,
    session: DbSession,
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
) -> LlmActivity:
    """Recent calls to the LLM in the last 24 hours with their prompts and replies."""
    now = utcnow()
    since_day = now - timedelta(days=1)

    def count(since: timedelta, failed: bool = False) -> int:
        query = select(func.count()).where(LlmCall.created_at >= now - since)
        if failed:
            query = query.where(LlmCall.error.is_not(None))
        return session.scalar(query) or 0

    total = count(timedelta(days=1))
    total_pages = max(1, (total + limit - 1) // limit)
    page = min(page, total_pages) if total > 0 else 1
    offset = (page - 1) * limit

    rows = session.execute(
        select(LlmCall, User.display_name)
        .outerjoin(User, User.id == LlmCall.user_id)
        .where(LlmCall.created_at >= since_day)
        .order_by(LlmCall.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return LlmActivity(
        total=total,
        page=page,
        total_pages=total_pages,
        last_hour=count(timedelta(hours=1)),
        last_day=total,
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
