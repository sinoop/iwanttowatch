import logging
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from iwanttowatch.api.deps import AdultUser, CurrentUser, DbSession, Tmdb
from iwanttowatch.api.schemas import ImdbScore, Me
from iwanttowatch.availability import (
    availability,
    is_stale,
    other_offers,
    provider_catalogue,
    regions,
    watchable,
)
from iwanttowatch.catalog import ensure_titles
from iwanttowatch.children import child_age, library_owners, limit_for_age
from iwanttowatch.feed import DOCUMENTARY_GENRE_ID, is_non_movie, score_films, seen
from iwanttowatch.models import Availability, LibraryItem, User
from iwanttowatch.tmdb import TmdbError, client_from_settings

router = APIRouter(prefix="/api/v1")

Region = Annotated[str, Field(pattern=r"^[A-Z]{2}$")]


class StreamingRegion(BaseModel):
    code: str
    name: str


class Provider(BaseModel):
    provider_id: int
    name: str
    logo_path: str | None


class Offer(Provider):
    # "flatrate" (in a subscription), "free", or "ads" (free with ads); among
    # `other_offers`, a "flatrate" one is on a service the user doesn't pay for, and
    # "rent" and "buy" appear too.
    kind: str


class TitleAvailability(BaseModel):
    tmdb_id: int
    on_jellyfin: bool
    # Where the user can play it now: their subscriptions, plus free services.
    offers: list[Offer]
    # What the user can't play now: services they don't pay for, renting, and buying.
    # Only filled in a film's details, to keep lists light.
    other_offers: list[Offer] = Field(default_factory=list)
    # TMDb's watch page for the user's region (JustWatch data).
    link: str | None
    checked_at: datetime | None
    # The last check is older than three days and rechecking failed.
    stale: bool
    in_theaters: bool = False


class RecentlyAddedItem(BaseModel):
    tmdb_id: int
    title: str
    original_title: str
    original_language: str
    year: int | None
    runtime: int | None
    poster_path: str | None
    genres: list[str]
    match: int | None
    reasons: list[str] = Field(default_factory=list)
    availability: TitleAvailability
    digital_release_date: str | None = None
    imdb: ImdbScore | None = None


class RecentlyAddedResponse(BaseModel):
    items: list[RecentlyAddedItem]
    days: int
    total: int


class StreamingUpdate(BaseModel):
    region: Region
    subscriptions: list[int] = Field(max_length=100)
    show_rent_buy: bool = False


@router.get("/streaming/regions")
def list_regions(_user: CurrentUser, tmdb: Tmdb) -> list[StreamingRegion]:
    return [StreamingRegion(**r) for r in regions(tmdb)]


@router.get("/streaming/providers")
def list_providers(user: CurrentUser, tmdb: Tmdb, region: Region | None = None) -> list[Provider]:
    """The movie streaming services in a region (the user's by default)."""
    return [Provider(**p) for p in provider_catalogue(tmdb, region or user.region)]


@router.put("/me/streaming")
def set_streaming(
    body: StreamingUpdate, user: AdultUser, session: DbSession, request: Request
) -> Me:
    tmdb = client_from_settings(session, request.app.state.engine, request.app.state.tmdb_base_url)
    children = session.scalars(select(User).where(User.is_child.is_(True))).all()
    # Look up age limits in the new country before changing anything: TMDb lookups write
    # its cache on another connection, which would wait on this session's writes.
    limits: dict[int, tuple[str, list[str]]] = {}
    for child in children:
        age = child_age(child)
        limits[child.id] = (
            (limit_for_age(body.region, age, tmdb) or ("", [])) if age is not None else ("", [])
        )
    user.region = body.region
    user.subscriptions = list(dict.fromkeys(body.subscriptions))
    user.show_rent_buy = body.show_rent_buy
    for child in children:
        child.max_certificate, child.allowed_certificates = limits[child.id]
        child.region = body.region
        child.subscriptions = list(user.subscriptions)
        child.show_rent_buy = body.show_rent_buy
    session.commit()
    # Candidates come partly from the user's services, so rebuild the feed.
    request.app.state.feed_worker.request(user.id)
    for child in children:
        request.app.state.feed_worker.request(child.id)
    return Me.model_validate(user)


