"""Rating a film in iWantToWatch: Didn't like / Liked / Loved, plus up to three tags and
an optional note."""

from datetime import date
from typing import Literal, cast

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from iwanttowatch.api.deps import CurrentUser, DbSession
from iwanttowatch.catalog import ensure_title
from iwanttowatch.models import Title, User, UserTitle
from iwanttowatch.tags import BY_ID, MAX_NOTE, MAX_TAGS, Group, options_for
from iwanttowatch.taste import refresh_reaction_ratings
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
    tags: list[str]
    note: str | None
    # What to offer for "What did you like most?" and "What didn't work?".
    liked_tags: list[TagOption]
    disliked_tags: list[TagOption]


class ReactionUpdate(BaseModel):
    reaction: Reaction
    tags: list[str] = Field(default_factory=list, max_length=MAX_TAGS)
    # Replaces the stored note; blank clears it.
    note: str = Field("", max_length=MAX_NOTE)


def load_title(session: DbSession, request: Request, tmdb_id: int) -> Title:
    """The title, fetched from TMDb if it isn't stored yet."""
    title = session.get(Title, tmdb_id)
    if title is not None:
        return title
    tmdb = client_from_settings(session, request.app.state.engine, request.app.state.tmdb_base_url)
    if tmdb is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Add a TMDb API key in Settings first")
    try:
        title = ensure_title(session, tmdb, tmdb_id)
    except TmdbError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Movie not found on TMDb") from error
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
    reaction = cast(Reaction | None, entry.reaction if entry else None)
    return TitleReaction(
        tmdb_id=title.tmdb_id,
        title=title.title,
        original_title=title.original_title,
        year=title.year,
        poster_path=title.poster_path,
        reaction=reaction,
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
    positive = body.reaction != "disliked"
    tags = list(dict.fromkeys(body.tags))
    for tag in tags:
        if tag not in BY_ID or BY_ID[tag].positive != positive:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, f"{tag!r} isn't a tag for {body.reaction!r}"
            )
    entry = _entry(session, user.id, tmdb_id)
    if entry is None:
        entry = UserTitle(user_id=user.id, tmdb_id=tmdb_id, source=SOURCE)
        session.add(entry)
    today = date.today()
    entry.reaction, entry.tags = body.reaction, tags
    entry.note = body.note.strip() or None
    entry.rated_at = today
    entry.watched = True
    entry.watched_at = entry.watched_at or today
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
        session.commit()
        worker = request.app.state.feed_worker
        worker.rescore_soon(user.id)
        if not user.is_child:
            for child_id in session.scalars(select(User.id).where(User.is_child.is_(True))):
                worker.rescore_soon(child_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
