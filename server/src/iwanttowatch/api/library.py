from datetime import date

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from iwanttowatch.api.deps import CurrentUser, DbSession, Tmdb
from iwanttowatch.api.imports import Candidate
from iwanttowatch.catalog import search_movies
from iwanttowatch.models import Title, UserTitle

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
    latest = (
        select(
            UserTitle,
            func.row_number()
            .over(
                partition_by=UserTitle.tmdb_id,
                order_by=(UserTitle.rated_at.desc().nulls_last(), UserTitle.id.desc()),
            )
            .label("rank"),
        )
        .where(UserTitle.user_id == user.id, UserTitle.rating.is_not(None))
        .subquery()
    )
    effective = select(latest).where(latest.c.rank == 1).subquery()
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
            )
            for row in rows
        ],
        languages=[LanguageCount(language=lang, count=n) for lang, n in languages],
    )


@router.get("/catalog/search")
def search_catalog(
    _user: CurrentUser, tmdb: Tmdb, query: str = Query(min_length=1), year: int | None = None
) -> list[Candidate]:
    return [Candidate(**c) for c in search_movies(tmdb, query, year)]
