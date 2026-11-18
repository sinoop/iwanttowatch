import hashlib
import hmac
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import select

from iwanttowatch import radarr
from iwanttowatch.api.deps import DbSession, Tmdb
from iwanttowatch.api.feed import (
    AskBody,
    RadarrMovieStatus,
    TitleDetail,
    _title_detail,
    ask_feed,
)
from iwanttowatch.api.mcp import KEY_SETTING as MCP_KEY_SETTING
from iwanttowatch.api.reactions import (
    ReactionUpdate,
    TitleReaction,
    clear_reaction,
    load_title,
    load_title_and_availability,
    set_reaction,
)
from iwanttowatch.availability import availability
from iwanttowatch.catalog import search_movies
from iwanttowatch.feed import ensure_shortlist_recommendation
from iwanttowatch.llm import provider_from_settings
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
    overview: str | None = None
    in_jellyfin: bool = False
    in_shortlist: bool = False
    streaming_services: list[str] = []


class HomeAssistantAskMovie(HomeAssistantMovie):
    why: str


class HomeAssistantAskResponse(BaseModel):
    picks: list[HomeAssistantAskMovie]
    considered: int


class HomeAssistantPayload(BaseModel):
    user: str
    generated_at: datetime
    radarr_configured: bool = False
    llm_configured: bool = False
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


