"""Declutter Assistant API: inspect and delete prune candidates."""

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from iwanttowatch.api.deps import AdminUser, CurrentUser, DbSession, Tmdb
from iwanttowatch.declutter import (
    delete_declutter_candidates,
    inspect_declutter_candidates,
    set_ignored_tmdb_id,
)
from iwanttowatch.radarr import RadarrError

router = APIRouter(prefix="/api/v1/library/declutter", tags=["declutter"])


class CategoryStat(BaseModel):
    count: int
    bytes: int
    formatted: str


class DeclutterCandidateItem(BaseModel):
    tmdb_id: int
    radarr_movie_id: int | None
    title: str
    year: int | None
    poster_path: str | None
    original_language: str | None
    imdb_rating: float | None
    category: str
    categories: list[str] = Field(default_factory=list)
    reasons: list[str]
    size_bytes: int
    size_formatted: str
    has_file: bool
    monitored: bool
    match_pct: int | None
    is_protected: bool
    protection_reasons: list[str]
    streaming_offers: list[str]
    is_ignored: bool


class DeclutterInspection(BaseModel):
    radarr_configured: bool
    jellyfin_configured: bool = False
    total_candidates: int
    reclaimable_bytes: int
    reclaimable_formatted: str
    protected_count: int
    categories_summary: dict[str, CategoryStat]
    items: list[DeclutterCandidateItem]


class DeclutterDeleteRequest(BaseModel):
    tmdb_ids: list[int]
    delete_files: bool = True
    add_import_exclusion: bool = False


class DeclutterDeleteResponse(BaseModel):
    success: bool
    deleted_count: int
    freed_bytes: int
    freed_formatted: str
    failed_count: int
    errors: list[str]


class DeclutterIgnoreRequest(BaseModel):
    tmdb_id: int
    ignored: bool = True


class DeclutterIgnoreResponse(BaseModel):
    tmdb_id: int
    ignored: bool


@router.get("", response_model=DeclutterInspection)
def get_declutter_candidates(
    user: CurrentUser,
    session: DbSession,
    tmdb: Tmdb,
    category: str | None = Query(
        None, description="Filter to a specific category or comma-separated list of categories"
    ),
    categories_mode: str = Query(
        "any", description="Combine mode for multiple categories: 'all' (AND) or 'any' (OR)"
    ),
    include_ignored: bool = Query(False, description="Include previously ignored titles"),
    whitelist: str | None = Query(None, description="Whitelist filter: 'hide', 'only', or 'all'"),
) -> DeclutterInspection:
    """Inspect the library and Radarr to identify safe prune candidates."""
    data = inspect_declutter_candidates(
        session=session,
        tmdb=tmdb,
        user=user,
        category_filter=category,
        categories_mode=categories_mode,
        include_ignored=include_ignored,
        whitelist_filter=whitelist,
    )
    return DeclutterInspection(**data)


@router.post("/delete", response_model=DeclutterDeleteResponse)
def delete_candidates(
    body: DeclutterDeleteRequest,
    _admin: AdminUser,
    session: DbSession,
) -> DeclutterDeleteResponse:
    """Delete candidate movies from Radarr and reclaim storage."""
    try:
        res = delete_declutter_candidates(
            session=session,
            tmdb_ids=body.tmdb_ids,
            delete_files=body.delete_files,
            add_import_exclusion=body.add_import_exclusion,
        )
        return DeclutterDeleteResponse(**res)
    except RadarrError as err:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(err)) from err


@router.post("/ignore", response_model=DeclutterIgnoreResponse)
def ignore_candidate(
    body: DeclutterIgnoreRequest,
    _admin: AdminUser,
    session: DbSession,
) -> DeclutterIgnoreResponse:
    """Whitelist/ignore a movie so it is not suggested for pruning."""
    set_ignored_tmdb_id(session, body.tmdb_id, ignored=body.ignored)
    return DeclutterIgnoreResponse(tmdb_id=body.tmdb_id, ignored=body.ignored)
