"""Rating a film in iWantToWatch: Didn't like / Liked / Loved, plus up to three tags and
an optional note."""

import time
from datetime import date
from typing import Literal, cast

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from iwanttowatch import imdb
from iwanttowatch.api.deps import CurrentUser, DbSession
from iwanttowatch.catalog import ensure_title
from iwanttowatch.db import utcnow
from iwanttowatch.feed import clear_user_rated_matches_cache
from iwanttowatch.models import OutlierReview, RatingPrompt, Title, User, UserTitle
from iwanttowatch.tags import BY_ID, MAX_NOTE, MAX_TAGS, Group, options_for
from iwanttowatch.taste import REACTION_FALLBACK, rating_to_reaction, refresh_reaction_ratings
from iwanttowatch.tmdb import TmdbError, client_from_settings

router = APIRouter(prefix="/api/v1/titles")
SOURCE = "app"

Reaction = Literal["disliked", "liked", "loved"]


class TagOption(BaseModel):
    id: str
    label: str
    # "core" tags are offered for every film, "suggested" ones suit this film, and the
    # rest are "more".
    group: Group


class TitleReaction(BaseModel):
    tmdb_id: int
    title: str
    original_title: str
    year: int | None
    poster_path: str | None
    reaction: Reaction | None
    watched: bool = False
    tags: list[str]
    note: str | None
    # What to offer for "What did you like most?" and "What didn't work?".
    liked_tags: list[TagOption]
    disliked_tags: list[TagOption]


class ReactionUpdate(BaseModel):
    reaction: Reaction | None = None
    watched: bool = True
    tags: list[str] = Field(default_factory=list, max_length=MAX_TAGS)
    # Replaces the stored note; blank clears it.
    note: str = Field("", max_length=MAX_NOTE)


def load_title(
    session: DbSession,
    request: Request,
    tmdb_id: int,
    timings: dict[str, float] | None = None,
) -> Title:
    """The title, fetched from TMDb if it isn't stored yet."""
    title = session.get(Title, tmdb_id)
    if title is not None:
        if timings is not None:
            timings["tmdb_fetch_ms"] = 0.0
            t0 = time.perf_counter()
            imdb.ensure_title_rating(session, request.app.state.data_dir, title)
            timings["imdb_ms"] = (time.perf_counter() - t0) * 1000
        else:
            imdb.ensure_title_rating(session, request.app.state.data_dir, title)
        return title
    tmdb = client_from_settings(session, request.app.state.engine, request.app.state.tmdb_base_url)
    if tmdb is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Add a TMDb API key in Settings first")
    t_tmdb = time.perf_counter() if timings is not None else 0.0
    try:
        title = ensure_title(session, tmdb, tmdb_id)
    except TmdbError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Movie not found on TMDb") from error
    if timings is not None:
        timings["tmdb_fetch_ms"] = (time.perf_counter() - t_tmdb) * 1000
    t_imdb = time.perf_counter() if timings is not None else 0.0
    imdb.ensure_title_rating(session, request.app.state.data_dir, title)
    if timings is not None:
        timings["imdb_ms"] = (time.perf_counter() - t_imdb) * 1000
    session.commit()
    return title


def _entry(session: DbSession, user_id: int, tmdb_id: int) -> UserTitle | None:
    return session.scalar(
        select(UserTitle).where(
            UserTitle.user_id == user_id,
            UserTitle.tmdb_id == tmdb_id,
            UserTitle.source == SOURCE,
        )
    )


def _out(title: Title, entry: UserTitle | None) -> TitleReaction:
    selected = entry.tags if entry and entry.reaction else []

    def options(positive: bool) -> list[TagOption]:
        return [
            TagOption(id=t.id, label=t.label, group=group)
            for t, group in options_for(title, positive)
        ]

    # Only this router writes app reactions, always one of the Reaction values.
    reaction = cast(
        Reaction | None,
        entry.reaction
        if entry and entry.reaction
        else (rating_to_reaction(entry.rating) if entry and entry.rating is not None else None),
    )
    return TitleReaction(
        tmdb_id=title.tmdb_id,
        title=title.title,
        original_title=title.original_title,
        year=title.year,
        poster_path=title.poster_path,
        reaction=reaction,
        watched=bool(entry and entry.watched),
        tags=selected,
        note=entry.note if entry and entry.reaction else None,
        liked_tags=options(True),
        disliked_tags=options(False),
    )


