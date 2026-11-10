"""Acquisition Radar API: inspect missing from streaming and theatrical releases."""

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from iwanttowatch.api.deps import AdultUser, CurrentUser, DbSession, Tmdb
from iwanttowatch.api.schemas import ImdbScore
from iwanttowatch.radar import (
    inspect_missing_candidates,
    inspect_theatrical_candidates,
    queue_radar_candidates,
)
from iwanttowatch.radarr import RadarrError

router = APIRouter(prefix="/api/v1/library/radar", tags=["radar"])


class RadarItem(BaseModel):
    tmdb_id: int
    title: str
    original_title: str
    original_language: str
    year: int | None
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
