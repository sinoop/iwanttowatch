"""Acquisition Radar API: missing from streaming, theatrical releases, and auto-downloader."""

from datetime import date

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from iwanttowatch.api.deps import AdultUser, CurrentUser, DbSession, Tmdb
from iwanttowatch.api.schemas import ImdbScore
from iwanttowatch.radar import (
    DEFAULT_AUTO_MIN_FREE_GB,
    DEFAULT_AUTO_MIN_MATCH,
    DEFAULT_AUTO_MIN_VOTES,
    DEFAULT_AUTO_RELEASED_ONLY,
    DEFAULT_AUTO_WEEKLY_LIMIT,
    get_auto_download_status,
    inspect_missing_candidates,
    inspect_theatrical_candidates,
    queue_radar_candidates,
    run_auto_downloader,
    save_auto_download_config,
)
from iwanttowatch.radarr import RadarrError

router = APIRouter(prefix="/api/v1/library/radar", tags=["radar"])


class RadarRootFolder(BaseModel):
    path: str
    free_space_bytes: int | None = None
    free_space_gb: float | None = None
    free_space_formatted: str | None = None
    below_threshold: bool = False


class RadarItem(BaseModel):
    tmdb_id: int
    title: str
    original_title: str
    original_language: str
    year: int | None
    release_date: date | None = None
    status: str | None = None
    runtime: int | None
    poster_path: str | None
    genres: list[str]
    match_pct: int
    reasons: list[str]
    imdb: ImdbScore | None
    radarr_status: str
    radarr_movie_id: int | None
    radarr_url: str | None
    is_theatrical: bool = False
    theatrical_release_date: str | None = None


class MissingCandidatesResponse(BaseModel):
    radarr_configured: bool
    scope: str
    min_match: int
    total_missing: int
    to_request_count: int
    downloading_count: int
    downloaded_count: int
    root_folders: list[RadarRootFolder] = Field(default_factory=list)
    min_free_space_bytes: int | None = None
    min_free_space_formatted: str | None = None
    items: list[RadarItem]


class TheatricalRadarResponse(BaseModel):
    radarr_configured: bool
    region: str
    total_theatrical: int
    to_track_count: int
    tracking_count: int
    downloaded_count: int
    items: list[RadarItem]


class RadarQueueRequest(BaseModel):
    tmdb_ids: list[int]
    minimum_availability: str | None = None


class RadarQueueItemResult(BaseModel):
    tmdb_id: int
    title: str
    status: str
    detail: str


class RadarQueueResponse(BaseModel):
    success: bool
    requested_count: int
    failed_count: int
    items: list[RadarQueueItemResult]


class AutoDownloadConfig(BaseModel):
    enabled: bool = False
    min_match: int = Field(DEFAULT_AUTO_MIN_MATCH, ge=50, le=100)
    min_free_space_gb: int = Field(DEFAULT_AUTO_MIN_FREE_GB, ge=0, le=100000)
    weekly_limit: int = Field(DEFAULT_AUTO_WEEKLY_LIMIT, ge=1, le=100)
    min_votes: int = Field(DEFAULT_AUTO_MIN_VOTES, ge=0, le=1000000)
    released_only: bool = DEFAULT_AUTO_RELEASED_ONLY


class AutoDownloadHistoryItem(BaseModel):
    tmdb_id: int
    title: str
    year: int | None = None
    match_pct: int
    root_folder: str | None = None
    queued_at: str


class AutoDownloadLastRun(BaseModel):
    ran_at: str
    queued_count: int
    skipped_low_space: int = 0
    skipped_weekly_cap: int = 0
    skipped_votes: int = 0
    skipped_unreleased: int = 0
    detail: str


class AutoDownloadStatusResponse(BaseModel):
    radarr_configured: bool
    config: AutoDownloadConfig
    downloads_this_week: int
    remaining_weekly_quota: int
    root_folders: list[RadarRootFolder] = Field(default_factory=list)
    has_sufficient_space: bool = True
    min_free_space_bytes: int | None = None
    min_free_space_formatted: str | None = None
    last_run: AutoDownloadLastRun | None = None
    history: list[AutoDownloadHistoryItem] = Field(default_factory=list)


