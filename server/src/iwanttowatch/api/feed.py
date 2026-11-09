from collections import Counter, defaultdict
from datetime import UTC, date, datetime
from typing import Annotated, Literal, cast

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from iwanttowatch.api.deps import CurrentUser, DbSession, Tmdb
from iwanttowatch.api.library import LanguageCount
from iwanttowatch.api.reactions import SOURCE as APP_SOURCE
from iwanttowatch.api.reactions import load_title
from iwanttowatch.api.schemas import ImdbScore, imdb_score
from iwanttowatch.api.streaming import (
    PlatformCount,
    TitleAvailability,
    platform_counts,
    shown_for,
    title_availability,
)
from iwanttowatch.availability import availability
from iwanttowatch.children import (
    allowed_for,
    ensure_themes_note_quietly,
    generate_themes_note,
    library_owners,
)
from iwanttowatch.db import utcnow
from iwanttowatch.feed import (
    ASK_FILMS,
    ASK_PICKS,
    SNOOZE,
    feed_films,
    feed_reasons,
    films_for_request,
    hidden,
    score_films,
    seen,
    shortlisted,
    stored_picks,
)
from iwanttowatch.jellyfin import URL_SETTING as JELLYFIN_URL_SETTING
from iwanttowatch.llm import LlmError, provider_from_settings
from iwanttowatch.models import (
    Availability,
    Explanation,
    Feedback,
    FeedBuild,
    LibraryItem,
    Recommendation,
    ShortlistItem,
    Title,
    User,
    UserTitle,
    get_setting,
)
from iwanttowatch.moods import moods_for
from iwanttowatch.taste import effective_ratings, explain_match

router = APIRouter(prefix="/api/v1")

FeedStatus = Literal["none", "queued", "building", "ready", "failed"]
FeedSort = Literal["match", "rating", "newest", "oldest", "shortest"]
# "seen" marks the film watched (without a rating); the others are Feedback kinds.
FeedbackKind = Literal["up", "down", "dismissed", "snoozed", "seen"]


class FeedItem(BaseModel):
    tmdb_id: int
    title: str
    original_title: str
    original_language: str
    year: int | None
    runtime: int | None
    # Film certificate in the user's region, e.g. "U/A 7+" or "PG".
    certificate: str | None = None
    poster_path: str | None
    genres: list[str]
    moods: list[str]
    # Predicted percentile of the user's own ratings, 0–100.
    match: int
    reasons: list[str]
    availability: TitleAvailability
    # The user asked for more like this.
    thumbs_up: bool
    shortlisted: bool
    # Child profile IDs that have this film on their shortlist.
    assigned_children: list[int] = Field(default_factory=list)
    imdb: ImdbScore | None


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
    # Where the feed's films can be played (before the platform filter).
    platforms: list[PlatformCount]
    # Shortlisted films the user hasn't watched yet.
    shortlist_count: int


def _sort_key(sort: FeedSort, rec: Recommendation, title: Title) -> tuple[float | int, ...]:
    if sort == "rating":
        public = (
            title.imdb_rating
            if title.imdb_rating is not None and title.imdb_votes
            else (title.vote_average or 0.0)
        )
        return (-public, rec.rank)
    if sort == "newest":
        day = title.release_date.toordinal() if title.release_date else 0
        return (-(title.year or 0), -day, rec.rank)
    if sort == "oldest":
        day = title.release_date.toordinal() if title.release_date else 0
        return (1 if title.year is None else 0, title.year or 0, day, rec.rank)
    if sort == "shortest":
        return (1 if not title.runtime else 0, title.runtime or 0, rec.rank)
    return (rec.rank,)