@router.get("/availability")
def read_availability(
    user: CurrentUser,
    session: DbSession,
    tmdb: Tmdb,
    ids: Annotated[list[int], Query(min_length=1, max_length=60)],
) -> list[TitleAvailability]:
    """Where the user can watch each title: their Jellyfin libraries or streaming services."""
    owners = library_owners(session, user)
    rows = availability(session, tmdb, ids, user.region)
    in_library = set(
        session.scalars(
            select(LibraryItem.tmdb_id).where(
                LibraryItem.user_id.in_(owners), LibraryItem.tmdb_id.in_(ids)
            )
        )
    )
    return [
        title_availability(tmdb_id, rows.get(tmdb_id), tmdb_id in in_library, user.subscriptions)
        for tmdb_id in dict.fromkeys(ids)
    ]


class PlatformCount(BaseModel):
    # "jellyfin", or a TMDb provider ID such as "8" for Netflix.
    key: str
    name: str
    logo_path: str | None
    # Films on it among the ones listed, before filtering by platform.
    count: int
    # Free or free with ads, rather than one of the user's subscriptions or Jellyfin.
    free: bool = False


# Filters on Jellyfin rather than a streaming service.
JELLYFIN = "jellyfin"


def platform_counts(places: list[TitleAvailability]) -> list[PlatformCount]:
    """Where the films can be played: Jellyfin first, then the user's services and then
    free ones, each with the most films first."""
    services: dict[int, PlatformCount] = {}
    for where in places:
        for offer in where.offers:
            entry = services.get(offer.provider_id)
            if entry is None:
                entry = PlatformCount(
                    key=str(offer.provider_id),
                    name=offer.name,
                    logo_path=offer.logo_path,
                    count=0,
                    free=offer.kind != "flatrate",
                )
                services[offer.provider_id] = entry
            entry.count += 1
            entry.free = entry.free and offer.kind != "flatrate"
    counts = sorted(services.values(), key=lambda p: (p.free, -p.count, p.name))
    if on_server := sum(where.on_jellyfin for where in places):
        counts.insert(
            0, PlatformCount(key=JELLYFIN, name="Jellyfin", logo_path=None, count=on_server)
        )
    return counts


def shown_for(
    where: TitleAvailability,
    available_only: bool,
    platforms: list[str],
    unavailable_only: bool = False,
) -> bool:
    """Whether a film passes the platform filter: on any chosen platform when some are
    chosen, otherwise on Jellyfin or a subscription unless everything is wanted or only
    unavailable films are wanted. Free services count only when chosen; they're mostly
    ad-funded or need a library card."""
    is_available = where.on_jellyfin or any(offer.kind == "flatrate" for offer in where.offers)
    if unavailable_only:
        return not is_available
    if platforms:
        return (JELLYFIN in platforms and where.on_jellyfin) or any(
            str(offer.provider_id) in platforms for offer in where.offers
        )
    return not available_only or is_available


RECENT_STREAMING_CACHE = timedelta(hours=6)
log = logging.getLogger(__name__)