class AutoDownloadRunResponse(BaseModel):
    queued_count: int
    queued_items: list[AutoDownloadHistoryItem] = Field(default_factory=list)
    skipped_low_space: int = 0
    skipped_weekly_cap: int = 0
    skipped_votes: int = 0
    skipped_unreleased: int = 0
    detail: str
    status: AutoDownloadStatusResponse


@router.get("/missing", response_model=MissingCandidatesResponse)
def get_missing_candidates(
    user: CurrentUser,
    session: DbSession,
    tmdb: Tmdb,
    min_match: int = Query(70, ge=1, le=100, description="Minimum predicted match percentage"),
    scope: str = Query("user", description="Scope: 'user' or 'group'"),
) -> MissingCandidatesResponse:
    """Inspect unwatched high-match recommendations not available on streaming or Jellyfin."""
    data = inspect_missing_candidates(
        session=session,
        tmdb=tmdb,
        user=user,
        min_match=min_match,
        scope=scope,
    )
    return MissingCandidatesResponse(**data)


@router.get("/theatrical", response_model=TheatricalRadarResponse)
def get_theatrical_candidates(
    user: CurrentUser,
    session: DbSession,
    tmdb: Tmdb,
    min_match: int = Query(50, ge=1, le=100, description="Minimum predicted match percentage"),
    region: str | None = Query(
        None, description="ISO 3166-1 country code (defaults to user region)"
    ),
) -> TheatricalRadarResponse:
    """Discover high-taste theatrical releases and check Radarr monitoring status."""
    data = inspect_theatrical_candidates(
        session=session,
        tmdb=tmdb,
        user=user,
        region=region,
        min_match=min_match,
    )
    return TheatricalRadarResponse(**data)


@router.post("/queue", response_model=RadarQueueResponse)
def queue_candidates(
    body: RadarQueueRequest,
    user: AdultUser,
    session: DbSession,
) -> RadarQueueResponse:
    """Queue or track radar candidate titles in Radarr."""
    try:
        data = queue_radar_candidates(
            session=session,
            user=user,
            tmdb_ids=body.tmdb_ids,
            minimum_availability=body.minimum_availability,
        )
        return RadarQueueResponse(**data)
    except RadarrError as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err)) from err


@router.get("/auto-download", response_model=AutoDownloadStatusResponse)
def get_auto_download_settings(
    _user: CurrentUser,
    session: DbSession,
) -> AutoDownloadStatusResponse:
    """Inspect background auto-downloader settings, remaining HDD space, and weekly quota."""
    data = get_auto_download_status(session)
    return AutoDownloadStatusResponse(**data)


@router.put("/auto-download", response_model=AutoDownloadStatusResponse)
def update_auto_download_settings(
    body: AutoDownloadConfig,
    _user: AdultUser,
    session: DbSession,
) -> AutoDownloadStatusResponse:
    """Update background auto-downloader settings (match %, min free space GB, weekly cap)."""
    save_auto_download_config(
        session,
        enabled=body.enabled,
        min_match=body.min_match,
        min_free_space_gb=body.min_free_space_gb,
        weekly_limit=body.weekly_limit,
        min_votes=body.min_votes,
        released_only=body.released_only,
    )
    session.commit()
    data = get_auto_download_status(session)
    return AutoDownloadStatusResponse(**data)


@router.post("/auto-download/run", response_model=AutoDownloadRunResponse)
def trigger_auto_downloader(
    user: AdultUser,
    session: DbSession,
    tmdb: Tmdb,
) -> AutoDownloadRunResponse:
    """Execute the background auto-downloader immediately on demand."""
    try:
        data = run_auto_downloader(
            session=session,
            tmdb=tmdb,
            user=user,
            force=True,
        )
        return AutoDownloadRunResponse(**data)
    except RadarrError as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err)) from err
