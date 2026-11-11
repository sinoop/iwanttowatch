from collections import Counter
from datetime import date, datetime

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy import String, case, cast, func, or_, select

from iwanttowatch.api.deps import CurrentUser, DbSession, Tmdb
from iwanttowatch.api.imports import Candidate
from iwanttowatch.api.reactions import TagOption
from iwanttowatch.catalog import search_movies
from iwanttowatch.children import library_owners
from iwanttowatch.feed import user_rated_matches
from iwanttowatch.llm import LlmError, llm_order, provider_from_settings
from iwanttowatch.models import (
    Availability,
    LibraryItem,
    OutlierReview,
    Persona,
    Title,
    UserTitle,
)
from iwanttowatch.tags import options_for
from iwanttowatch.taste import (
    MIN_RATINGS_FOR_PERSONA,
    REACTION_FALLBACK,
    effective_ratings,
    find_divergent_ratings,
    generate_persona,
    is_refreshing,
    rating_count,
    rating_to_reaction,
)

router = APIRouter(prefix="/api/v1")


class RatedTitle(BaseModel):
    tmdb_id: int
    title: str
    original_title: str
    original_language: str
    year: int | None
    poster_path: str | None
    rating: float
    rated_at: date | None
    source: str
    favorite: bool
    # Set when the effective rating was given in iWantToWatch.
    reaction: str | None
    tags: list[str]
    note: str | None = None
    match: int | None = None


class LanguageCount(BaseModel):
    language: str
    count: int


class RatingsPage(BaseModel):
    total: int
    total_unfiltered: int = 0
    items: list[RatedTitle]
    languages: list[LanguageCount]
    genres: list[str] = []
    decades: list[int] = []
    tags: list[str] = []
    reactions: dict[str, int] = {}
    top_people: list[str] = []
    has_notes_count: int = 0


