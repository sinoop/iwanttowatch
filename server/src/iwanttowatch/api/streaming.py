from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from iwanttowatch.api.deps import AdultUser, CurrentUser, DbSession, Tmdb
from iwanttowatch.api.schemas import Me
from iwanttowatch.availability import (
    availability,
    is_stale,
    other_offers,
    provider_catalogue,
    regions,
    watchable,
)
from iwanttowatch.children import child_age, library_owners, limit_for_age
from iwanttowatch.models import Availability, LibraryItem, User
from iwanttowatch.tmdb import client_from_settings

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
