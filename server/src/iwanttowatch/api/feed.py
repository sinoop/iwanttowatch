from collections import Counter
from datetime import UTC, date, datetime
from typing import Literal, cast

from fastapi import APIRouter, Query, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import select

from iwanttowatch.api.deps import CurrentUser, DbSession, Tmdb
from iwanttowatch.api.library import LanguageCount
from iwanttowatch.api.reactions import SOURCE as APP_SOURCE
from iwanttowatch.api.reactions import load_title
from iwanttowatch.api.streaming import TitleAvailability, title_availability
from iwanttowatch.availability import availability
from iwanttowatch.db import utcnow
from iwanttowatch.feed import SNOOZE, hidden, seen
from iwanttowatch.jellyfin import URL_SETTING as JELLYFIN_URL_SETTING
from iwanttowatch.models import (
    Availability,
    Feedback,
    FeedBuild,
    LibraryItem,
    Recommendation,
    Title,
    UserTitle,
    get_setting,
)
from iwanttowatch.moods import moods_for

router = APIRouter(prefix="/api/v1")

FeedStatus = Literal["none", "queued", "building", "ready", "failed"]
# "seen" marks the film watched (without a rating); the others are Feedback kinds.
FeedbackKind = Literal["up", "down", "dismissed", "snoozed", "seen"]


class FeedItem(BaseModel):
    tmdb_id: int
    title: str
    original_title: str
    original_language: str
    year: int | None
    runtime: int | None
    poster_path: str | None
    genres: list[str]
    moods: list[str]
    # Predicted percentile of the user's own ratings, 0–100.
    match: int
    reasons: list[str]
    availability: TitleAvailability
    # The user asked for more like this.
    thumbs_up: bool


class FeedPage(BaseModel):
    status: FeedStatus
    # What a running build is doing.
    step: str | None
    error: str | None
    built_at: datetime | None
    # Recent ratings or feedback haven't reached the order yet; it changes shortly.
    rescoring: bool
    total: int
    items: list[FeedItem]
    # Languages and genres among the feed (before the language and genre filters).
    languages: list[LanguageCount]
    genres: list[str]


@router.get("/feed")
def read_feed(
    user: CurrentUser,
    session: DbSession,
    request: Request,
    available_only: bool = True,
    language: str | None = None,
    genre: str | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(24, ge=1, le=100),
) -> FeedPage:
    """The user's recommendations, best first. Films they have since watched or rated
    drop out at once; the first visit starts building the feed."""
    state = session.get(FeedBuild, user.id)
    if state is None:
        request.app.state.feed_worker.request(user.id)
        state = session.get(FeedBuild, user.id)
    rows = session.execute(
        select(Recommendation, Title)
        .join(Title, Title.tmdb_id == Recommendation.tmdb_id)
        .where(Recommendation.user_id == user.id)
        .order_by(Recommendation.rank)
    ).all()
    ids = [title.tmdb_id for _, title in rows]
    exclude = seen(session, user.id) | hidden(session, user.id)
    thumbs_up = set(
        session.scalars(
            select(Feedback.tmdb_id).where(Feedback.user_id == user.id, Feedback.kind == "up")
        )
    )
    library = set(
        session.scalars(
            select(LibraryItem.tmdb_id).where(
                LibraryItem.user_id == user.id, LibraryItem.tmdb_id.in_(ids)
            )
        )
    )
    offers = {
        row.tmdb_id: row
        for row in session.scalars(
            select(Availability).where(
                Availability.region == user.region, Availability.tmdb_id.in_(ids)
            )
        )
    }
    shown = []
    for rec, title in rows:
        if title.tmdb_id in exclude:
            continue
        where = title_availability(
            title.tmdb_id, offers.get(title.tmdb_id), title.tmdb_id in library, user.subscriptions
        )
        if available_only and not (where.on_jellyfin or where.offers):
            continue
        shown.append((rec, title, where))
    languages = Counter(title.original_language for _, title, _ in shown)
    genres = Counter(g for _, title, _ in shown for g in title.genres)
    matching = [
        (rec, title, where)
        for rec, title, where in shown
        if (language is None or title.original_language == language)
        and (genre is None or genre in title.genres)
    ]
    return FeedPage(
        status=cast(FeedStatus, state.status) if state and state.status else "none",
        step=state.step if state else None,
        error=state.error if state else None,
        built_at=state.built_at.replace(tzinfo=UTC) if state and state.built_at else None,
        rescoring=request.app.state.feed_worker.rescoring(user.id),
        total=len(matching),
        items=[
            FeedItem(
                tmdb_id=title.tmdb_id,
                title=title.title,
                original_title=title.original_title,
                original_language=title.original_language,
                year=title.year,
                runtime=title.runtime,
                poster_path=title.poster_path,
                genres=title.genres,
                moods=moods_for(title),
                match=round(rec.score * 100),
                reasons=rec.reasons,
                availability=where,
                thumbs_up=title.tmdb_id in thumbs_up,
            )
            for rec, title, where in matching[offset : offset + limit]
        ],
        languages=[LanguageCount(language=k, count=n) for k, n in languages.most_common(10)],
        genres=[g for g, _ in genres.most_common(12)],
    )


