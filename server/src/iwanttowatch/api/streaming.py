from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from iwanttowatch.api.deps import CurrentUser, DbSession, Tmdb
from iwanttowatch.api.schemas import Me
from iwanttowatch.availability import (
    availability,
    is_stale,
    provider_catalogue,
    regions,
    watchable,
)
from iwanttowatch.models import Availability, LibraryItem

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
    # "flatrate" (in a subscription), "free", or "ads" (free with ads).
    kind: str


class TitleAvailability(BaseModel):
    tmdb_id: int
    on_jellyfin: bool
    # Where the user can play it now: their subscriptions, plus free services.
    offers: list[Offer]
    # TMDb's watch page for the user's region (JustWatch data).
    link: str | None
    checked_at: datetime | None
    # The last check is older than three days and rechecking failed.
    stale: bool


class StreamingUpdate(BaseModel):
    region: Region
    subscriptions: list[int] = Field(max_length=100)


@router.get("/streaming/regions")
def list_regions(_user: CurrentUser, tmdb: Tmdb) -> list[StreamingRegion]:
    return [StreamingRegion(**r) for r in regions(tmdb)]


@router.get("/streaming/providers")
def list_providers(user: CurrentUser, tmdb: Tmdb, region: Region | None = None) -> list[Provider]:
    """The movie streaming services in a region (the user's by default)."""
    return [Provider(**p) for p in provider_catalogue(tmdb, region or user.region)]


@router.put("/me/streaming")
def set_streaming(
    body: StreamingUpdate, user: CurrentUser, session: DbSession, request: Request
) -> Me:
    user.region = body.region
    user.subscriptions = list(dict.fromkeys(body.subscriptions))
    session.commit()
    # Candidates come partly from the user's services, so rebuild the feed.
    request.app.state.feed_worker.request(user.id)
    return Me.model_validate(user)


@router.get("/availability")
def read_availability(
    user: CurrentUser,
    session: DbSession,
    tmdb: Tmdb,
    ids: Annotated[list[int], Query(min_length=1, max_length=60)],
) -> list[TitleAvailability]:
    """Where the user can watch each title: their Jellyfin libraries or streaming services."""
    rows = availability(session, tmdb, ids, user.region)
    in_library = set(
        session.scalars(
            select(LibraryItem.tmdb_id).where(
                LibraryItem.user_id == user.id, LibraryItem.tmdb_id.in_(ids)
            )
        )
    )
    return [
        title_availability(tmdb_id, rows.get(tmdb_id), tmdb_id in in_library, user.subscriptions)
        for tmdb_id in dict.fromkeys(ids)
    ]


def title_availability(
    tmdb_id: int, row: Availability | None, on_jellyfin: bool, subscriptions: list[int]
) -> TitleAvailability:
    return TitleAvailability(
        tmdb_id=tmdb_id,
        on_jellyfin=on_jellyfin,
        offers=[Offer(**o) for o in watchable(row.offers, subscriptions)] if row else [],
        link=row.link if row else None,
        # SQLite returns stored UTC times without their time zone.
        checked_at=row.checked_at.replace(tzinfo=UTC) if row else None,
        stale=is_stale(row) if row else False,
    )