@router.get("/{tmdb_id}/reaction")
def read_reaction(
    tmdb_id: int, user: CurrentUser, session: DbSession, request: Request
) -> TitleReaction:
    title = load_title(session, request, tmdb_id)
    return _out(title, _entry(session, user.id, tmdb_id))


@router.put("/{tmdb_id}/reaction")
def set_reaction(
    tmdb_id: int, body: ReactionUpdate, user: CurrentUser, session: DbSession, request: Request
) -> TitleReaction:
    title = load_title(session, request, tmdb_id)
    tags = list(dict.fromkeys(body.tags))
    for tag in tags:
        if tag not in BY_ID:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{tag!r} isn't a known tag")
    entry = _entry(session, user.id, tmdb_id)
    if entry is None:
        entry = UserTitle(user_id=user.id, tmdb_id=tmdb_id, source=SOURCE)
        session.add(entry)
    today = date.today()
    entry.reaction = body.reaction
    entry.tags = tags if body.reaction else []
    entry.note = (body.note.strip() or None) if body.reaction else None
    entry.rated_at = today if body.reaction else None
    entry.watched = body.watched
    entry.watched_at = entry.watched_at or today
    entry.rating = REACTION_FALLBACK[body.reaction] if body.reaction else None
    # Dismiss any pending Jellyfin rating prompt for this film.
    prompt = session.scalar(
        select(RatingPrompt).where(RatingPrompt.user_id == user.id, RatingPrompt.tmdb_id == tmdb_id)
    )
    if prompt is not None:
        prompt.dismissed = True
    # Scores this reaction, and re-scores earlier ones, against the user's current scale.
    refresh_reaction_ratings(session, user.id)
    session.commit()
    worker = request.app.state.feed_worker
    worker.rescore_soon(user.id)
    if not user.is_child:
        for child_id in session.scalars(select(User.id).where(User.is_child.is_(True))):
            worker.rescore_soon(child_id)
    return _out(title, entry)


@router.delete("/{tmdb_id}/reaction", status_code=status.HTTP_204_NO_CONTENT)
def clear_reaction(
    tmdb_id: int, user: CurrentUser, session: DbSession, request: Request
) -> Response:
    entry = _entry(session, user.id, tmdb_id)
    if entry is not None:
        session.delete(entry)
        session.execute(
            delete(OutlierReview).where(
                OutlierReview.user_id == user.id, OutlierReview.tmdb_id == tmdb_id
            )
        )
        session.commit()
        worker = request.app.state.feed_worker
        worker.rescore_soon(user.id)
        if not user.is_child:
            for child_id in session.scalars(select(User.id).where(User.is_child.is_(True))):
                worker.rescore_soon(child_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{tmdb_id}/clear-rating", status_code=status.HTTP_204_NO_CONTENT)
def clear_rating_keep_watched(
    tmdb_id: int, user: CurrentUser, session: DbSession, request: Request
) -> Response:
    """Clear any rating on the film across sources, but keep it marked as watched."""
    rows = session.scalars(
        select(UserTitle).where(UserTitle.user_id == user.id, UserTitle.tmdb_id == tmdb_id)
    ).all()
    if not rows:
        entry = UserTitle(user_id=user.id, tmdb_id=tmdb_id, source=SOURCE, watched=True)
        session.add(entry)
    else:
        for r in rows:
            r.rating = None
            r.reaction = None
            r.tags = []
            r.watched = True
            r.updated_at = utcnow()

    existing_outlier = session.get(OutlierReview, (user.id, tmdb_id))
    if existing_outlier is None:
        session.add(OutlierReview(user_id=user.id, tmdb_id=tmdb_id))

    refresh_reaction_ratings(session, user.id)
    session.commit()
    clear_user_rated_matches_cache(user.id)
    worker = request.app.state.feed_worker
    worker.rescore_soon(user.id)
    if not user.is_child:
        for child_id in session.scalars(select(User.id).where(User.is_child.is_(True))):
            worker.rescore_soon(child_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