@router.get("/ratings")
def list_ratings(
    user: CurrentUser,
    session: DbSession,
    limit: int = Query(48, ge=1, le=200),
    offset: int = Query(0, ge=0),
    query: str | None = None,
    reaction: str | None = None,
    language: str | None = None,
    genre: str | None = None,
    person: str | None = None,
    tag: str | None = None,
    decade: int | None = None,
    watch_on: str | None = None,
    has_note: bool | None = None,
    favorite: bool | None = None,
    sort: str = "newest",
) -> RatingsPage:
    """The user's ratings with rich filtering and sorting."""
    effective = effective_ratings(user.id)

    # 1. Gather all unfiltered rated titles to extract user-specific filter facets
    all_rated = session.execute(
        select(
            Title.original_language,
            Title.genres,
            Title.year,
            Title.directors,
            Title.cast,
            effective.c.reaction,
            effective.c.tags,
            effective.c.note,
        ).join(Title, Title.tmdb_id == effective.c.tmdb_id)
    ).all()

    total_unfiltered = len(all_rated)
    lang_counter: Counter[str] = Counter()
    genre_set: set[str] = set()
    decade_set: set[int] = set()
    tag_set: set[str] = set()
    reaction_counter: Counter[str] = Counter()
    people_counter: Counter[str] = Counter()
    has_notes_count = 0

    for row in all_rated:
        if row.original_language:
            lang_counter[row.original_language] += 1
        if row.genres:
            genre_set.update(row.genres)
        if row.year:
            decade_set.add((row.year // 10) * 10)
        if row.reaction:
            reaction_counter[row.reaction] += 1
        if row.tags:
            tag_set.update(row.tags)
        if row.note and row.note.strip():
            has_notes_count += 1
        if row.directors:
            for p in row.directors:
                if isinstance(p, dict) and p.get("name"):
                    people_counter[p["name"]] += 1
        if row.cast:
            for p in row.cast[:4]:
                if isinstance(p, dict) and p.get("name"):
                    people_counter[p["name"]] += 1

    languages = [
        LanguageCount(language=lang, count=count) for lang, count in lang_counter.most_common()
    ]
    genres = sorted(genre_set)
    decades = sorted(decade_set, reverse=True)
    tags = sorted(tag_set)
    top_people = [name for name, count in people_counter.most_common(30) if count >= 2]

    # 2. Build filtered query
    stmt = select(effective, Title).join(Title, Title.tmdb_id == effective.c.tmdb_id)

    if query and query.strip():
        pattern = f"%{query.strip().lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Title.title).like(pattern),
                func.lower(Title.original_title).like(pattern),
            )
        )
    if reaction:
        stmt = stmt.where(effective.c.reaction == reaction)
    if language:
        stmt = stmt.where(Title.original_language == language)
    if genre:
        stmt = stmt.where(cast(Title.genres, String).like(f'%"{genre}"%'))
    if person and person.strip():
        person_pattern = f"%{person.strip().lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(cast(Title.directors, String)).like(person_pattern),
                func.lower(cast(Title.cast, String)).like(person_pattern),
            )
        )
    if tag:
        stmt = stmt.where(cast(effective.c.tags, String).like(f'%"{tag}"%'))
    if decade is not None:
        stmt = stmt.where(Title.year >= decade, Title.year < decade + 10)
    if has_note:
        stmt = stmt.where(effective.c.note.is_not(None), effective.c.note != "")
    if favorite:
        stmt = stmt.where(effective.c.favorite.is_(True))

    if watch_on == "jellyfin":
        owners = library_owners(session, user)
        jellyfin_ids = select(LibraryItem.tmdb_id).where(LibraryItem.user_id.in_(owners))
        stmt = stmt.where(Title.tmdb_id.in_(jellyfin_ids))
    elif watch_on == "streamable":
        owners = library_owners(session, user)
        jellyfin_ids = select(LibraryItem.tmdb_id).where(LibraryItem.user_id.in_(owners))
        conditions = [
            cast(Availability.offers, String).like('%"kind": "free"%'),
            cast(Availability.offers, String).like('%"kind": "ads"%'),
        ]
        for pid in user.subscriptions or []:
            conditions.append(cast(Availability.offers, String).like(f'%"provider_id": {pid}%'))
        streamable_subq = select(Availability.tmdb_id).where(
            Availability.region == user.region, or_(*conditions)
        )
        stmt = stmt.where(or_(Title.tmdb_id.in_(jellyfin_ids), Title.tmdb_id.in_(streamable_subq)))

    # 3. Sort order
    if sort == "reaction":
        stmt = stmt.order_by(
            case(
                (effective.c.reaction == "loved", 3),
                (effective.c.reaction == "liked", 2),
                (effective.c.reaction == "disliked", 1),
                else_=0,
            ).desc(),
            effective.c.rated_at.desc().nulls_last(),
            effective.c.id.desc(),
        )
    elif sort == "year_desc":
        stmt = stmt.order_by(Title.year.desc().nulls_last(), Title.title.asc())
    elif sort == "year_asc":
        stmt = stmt.order_by(Title.year.asc().nulls_last(), Title.title.asc())
    elif sort == "title_asc":
        stmt = stmt.order_by(Title.title.asc())
    else:  # "newest" or default
        stmt = stmt.order_by(effective.c.rated_at.desc().nulls_last(), effective.c.id.desc())

    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = session.execute(stmt.limit(limit).offset(offset)).all()
    favorites = set(
        session.scalars(
            select(UserTitle.tmdb_id).where(UserTitle.user_id == user.id, UserTitle.favorite)
        )
    )
    matches = user_rated_matches(session, user)

    return RatingsPage(
        total=total,
        total_unfiltered=total_unfiltered,
        items=[
            RatedTitle(
                tmdb_id=row.Title.tmdb_id,
                title=row.Title.title,
                original_title=row.Title.original_title,
                original_language=row.Title.original_language,
                year=row.Title.year,
                poster_path=row.Title.poster_path,
                rating=row.rating if row.rating is not None else 0.0,
                rated_at=row.rated_at,
                source=row.source,
                favorite=row.Title.tmdb_id in favorites,
                reaction=row.reaction,
                tags=row.tags or [],
                note=row.note,
                match=matches.get(row.Title.tmdb_id),
            )
            for row in rows
        ],
        languages=languages,
        genres=genres,
        decades=decades,
        tags=tags,
        reactions=dict(reaction_counter),
        top_people=top_people,
        has_notes_count=has_notes_count,
    )


class DivergentTitle(BaseModel):
    tmdb_id: int
    title: str
    original_title: str
    original_language: str
    year: int | None
    poster_path: str | None
    user_rating: float
    consensus_rating: float
    vote_count: int
    divergence: float
    reaction: str | None
    tags: list[str]
    note: str | None
    clash: str | None = None


@router.get("/me/divergent-ratings")
def list_divergent_ratings(
    user: CurrentUser,
    session: DbSession,
    limit: int = Query(50, ge=1, le=100),
    threshold: float = Query(1.5, ge=0.5, le=5.0),
) -> list[DivergentTitle]:
    """Films the user rated where their rating strongly differed from the general audience."""
    items = find_divergent_ratings(session, user.id, threshold=threshold, limit=limit)
    return [
        DivergentTitle(
            tmdb_id=item.tmdb_id,
            title=item.title,
            original_title=item.original_title,
            original_language=item.original_language,
            year=item.year,
            poster_path=item.poster_path,
            user_rating=item.user_rating,
            consensus_rating=item.consensus_rating,
            vote_count=item.vote_count,
            divergence=item.divergence,
            reaction=item.reaction,
            tags=item.tags,
            note=item.note,
            clash=item.clash,
        )
        for item in items
    ]


class OutlierTitle(BaseModel):
    tmdb_id: int
    title: str
    original_title: str
    original_language: str
    year: int | None
    poster_path: str | None
    genres: list[str]
    user_rating: float
    reaction: str
    tags: list[str]
    note: str | None
    predicted_match: int
    divergence: int
    outlier_type: str
    liked_tags: list[TagOption]
    disliked_tags: list[TagOption]


