from datetime import date, datetime

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select

from iwanttowatch.api.deps import CurrentUser, DbSession, Tmdb
from iwanttowatch.api.imports import Candidate
from iwanttowatch.catalog import search_movies
from iwanttowatch.llm import LlmError, llm_order, provider_from_settings
from iwanttowatch.models import Persona, Title, UserTitle
from iwanttowatch.taste import (
    MIN_RATINGS_FOR_PERSONA,
    effective_ratings,
    generate_persona,
    is_refreshing,
    rating_count,
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


class LanguageCount(BaseModel):
    language: str
    count: int


class RatingsPage(BaseModel):
    total: int
    items: list[RatedTitle]
    languages: list[LanguageCount]


@router.get("/ratings")
def list_ratings(
    user: CurrentUser,
    session: DbSession,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> RatingsPage:
    """The user's ratings, newest first; when sources disagree the latest rating wins."""
    effective = effective_ratings(user.id)
    total = session.scalar(select(func.count()).select_from(effective)) or 0
    rows = session.execute(
        select(effective, Title)
        .join(Title, Title.tmdb_id == effective.c.tmdb_id)
        .order_by(effective.c.rated_at.desc().nulls_last(), effective.c.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    favorites = set(
        session.scalars(
            select(UserTitle.tmdb_id).where(UserTitle.user_id == user.id, UserTitle.favorite)
        )
    )
    languages = session.execute(
        select(Title.original_language, func.count())
        .join(effective, Title.tmdb_id == effective.c.tmdb_id)
        .group_by(Title.original_language)
        .order_by(func.count().desc())
        .limit(8)
    ).all()
    return RatingsPage(
        total=total,
        items=[
            RatedTitle(
                tmdb_id=row.Title.tmdb_id,
                title=row.Title.title,
                original_title=row.Title.original_title,
                original_language=row.Title.original_language,
                year=row.Title.year,
                poster_path=row.Title.poster_path,
                rating=row.rating,
                rated_at=row.rated_at,
                source=row.source,
                favorite=row.Title.tmdb_id in favorites,
                reaction=row.reaction,
                tags=row.tags or [],
            )
            for row in rows
        ],
        languages=[LanguageCount(language=lang, count=n) for lang, n in languages],
    )


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