@router.get("/feed")
def read_feed(
    user: CurrentUser,
    session: DbSession,
    request: Request,
    available_only: bool = True,
    # "jellyfin" or TMDb provider IDs; when given, only films on one of them.
    platforms: Annotated[list[str], Query()] = [],  # noqa: B006 (FastAPI copies defaults)
    language: str | None = None,
    genre: str | None = None,
    # Only the user's shortlist, which may hold films the feed would hide.
    shortlist: bool = False,
    # Hide films the user has already shortlisted, to browse fresh picks.
    hide_shortlisted: bool = False,
    # On a child profile, keep only films within their birth-year certificate limit.
    age_limit: bool = True,
    sort: FeedSort = "match",
    # Only these films, such as the AI's picks for a request.
    only: Annotated[list[int], Query(max_length=ASK_PICKS)] = [],  # noqa: B006
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
    watched = seen(session, user.id)
    saved = set(shortlisted(session, user.id))
    # Saving a film overrides having turned it down before.
    exclude = watched | (hidden(session, user.id) - saved)
    thumbs_up = set(
        session.scalars(
            select(Feedback.tmdb_id).where(Feedback.user_id == user.id, Feedback.kind == "up")
        )
    )
    owners = library_owners(session, user)
    library = set(
        session.scalars(
            select(LibraryItem.tmdb_id).where(
                LibraryItem.user_id.in_(owners), LibraryItem.tmdb_id.in_(ids)
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
    assigned: dict[int, list[int]] = defaultdict(list)
    for tmdb_id, child_id in session.execute(
        select(ShortlistItem.tmdb_id, ShortlistItem.user_id)
        .join(User, User.id == ShortlistItem.user_id)
        .where(User.is_child.is_(True), ShortlistItem.tmdb_id.in_(ids))
        .order_by(ShortlistItem.user_id)
    ):
        assigned[tmdb_id].append(child_id)
    listed = []
    shortlist_count = 0
    for rec, title in rows:
        if title.tmdb_id in exclude or (
            age_limit
            and title.tmdb_id not in saved
            and not allowed_for(title, user.region, user.allowed_certificates)
        ):
            continue
        shortlist_count += title.tmdb_id in saved
        if (
            (shortlist and title.tmdb_id not in saved)
            or (hide_shortlisted and not shortlist and title.tmdb_id in saved)
            or (only and title.tmdb_id not in only)
        ):
            continue
        where = title_availability(
            title.tmdb_id, offers.get(title.tmdb_id), title.tmdb_id in library, user.subscriptions
        )
        listed.append((rec, title, where))
    shown = [row for row in listed if shown_for(row[2], available_only, platforms)]
    languages = Counter(title.original_language for _, title, _ in shown)
    genres = Counter(g for _, title, _ in shown for g in title.genres)
    matching = [
        (rec, title, where)
        for rec, title, where in shown
        if (language is None or title.original_language == language)
        and (genre is None or genre in title.genres)
    ]
    if sort != "match":
        matching.sort(key=lambda item: _sort_key(sort, item[0], item[1]))
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
                certificate=(title.certifications or {}).get(user.region),
                poster_path=title.poster_path,
                genres=title.genres,
                moods=moods_for(title),
                match=round(rec.score * 100),
                reasons=rec.reasons,
                availability=where,
                thumbs_up=title.tmdb_id in thumbs_up,
                shortlisted=title.tmdb_id in saved,
                assigned_children=assigned[title.tmdb_id],
                imdb=imdb_score(title),
            )
            for rec, title, where in matching[offset : offset + limit]
        ],
        languages=[LanguageCount(language=k, count=n) for k, n in languages.most_common(10)],
        genres=[g for g, _ in genres.most_common(12)],
        platforms=platform_counts([where for _, _, where in listed]),
        shortlist_count=shortlist_count,
    )


class AskBody(BaseModel):
    # What the user is in the mood for, in their own words.
    text: str = Field(min_length=1, max_length=200, pattern=r"\S")


class AskPick(BaseModel):
    tmdb_id: int
    # How the film fits the request, in the AI's words.
    why: str


class AskAnswer(BaseModel):
    # Up to 12 films that fit, best fit first; show them with GET /feed?only=….
    picks: list[AskPick]
    # How many films from the top of the filtered feed the AI chose from.
    considered: int


@router.post("/feed/ask")
def ask_feed(
    body: AskBody,
    user: CurrentUser,
    session: DbSession,
    request: Request,
    available_only: bool = True,
    platforms: Annotated[list[str], Query()] = [],  # noqa: B006
    language: str | None = None,
    genre: str | None = None,
    shortlist: bool = False,
    hide_shortlisted: bool = False,
    age_limit: bool = True,
) -> AskAnswer:
    """Ask the configured LLM which films near the top of the feed, with the same
    filters, fit a request such as "a light Malayalam comedy under 2 hours"."""
    llm = provider_from_settings(session, "ask", user.id)
    if llm is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Connect Ollama or Gemini in Settings first")
    page = read_feed(
        user,
        session,
        request,
        available_only,
        platforms,
        language,
        genre,
        shortlist,
        hide_shortlisted,
        age_limit,
        sort="match",
        only=[],
        offset=0,
        limit=ASK_FILMS,
    )
    if not page.items:
        return AskAnswer(picks=[], considered=0)
    found = session.scalars(select(Title).where(Title.tmdb_id.in_(i.tmdb_id for i in page.items)))
    titles = {t.tmdb_id: t for t in found}
    try:
        fits = films_for_request(llm, body.text.strip(), [titles[i.tmdb_id] for i in page.items])
    except LlmError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(error)) from error
    return AskAnswer(
        picks=[AskPick(tmdb_id=i, why=why) for i, why in fits.items()],
        considered=len(page.items),
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


@router.put("/titles/{tmdb_id}/shortlist", status_code=status.HTTP_204_NO_CONTENT)
def add_to_shortlist(
    tmdb_id: int, user: CurrentUser, session: DbSession, request: Request, tmdb: Tmdb
) -> Response:
    """Save a film to choose from later; it stays in the feed with its match."""
    load_title(session, request, tmdb_id)
    # Look up where it streams before writing: the lookup caches on its own connection.
    availability(session, tmdb, [tmdb_id], user.region)
    if session.get(ShortlistItem, (user.id, tmdb_id)) is None:
        session.add(ShortlistItem(user_id=user.id, tmdb_id=tmdb_id))
        session.commit()
        # Films from search or Watch together join the feed's candidates.
        if session.get(Recommendation, (user.id, tmdb_id)) is None:
            request.app.state.feed_worker.rescore_soon(user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/titles/{tmdb_id}/shortlist", status_code=status.HTTP_204_NO_CONTENT)
def remove_from_shortlist(tmdb_id: int, user: CurrentUser, session: DbSession) -> Response:
    entry = session.get(ShortlistItem, (user.id, tmdb_id))
    if entry is not None:
        session.delete(entry)
        session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class SeenStatus(BaseModel):
    # The user's rating out of 10, and their reaction when they rated it here; both are
    # None for a film watched without a rating.
    rating: float | None
    reaction: str | None


class TitleDetail(BaseModel):
    tmdb_id: int
    title: str
    original_title: str
    original_language: str
    year: int | None
    runtime: int | None
    # Film certificate in the user's region, e.g. "U/A 7+" or "PG".
    certificate: str | None = None
    poster_path: str | None
    overview: str
    tagline: str
    genres: list[str]
    moods: list[str]
    directors: list[str]
    cast: list[str]
    # How well the film suits the user, scored like the feed's films; None once seen.
    match: int | None
    reasons: list[str]
    # Set when the user has watched or rated the film.
    seen: SeenStatus | None = None
    availability: TitleAvailability
    # Opens the film in the Jellyfin web app, when it's in the user's libraries.
    jellyfin_url: str | None
    imdb: ImdbScore | None
    # Optional AI-written note on the film's themes and values for parents.
    themes_note: str | None = None
    shortlisted: bool = False
    # Child profile IDs that have this film on their shortlist.
    assigned_children: list[int] = Field(default_factory=list)
    # The AI's answer to "Why this?", once the user has asked.
    explanation: str | None = None


def _title_detail(session: DbSession, user: User, tmdb: Tmdb, title: Title) -> TitleDetail:
    owners = library_owners(session, user)
    offers = availability(session, tmdb, [title.tmdb_id], user.region).get(title.tmdb_id)
    rec = session.get(Recommendation, (user.id, title.tmdb_id))
    item_id = session.scalar(
        select(LibraryItem.item_id).where(
            LibraryItem.user_id.in_(owners), LibraryItem.tmdb_id == title.tmdb_id
        )
    )
    assigned = list(
        session.scalars(
            select(ShortlistItem.user_id)
            .join(User, User.id == ShortlistItem.user_id)
            .where(User.is_child.is_(True), ShortlistItem.tmdb_id == title.tmdb_id)
            .order_by(ShortlistItem.user_id)
        )
    )
    jellyfin = get_setting(session, JELLYFIN_URL_SETTING)
    effective = effective_ratings(user.id)
    rated = session.execute(
        select(effective.c.rating, effective.c.reaction).where(effective.c.tmdb_id == title.tmdb_id)
    ).first()
    watched = rated is not None or title.tmdb_id in seen(session, user.id)
    match, reasons = (round(rec.score * 100), rec.reasons) if rec else (None, [])
    if rec is None and not watched:
        # Not in the feed, such as a film the user searched for: score it with the
        # feed's films, so its match means the same, without adding it to the feed.
        scored = next(
            (
                s
                for s in score_films(session, user, [*feed_films(session, user), title.tmdb_id])
                if s.tmdb_id == title.tmdb_id
            ),
            None,
        )
        if scored is not None:
            match = round(scored.score * 100)
            reasons = feed_reasons(scored, stored_picks(session, user.id))
    return TitleDetail(
        tmdb_id=title.tmdb_id,
        title=title.title,
        original_title=title.original_title,
        original_language=title.original_language,
        year=title.year,
        runtime=title.runtime,
        certificate=(title.certifications or {}).get(user.region),
        poster_path=title.poster_path,
        overview=title.overview,
        tagline=title.tagline,
        genres=title.genres,
        moods=moods_for(title),
        directors=[p["name"] for p in title.directors],
        cast=[p["name"] for p in title.cast[:8]],
        match=match,
        reasons=reasons,
        seen=SeenStatus(rating=rated.rating, reaction=rated.reaction)
        if rated
        else SeenStatus(rating=None, reaction=None)
        if watched
        else None,
        availability=title_availability(
            title.tmdb_id, offers, item_id is not None, user.subscriptions
        ),
        jellyfin_url=f"{jellyfin}/web/#/details?id={item_id}" if jellyfin and item_id else None,
        imdb=imdb_score(title),
        themes_note=title.themes_note,
        shortlisted=session.get(ShortlistItem, (user.id, title.tmdb_id)) is not None,
        assigned_children=assigned,
        explanation=explained.text
        if (explained := session.get(Explanation, (user.id, title.tmdb_id)))
        else None,
    )


@router.get("/titles/{tmdb_id}")
def read_title(
    tmdb_id: int, user: CurrentUser, session: DbSession, request: Request, tmdb: Tmdb
) -> TitleDetail:
    title = load_title(session, request, tmdb_id)
    if user.is_child:
        ensure_themes_note_quietly(session, title, user.id)
    return _title_detail(session, user, tmdb, title)


@router.post("/titles/{tmdb_id}/themes")
def write_title_themes(
    tmdb_id: int, user: CurrentUser, session: DbSession, request: Request, tmdb: Tmdb
) -> TitleDetail:
    """Ask the configured LLM to write a 'themes and values' note for this film."""
    title = load_title(session, request, tmdb_id)
    llm = provider_from_settings(session, "themes", user.id)
    if llm is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Connect Ollama or Gemini in Settings first")
    try:
        generate_themes_note(session, title, llm)
    except LlmError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(error)) from error
    return _title_detail(session, user, tmdb, title)


@router.post("/titles/{tmdb_id}/why")
def explain_title(
    tmdb_id: int, user: CurrentUser, session: DbSession, request: Request, tmdb: Tmdb
) -> TitleDetail:
    """Ask the configured LLM how well this film fits the user's taste; asked once."""
    title = load_title(session, request, tmdb_id)
    llm = provider_from_settings(session, "why", user.id)
    if llm is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Connect Ollama or Gemini in Settings first")
    try:
        explain_match(session, user.id, title, llm)
    except LlmError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(error)) from error
    return _title_detail(session, user, tmdb, title)