def _load_context(
    session: DbSession, user: User, tmdb_ids: list[int]
) -> tuple[set[int], set[int], dict[int, list[str]]]:
    """Load Jellyfin presence, shortlist membership, and flatrate streaming providers."""
    if not tmdb_ids:
        return set(), set(), {}

    jellyfin_ids = {
        tid
        for tid in session.scalars(
            select(LibraryItem.tmdb_id).where(
                LibraryItem.user_id == user.id,
                LibraryItem.tmdb_id.in_(tmdb_ids),
            )
        )
        if tid is not None
    }
    shortlist_ids = set(
        session.scalars(
            select(ShortlistItem.tmdb_id).where(
                ShortlistItem.user_id == user.id,
                ShortlistItem.tmdb_id.in_(tmdb_ids),
            )
        )
    )
    services_by_tmdb: dict[int, list[str]] = {}
    region = user.region or get_setting(session, "default_region") or "US"
    for avail in session.scalars(
        select(Availability).where(
            Availability.tmdb_id.in_(tmdb_ids),
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
    return jellyfin_ids, shortlist_ids, services_by_tmdb


def _build_movie(
    title: Title,
    score: float | None,
    jellyfin_ids: set[int],
    shortlist_ids: set[int],
    services_by_tmdb: dict[int, list[str]],
) -> HomeAssistantMovie:
    return HomeAssistantMovie(
        tmdb_id=title.tmdb_id,
        title=title.title,
        year=title.year,
        match=round(score * 100) if score is not None else None,
        imdb_rating=title.imdb_rating,
        poster_url=f"{TMDB_IMAGE_BASE}{title.poster_path}" if title.poster_path else None,
        overview=title.overview,
        in_jellyfin=title.tmdb_id in jellyfin_ids,
        in_shortlist=title.tmdb_id in shortlist_ids,
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
    jellyfin_ids, shortlist_ids, services_by_tmdb = _load_context(session, user, all_ids)
    radarr_url = get_setting(session, radarr.URL_SETTING)
    radarr_key = get_setting(session, radarr.API_KEY_SETTING)

    return HomeAssistantPayload(
        user=user.display_name,
        generated_at=datetime.now(UTC),
        radarr_configured=bool(radarr_url and radarr_key),
        llm_configured=provider_from_settings(session, "ask", user.id) is not None,
        high_rated_recommendations=[
            _build_movie(title, score, jellyfin_ids, shortlist_ids, services_by_tmdb)
            for title, score in rec_rows
        ],
        shortlisted=[
            _build_movie(title, score, jellyfin_ids, shortlist_ids, services_by_tmdb)
            for title, score in shortlist_rows
        ],
    )


@router.get("/integrations/home-assistant/search")
def home_assistant_search(
    request: Request,
    session: DbSession,
    tmdb: Tmdb,
    query: str = Query(..., min_length=1),
    year: int | None = Query(None),
    username: str | None = Query(None),
    limit: int = Query(20, ge=1, le=50),
) -> list[HomeAssistantMovie]:
    """Search TMDb for movies and enrich with match scores, shortlist, and availability."""
    user = _resolve_user(request, session, username)
    candidates = search_movies(tmdb, query, year)[:limit]
    tmdb_ids = [int(c["tmdb_id"]) for c in candidates]
    if not tmdb_ids:
        return []

    titles_by_id = {
        t.tmdb_id: t for t in session.scalars(select(Title).where(Title.tmdb_id.in_(tmdb_ids)))
    }
    scores_by_id = {
        tid: score
        for tid, score in session.execute(
            select(Recommendation.tmdb_id, Recommendation.score).where(
                Recommendation.user_id == user.id,
                Recommendation.tmdb_id.in_(tmdb_ids),
            )
        ).all()
    }
    jellyfin_ids, shortlist_ids, services_by_tmdb = _load_context(session, user, tmdb_ids)

    results: list[HomeAssistantMovie] = []
    for c in candidates:
        tid = int(c["tmdb_id"])
        cached = titles_by_id.get(tid)
        score = scores_by_id.get(tid)
        poster_path = cached.poster_path if cached else c.get("poster_path")
        results.append(
            HomeAssistantMovie(
                tmdb_id=tid,
                title=cached.title if cached else str(c.get("title") or ""),
                year=cached.year if cached else c.get("year"),
                match=round(score * 100) if score is not None else None,
                imdb_rating=cached.imdb_rating if cached else None,
                poster_url=f"{TMDB_IMAGE_BASE}{poster_path}" if poster_path else None,
                overview=cached.overview if cached else c.get("overview"),
                in_jellyfin=tid in jellyfin_ids,
                in_shortlist=tid in shortlist_ids,
                streaming_services=services_by_tmdb.get(tid, []),
            )
        )
    return results


@router.put(
    "/integrations/home-assistant/titles/{tmdb_id}/shortlist",
    status_code=status.HTTP_204_NO_CONTENT,
)
def home_assistant_add_shortlist(
    tmdb_id: int,
    request: Request,
    session: DbSession,
    tmdb: Tmdb,
    username: str | None = Query(None),
) -> Response:
    """Add a movie to the user's shortlist from Home Assistant."""
    user = _resolve_user(request, session, username)
    if session.get(Title, tmdb_id) is None:
        title = load_title_and_availability(session, request, tmdb, tmdb_id, user.region)
    else:
        title = load_title(session, request, tmdb_id)
        availability(session, tmdb, [tmdb_id], user.region)
    if session.get(ShortlistItem, (user.id, tmdb_id)) is None:
        session.add(ShortlistItem(user_id=user.id, tmdb_id=tmdb_id))
        session.commit()
        if (
            not ensure_shortlist_recommendation(session, user, tmdb_id)
            and session.get(Recommendation, (user.id, tmdb_id)) is None
        ):
            request.app.state.feed_worker.rescore_soon(user.id)
        radarr.auto_sync_if_unstreamable(session, tmdb, user, tmdb_id, title)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/integrations/home-assistant/titles/{tmdb_id}/shortlist",
    status_code=status.HTTP_204_NO_CONTENT,
)
def home_assistant_remove_shortlist(
    tmdb_id: int,
    request: Request,
    session: DbSession,
    username: str | None = Query(None),
) -> Response:
    """Remove a movie from the user's shortlist from Home Assistant."""
    user = _resolve_user(request, session, username)
    entry = session.get(ShortlistItem, (user.id, tmdb_id))
    if entry is not None:
        session.delete(entry)
        session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/integrations/home-assistant/titles/{tmdb_id}/radarr")
def home_assistant_radarr_status(
    tmdb_id: int,
    request: Request,
    session: DbSession,
    username: str | None = Query(None),
) -> RadarrMovieStatus:
    """Check whether a movie is already in Radarr."""
    _resolve_user(request, session, username)
    return RadarrMovieStatus(**radarr.movie_status(session, tmdb_id))


@router.post("/integrations/home-assistant/titles/{tmdb_id}/radarr")
def home_assistant_request_radarr(
    tmdb_id: int,
    request: Request,
    session: DbSession,
    username: str | None = Query(None),
) -> RadarrMovieStatus:
    """Queue a movie in Radarr from Home Assistant."""
    user = _resolve_user(request, session, username)
    if user.is_child:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Child profiles cannot request downloads",
        )
    title = load_title(session, request, tmdb_id)
    try:
        radarr.queue_movie(
            session=session,
            tmdb_id=tmdb_id,
            title=title.title,
            year=title.year,
            language=title.original_language,
            search=True,
        )
    except radarr.RadarrError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Radarr error: {error}") from error
    return RadarrMovieStatus(**radarr.movie_status(session, tmdb_id))


@router.get("/integrations/home-assistant/titles/{tmdb_id}")
def home_assistant_title_detail(
    tmdb_id: int,
    request: Request,
    session: DbSession,
    tmdb: Tmdb,
    username: str | None = Query(None),
) -> TitleDetail:
    """Full movie details (genres, runtime, cast, match reasons, availability, Radarr)."""
    user = _resolve_user(request, session, username)
    if session.get(Title, tmdb_id) is None:
        title = load_title_and_availability(session, request, tmdb, tmdb_id, user.region)
    else:
        title = load_title(session, request, tmdb_id)
    return _title_detail(session, user, tmdb, title)


@router.put("/integrations/home-assistant/titles/{tmdb_id}/reaction")
def home_assistant_set_reaction(
    tmdb_id: int,
    body: ReactionUpdate,
    request: Request,
    session: DbSession,
    username: str | None = Query(None),
) -> TitleReaction:
    """Rate or mark a movie watched from Home Assistant."""
    user = _resolve_user(request, session, username)
    return set_reaction(tmdb_id, body, user, session, request)


@router.delete(
    "/integrations/home-assistant/titles/{tmdb_id}/reaction",
    status_code=status.HTTP_204_NO_CONTENT,
)
def home_assistant_clear_reaction(
    tmdb_id: int,
    request: Request,
    session: DbSession,
    username: str | None = Query(None),
) -> Response:
    """Clear a movie's rating/watched status from Home Assistant."""
    user = _resolve_user(request, session, username)
    return clear_reaction(tmdb_id, user, session, request)


@router.post("/integrations/home-assistant/ask")
def home_assistant_ask(
    body: AskBody,
    request: Request,
    session: DbSession,
    username: str | None = Query(None),
    available_only: bool = Query(False),
) -> HomeAssistantAskResponse:
    """Natural-language Ask AI movie search for Home Assistant."""
    user = _resolve_user(request, session, username)
    answer = ask_feed(body, user, session, request, available_only=available_only)
    if not answer.picks:
        return HomeAssistantAskResponse(picks=[], considered=answer.considered)

    tmdb_ids = [p.tmdb_id for p in answer.picks]
    titles_by_id = {
        t.tmdb_id: t for t in session.scalars(select(Title).where(Title.tmdb_id.in_(tmdb_ids)))
    }
    scores_by_id = {
        tid: score
        for tid, score in session.execute(
            select(Recommendation.tmdb_id, Recommendation.score).where(
                Recommendation.user_id == user.id,
                Recommendation.tmdb_id.in_(tmdb_ids),
            )
        ).all()
    }
    jellyfin_ids, shortlist_ids, services_by_tmdb = _load_context(session, user, tmdb_ids)

    enriched: list[HomeAssistantAskMovie] = []
    for pick in answer.picks:
        title = titles_by_id.get(pick.tmdb_id)
        if title is None:
            continue
        movie = _build_movie(
            title,
            scores_by_id.get(pick.tmdb_id),
            jellyfin_ids,
            shortlist_ids,
            services_by_tmdb,
        )
        enriched.append(HomeAssistantAskMovie(**movie.model_dump(), why=pick.why))
    return HomeAssistantAskResponse(picks=enriched, considered=answer.considered)