@router.get("/ratings/outliers")
def list_outliers(
    user: CurrentUser,
    session: DbSession,
    limit: int = Query(15, ge=1, le=15),
) -> list[OutlierTitle]:
    """Films where the user's rating strongly diverged from the recommender's predicted match."""
    effective = effective_ratings(user.id)
    rows = session.execute(
        select(effective, Title).join(Title, Title.tmdb_id == effective.c.tmdb_id)
    ).all()
    if not rows:
        return []

    matches = user_rated_matches(session, user)
    if not matches:
        return []

    reviewed = set(
        session.scalars(select(OutlierReview.tmdb_id).where(OutlierReview.user_id == user.id))
    )

    candidates: list[tuple[float, OutlierTitle]] = []
    for r in rows:
        t: Title = r.Title
        if t.tmdb_id in reviewed:
            continue
        pred = matches.get(t.tmdb_id)
        if pred is None:
            continue

        user_rating = (
            float(r.rating)
            if r.rating is not None
            else (REACTION_FALLBACK.get(r.reaction, 7.5) if r.reaction else 7.5)
        )
        rx = r.reaction or rating_to_reaction(user_rating)
        tags = list(r.tags or [])

        # Target percentile for reaction: Loved=95, Liked=70, Disliked=15
        expected_pct = 95 if rx == "loved" else 70 if rx == "liked" else 15
        diff = expected_pct - pred

        outlier_type: str | None = None
        if rx == "loved" and (pred <= 75 or not tags):
            outlier_type = "loved_rewatch"
        elif rx == "liked" and pred <= 45:
            outlier_type = "predicted_dislike_user_liked"
        elif rx == "disliked" and pred >= 65:
            outlier_type = "predicted_like_user_disliked"
        elif abs(diff) >= 30:
            outlier_type = (
                "predicted_dislike_user_liked" if diff > 0 else "predicted_like_user_disliked"
            )

        if outlier_type is None:
            continue

        priority = abs(diff) + (20 if not tags else 0) + (10 if rx == "loved" else 0)

        liked_opts = [
            TagOption(id=tag.id, label=tag.label, group=grp) for tag, grp in options_for(t, True)
        ]
        disliked_opts = [
            TagOption(id=tag.id, label=tag.label, group=grp) for tag, grp in options_for(t, False)
        ]

        item = OutlierTitle(
            tmdb_id=t.tmdb_id,
            title=t.title,
            original_title=t.original_title,
            original_language=t.original_language,
            year=t.year,
            poster_path=t.poster_path,
            genres=t.genres or [],
            user_rating=user_rating,
            reaction=rx,
            tags=tags,
            note=r.note,
            predicted_match=pred,
            divergence=diff,
            outlier_type=outlier_type,
            liked_tags=liked_opts,
            disliked_tags=disliked_opts,
        )
        candidates.append((priority, item))

    candidates.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in candidates[:limit]]


@router.post("/ratings/outliers/{tmdb_id}/confirm", status_code=status.HTTP_204_NO_CONTENT)
def confirm_outlier(tmdb_id: int, user: CurrentUser, session: DbSession) -> Response:
    """Mark an outlier film as reviewed and confirmed so it leaves the outlier queue."""
    existing = session.get(OutlierReview, (user.id, tmdb_id))
    if existing is None:
        session.add(OutlierReview(user_id=user.id, tmdb_id=tmdb_id))
        session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/catalog/search")
def search_catalog(
    _user: CurrentUser,
    tmdb: Tmdb,
    query: str = Query(min_length=1),
    year: int | None = None,
) -> list[Candidate]:
    return [Candidate(**c) for c in search_movies(tmdb, query, year)]


class PersonaOut(BaseModel):
    text: str | None
    generated_at: datetime | None
    # Ratings the persona was written from, and how many there are now.
    based_on_ratings: int
    current_ratings: int
    min_ratings: int
    llm_configured: bool
    # A background rewrite is in progress; poll until it clears.
    refreshing: bool


def _persona_out(session: DbSession, user_id: int) -> PersonaOut:
    persona = session.get(Persona, user_id)
    return PersonaOut(
        text=persona.text if persona else None,
        generated_at=persona.generated_at if persona else None,
        based_on_ratings=persona.rating_count if persona else 0,
        current_ratings=rating_count(session, user_id),
        min_ratings=MIN_RATINGS_FOR_PERSONA,
        llm_configured=bool(llm_order(session)),
        refreshing=is_refreshing(user_id),
    )


@router.get("/me/persona")
def read_persona(user: CurrentUser, session: DbSession) -> PersonaOut:
    return _persona_out(session, user.id)


@router.post("/me/persona")
def regenerate_persona(user: CurrentUser, session: DbSession) -> PersonaOut:
    """Ask the configured LLM to write a fresh persona from the user's ratings."""
    llm = provider_from_settings(session, "persona", user.id)
    if llm is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Connect Ollama or Gemini in Settings first")
    try:
        persona = generate_persona(session, user.id, llm)
    except LlmError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(error)) from error
    if persona is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Rate at least {MIN_RATINGS_FOR_PERSONA} movies first"
        )
    return _persona_out(session, user.id)