@router.get("/streaming/recently-added", response_model=RecentlyAddedResponse)
def get_recently_added_streaming(
    user: CurrentUser,
    session: DbSession,
    tmdb: Tmdb,
    days: int = Query(7, ge=1, le=30, description="Window in days (default: 7)"),
    limit: int = Query(20, ge=1, le=50, description="Maximum number of films to return"),
) -> RecentlyAddedResponse:
    """Films recently added to streaming services in the user's region within the past N days."""
    today = date.today()
    start_date = (today - timedelta(days=days)).isoformat()
    end_date = today.isoformat()
    target_region = user.region or "US"

    providers = user.subscriptions
    params: dict[str, Any] = {
        "region": target_region,
        "watch_region": target_region,
        "with_release_type": "4|5|6",
        "release_date.gte": start_date,
        "release_date.lte": end_date,
        "with_watch_monetization_types": "flatrate|free|ads",
        "sort_by": "popularity.desc",
        "without_genres": str(DOCUMENTARY_GENRE_ID),
        "include_adult": "false",
        "page": 1,
    }
    if providers:
        params["with_watch_providers"] = "|".join(str(p) for p in providers)

    candidate_ids: list[int] = []
    try:
        data = tmdb.get("/discover/movie", params, cache_for=RECENT_STREAMING_CACHE)
        for item in data.get("results", []):
            if "id" in item:
                candidate_ids.append(int(item["id"]))
    except TmdbError as err:
        log.warning("Could not fetch TMDb recently added streaming discover: %s", err)

    if len(candidate_ids) < 5:
        alt_params: dict[str, Any] = {
            "region": target_region,
            "watch_region": target_region,
            "primary_release_date.gte": start_date,
            "primary_release_date.lte": end_date,
            "with_watch_monetization_types": "flatrate|free|ads",
            "sort_by": "popularity.desc",
            "without_genres": str(DOCUMENTARY_GENRE_ID),
            "include_adult": "false",
            "page": 1,
        }
        if providers:
            alt_params["with_watch_providers"] = "|".join(str(p) for p in providers)
        try:
            alt_data = tmdb.get("/discover/movie", alt_params, cache_for=RECENT_STREAMING_CACHE)
            for item in alt_data.get("results", []):
                if "id" in item:
                    candidate_ids.append(int(item["id"]))
        except TmdbError as err:
            log.warning("Could not fetch TMDb primary_release_date discover: %s", err)

    user_seen = seen(session, user.id)
    unique_ids = [tid for tid in dict.fromkeys(candidate_ids) if tid not in user_seen]
    if not unique_ids:
        return RecentlyAddedResponse(items=[], days=days, total=0)

    # Ensure titles in catalog
    titles = ensure_titles(session, tmdb, unique_ids[: limit * 2])
    valid_ids = [
        tid for tid in unique_ids[: limit * 2] if tid in titles and not is_non_movie(titles[tid])
    ]

    # Availability
    places = availability(session, tmdb, valid_ids, target_region)
    streamable_ids: list[int] = []
    where_by_id: dict[int, TitleAvailability] = {}
    for tid in valid_ids:
        place = places.get(tid)
        where = title_availability(tid, place, on_jellyfin=False, subscriptions=user.subscriptions)
        if where.offers or (not user.subscriptions and place and place.offers):
            streamable_ids.append(tid)
            where_by_id[tid] = where

    if not streamable_ids:
        return RecentlyAddedResponse(items=[], days=days, total=0)

    # Score candidates against user's taste
    scores_by_id: dict[int, float] = {}
    reasons_by_id: dict[int, list[str]] = {}
    try:
        scored = score_films(session, user, streamable_ids)
        for s in scored:
            scores_by_id[s.tmdb_id] = s.score
            reasons_by_id[s.tmdb_id] = s.reasons
    except Exception as err:
        log.warning("Could not score recent streaming films: %s", err)

    # Sort streamable_ids by taste score descending
    streamable_ids.sort(key=lambda tid: scores_by_id.get(tid, 0.0), reverse=True)

    items: list[RecentlyAddedItem] = []
    for tid in streamable_ids[:limit]:
        t = titles[tid]
        match_pct = round(scores_by_id[tid] * 100) if tid in scores_by_id else None
        imdb_obj = None
        if t.imdb_id and t.imdb_rating is not None and t.imdb_votes:
            imdb_obj = ImdbScore(id=t.imdb_id, rating=t.imdb_rating, votes=t.imdb_votes)
        items.append(
            RecentlyAddedItem(
                tmdb_id=tid,
                title=t.title,
                original_title=t.original_title,
                original_language=t.original_language,
                year=t.year,
                runtime=t.runtime,
                poster_path=t.poster_path,
                genres=t.genres,
                match=match_pct,
                reasons=reasons_by_id.get(tid, []),
                availability=where_by_id[tid],
                digital_release_date=t.release_date.isoformat() if t.release_date else None,
                imdb=imdb_obj,
            )
        )

    return RecentlyAddedResponse(items=items, days=days, total=len(items))


def title_availability(
    tmdb_id: int,
    row: Availability | None,
    on_jellyfin: bool,
    subscriptions: list[int],
    with_others: bool = False,
) -> TitleAvailability:
    return TitleAvailability(
        tmdb_id=tmdb_id,
        on_jellyfin=on_jellyfin,
        offers=[Offer(**o) for o in watchable(row.offers, subscriptions)] if row else [],
        other_offers=[Offer(**o) for o in other_offers(row.offers, subscriptions)]
        if row and with_others
        else [],
        link=row.link if row else None,
        # SQLite returns stored UTC times without their time zone.
        checked_at=row.checked_at.replace(tzinfo=UTC) if row else None,
        stale=is_stale(row) if row else False,
    )
