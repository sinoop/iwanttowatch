import hashlib
import hmac
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import select

from iwanttowatch.api.deps import DbSession
from iwanttowatch.api.mcp import KEY_SETTING as MCP_KEY_SETTING
from iwanttowatch.models import (
    Availability,
    LibraryItem,
    Recommendation,
    ShortlistItem,
    Title,
    User,
    get_setting,
)

router = APIRouter(prefix="/api/v1")

TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500"


class HomeAssistantMovie(BaseModel):
    tmdb_id: int
    title: str
    year: int | None = None
    match: int | None = None
    imdb_rating: float | None = None
    poster_url: str | None = None
    in_jellyfin: bool = False
    streaming_services: list[str] = []


class HomeAssistantPayload(BaseModel):
    user: str
    generated_at: datetime
    high_rated_recommendations: list[HomeAssistantMovie]
    shortlisted: list[HomeAssistantMovie]


def _resolve_user(request: Request, session: DbSession, username: str | None) -> User:
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
        expected_hash = get_setting(session, MCP_KEY_SETTING)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        if not expected_hash or not hmac.compare_digest(token_hash, expected_hash):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key")
        if username:
            user = session.scalar(select(User).where(User.username == username))
            if user is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown user: {username}")
            return user
        user = session.scalar(select(User).where(User.is_admin.is_(True)).order_by(User.id))
        if user is None:
            user = session.scalar(select(User).order_by(User.id))
        if user is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No users configured")
        return user

    user_id = request.session.get("user_id")
    if isinstance(user_id, int):
        user = session.get(User, user_id)
        if user is not None:
            return user
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in or provide a Bearer API key")


def _build_movie(
    title: Title,
    score: float | None,
    jellyfin_ids: set[int],
    services_by_tmdb: dict[int, list[str]],
) -> HomeAssistantMovie:
    return HomeAssistantMovie(
        tmdb_id=title.tmdb_id,
        title=title.title,
        year=title.year,
        match=round(score * 100) if score is not None else None,
        imdb_rating=title.imdb_rating,
        poster_url=f"{TMDB_IMAGE_BASE}{title.poster_path}" if title.poster_path else None,
        in_jellyfin=title.tmdb_id in jellyfin_ids,
        streaming_services=services_by_tmdb.get(title.tmdb_id, []),
    )


@router.get("/integrations/home-assistant")
def home_assistant_feed(
    request: Request,
    session: DbSession,
    username: str | None = Query(None),
    limit: int = Query(10, ge=1, le=50),
    min_match: int = Query(75, ge=0, le=100),
) -> HomeAssistantPayload:
    """High-match recommendations and shortlisted movies for Home Assistant sensors."""
    user = _resolve_user(request, session, username)
    min_score = min_match / 100.0

    rec_rows = session.execute(
        select(Title, Recommendation.score)
        .join(Recommendation, Recommendation.tmdb_id == Title.tmdb_id)
        .where(
            Recommendation.user_id == user.id,
            Recommendation.score >= min_score,
        )
        .order_by(Recommendation.score.desc())
        .limit(limit)
    ).all()

    shortlist_rows = session.execute(
        select(Title, Recommendation.score)
        .join(ShortlistItem, ShortlistItem.tmdb_id == Title.tmdb_id)
        .outerjoin(
            Recommendation,
            (Recommendation.tmdb_id == Title.tmdb_id) & (Recommendation.user_id == user.id),
        )
        .where(ShortlistItem.user_id == user.id)
        .order_by(ShortlistItem.added_at.desc())
        .limit(limit)
    ).all()

    all_ids = list(
        {title.tmdb_id for title, _ in rec_rows} | {title.tmdb_id for title, _ in shortlist_rows}
    )

    jellyfin_ids: set[int] = set()
    services_by_tmdb: dict[int, list[str]] = {}
    if all_ids:
        jellyfin_ids = {
            tid
            for tid in session.scalars(
                select(LibraryItem.tmdb_id).where(
                    LibraryItem.user_id == user.id,
                    LibraryItem.tmdb_id.in_(all_ids),
                )
            )
            if tid is not None
        }
        region = user.region or get_setting(session, "default_region") or "US"
        for avail in session.scalars(
            select(Availability).where(
                Availability.tmdb_id.in_(all_ids),
                Availability.region == region,
            )
        ):
            offers = avail.offers or []
            flatrate = [
                str(o["provider_name"])
                for o in offers
                if isinstance(o, dict) and o.get("type") == "flatrate" and o.get("provider_name")
            ]
            services_by_tmdb[avail.tmdb_id] = list(dict.fromkeys(flatrate))

    return HomeAssistantPayload(
        user=user.display_name,
        generated_at=datetime.now(UTC),
        high_rated_recommendations=[
            _build_movie(title, score, jellyfin_ids, services_by_tmdb) for title, score in rec_rows
        ],
        shortlisted=[
            _build_movie(title, score, jellyfin_ids, services_by_tmdb)
            for title, score in shortlist_rows
        ],
    )