@router.post("/feed/refresh", status_code=status.HTTP_202_ACCEPTED)
def refresh_feed(user: CurrentUser, request: Request) -> Response:
    request.app.state.feed_worker.request(user.id)
    return Response(status_code=status.HTTP_202_ACCEPTED)


class FeedbackUpdate(BaseModel):
    kind: FeedbackKind


class FeedbackOut(BaseModel):
    tmdb_id: int
    kind: FeedbackKind
    # When a snoozed film comes back to the feed.
    until: datetime | None


@router.put("/titles/{tmdb_id}/feedback")
def give_feedback(
    tmdb_id: int, body: FeedbackUpdate, user: CurrentUser, session: DbSession, request: Request
) -> FeedbackOut:
    """Thumbs up or down, not interested, not now (for 30 days), or seen it. Only the
    latest applies; the feed is rescored shortly after."""
    load_title(session, request, tmdb_id)
    entry = session.get(Feedback, (user.id, tmdb_id))
    until = None
    if body.kind == "seen":
        if entry is not None:
            session.delete(entry)
        watched = session.scalar(
            select(UserTitle).where(
                UserTitle.user_id == user.id,
                UserTitle.tmdb_id == tmdb_id,
                UserTitle.source == APP_SOURCE,
            )
        )
        if watched is None:
            watched = UserTitle(user_id=user.id, tmdb_id=tmdb_id, source=APP_SOURCE)
            session.add(watched)
        watched.watched = True
        watched.watched_at = watched.watched_at or date.today()
    else:
        if entry is None:
            entry = Feedback(user_id=user.id, tmdb_id=tmdb_id)
            session.add(entry)
        until = utcnow() + SNOOZE if body.kind == "snoozed" else None
        entry.kind, entry.until, entry.created_at = body.kind, until, utcnow()
    session.commit()
    request.app.state.feed_worker.rescore_soon(user.id)
    return FeedbackOut(tmdb_id=tmdb_id, kind=body.kind, until=until)


@router.delete("/titles/{tmdb_id}/feedback", status_code=status.HTTP_204_NO_CONTENT)
def undo_feedback(
    tmdb_id: int, user: CurrentUser, session: DbSession, request: Request
) -> Response:
    """Take back feedback, including "seen it" as long as the film wasn't rated."""
    entry = session.get(Feedback, (user.id, tmdb_id))
    if entry is not None:
        session.delete(entry)
    watched = session.scalar(
        select(UserTitle).where(
            UserTitle.user_id == user.id,
            UserTitle.tmdb_id == tmdb_id,
            UserTitle.source == APP_SOURCE,
            UserTitle.reaction.is_(None),
        )
    )
    if watched is not None:
        session.delete(watched)
    session.commit()
    request.app.state.feed_worker.rescore_soon(user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class TitleDetail(BaseModel):
    tmdb_id: int
    title: str
    original_title: str
    original_language: str
    year: int | None
    runtime: int | None
    poster_path: str | None
    overview: str
    tagline: str
    genres: list[str]
    moods: list[str]
    directors: list[str]
    cast: list[str]
    # Set when the film is in the user's feed.
    match: int | None
    reasons: list[str]
    availability: TitleAvailability
    # Opens the film in the Jellyfin web app, when it's in the user's libraries.
    jellyfin_url: str | None


@router.get("/titles/{tmdb_id}")
def read_title(
    tmdb_id: int, user: CurrentUser, session: DbSession, request: Request, tmdb: Tmdb
) -> TitleDetail:
    title = load_title(session, request, tmdb_id)
    offers = availability(session, tmdb, [tmdb_id], user.region).get(tmdb_id)
    rec = session.get(Recommendation, (user.id, tmdb_id))
    item_id = session.scalar(
        select(LibraryItem.item_id).where(
            LibraryItem.user_id == user.id, LibraryItem.tmdb_id == tmdb_id
        )
    )
    jellyfin = get_setting(session, JELLYFIN_URL_SETTING)
    return TitleDetail(
        tmdb_id=title.tmdb_id,
        title=title.title,
        original_title=title.original_title,
        original_language=title.original_language,
        year=title.year,
        runtime=title.runtime,
        poster_path=title.poster_path,
        overview=title.overview,
        tagline=title.tagline,
        genres=title.genres,
        moods=moods_for(title),
        directors=[p["name"] for p in title.directors],
        cast=[p["name"] for p in title.cast[:8]],
        match=round(rec.score * 100) if rec else None,
        reasons=rec.reasons if rec else [],
        availability=title_availability(tmdb_id, offers, item_id is not None, user.subscriptions),
        jellyfin_url=f"{jellyfin}/web/#/details?id={item_id}" if jellyfin and item_id else None,
    )
