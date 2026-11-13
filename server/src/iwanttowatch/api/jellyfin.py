import json
import secrets
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import delete, func, or_, select

from iwanttowatch.api.deps import AdultUser, CurrentUser, DbSession
from iwanttowatch.feed import feed_films, score_films, user_rated_matches
from iwanttowatch.jellyfin import (
    SOURCE,
    URL_SETTING,
    WEBHOOK_TOKEN_SETTING,
    JellyfinError,
    client_from_settings,
    normalise_id,
    record_webhook,
)
from iwanttowatch.models import (
    LibraryItem,
    RatingPrompt,
    Recommendation,
    ShortlistItem,
    Title,
    User,
    UserTitle,
    get_setting,
)

router = APIRouter(prefix="/api/v1")

# Frequent progress ticks are ignored; start and stop trigger item sync.
IGNORED_EVENTS = {"PlaybackProgress"}


class JellyfinAccount(BaseModel):
    server_configured: bool
    linked: bool
    # Accounts created by signing in with Jellyfin have no password to fall back on.
    can_unlink: bool
    library_movies: int
    watched: int
    favorites: int


class JellyfinLogin(BaseModel):
    username: str
    password: str


class InProgressItem(BaseModel):
    tmdb_id: int
    title: str
    year: int | None
    poster_path: str | None
    runtime: int | None
    playback_position_ticks: int
    playback_percentage: float
    playback_updated_at: datetime | None
    jellyfin_item_id: str
    jellyfin_url: str | None
    match: int | None = None
    is_rewatch: bool = False


class RatingPromptItem(BaseModel):
    id: int
    tmdb_id: int
    title: str
    year: int | None
    poster_path: str | None
    created_at: datetime


def _account(session: DbSession, user: User) -> JellyfinAccount:
    def count(*where: Any) -> int:
        query = select(func.count()).select_from(UserTitle)
        return session.scalar(query.where(UserTitle.user_id == user.id, *where)) or 0

    return JellyfinAccount(
        server_configured=client_from_settings(session) is not None,
        linked=user.jellyfin_user_id is not None,
        can_unlink=user.password_hash is not None,
        library_movies=session.scalar(select(func.count()).where(LibraryItem.user_id == user.id))
        or 0,
        watched=count(UserTitle.source == SOURCE, UserTitle.watched),
        favorites=count(UserTitle.source == SOURCE, UserTitle.favorite),
    )


@router.get("/me/jellyfin")
def read_jellyfin_account(user: CurrentUser, session: DbSession) -> JellyfinAccount:
    return _account(session, user)


@router.put("/me/jellyfin")
def link_jellyfin_account(
    body: JellyfinLogin, user: AdultUser, request: Request, session: DbSession
) -> JellyfinAccount:
    """Link the signed-in account to a Jellyfin user, proven by their Jellyfin password."""
    jellyfin = client_from_settings(session)
    if jellyfin is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "An admin needs to connect Jellyfin first")
    try:
        identity = jellyfin.authenticate(body.username, body.password)
    except JellyfinError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(error)) from error
    if identity is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Wrong Jellyfin username or password")
    owner = session.scalar(select(User).where(User.jellyfin_user_id == identity[0]))
    if owner is not None and owner.id != user.id:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"That Jellyfin user is already linked to {owner.display_name}",
        )
    user.jellyfin_user_id = identity[0]
    session.commit()
    request.app.state.jellyfin_worker.request_full_sync()
    return _account(session, user)


@router.delete("/me/jellyfin")
def unlink_jellyfin_account(user: AdultUser, session: DbSession) -> JellyfinAccount:
    """Unlink Jellyfin and forget everything synced from it."""
    if user.password_hash is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "This account signs in with Jellyfin, so it stays linked"
        )
    user.jellyfin_user_id = None
    session.execute(delete(LibraryItem).where(LibraryItem.user_id == user.id))
    session.execute(
        delete(UserTitle).where(UserTitle.user_id == user.id, UserTitle.source == SOURCE)
    )
    session.commit()
    return _account(session, user)


@router.get("/me/in-progress")
def list_in_progress(user: CurrentUser, session: DbSession) -> list[InProgressItem]:
    """Movies the user is currently watching on Jellyfin (in progress / resume)."""
    jellyfin_url = get_setting(session, URL_SETTING)
    stmt = (
        select(LibraryItem, Title)
        .outerjoin(Title, Title.tmdb_id == LibraryItem.tmdb_id)
        .where(
            LibraryItem.user_id == user.id,
            LibraryItem.tmdb_id.is_not(None),
            or_(LibraryItem.playback_percentage > 0.0, LibraryItem.playback_position_ticks > 0),
        )
        .order_by(
            LibraryItem.playback_updated_at.desc().nulls_last(),
            LibraryItem.last_played.desc().nulls_last(),
        )
    )
    items_with_titles = session.execute(stmt).all()
    if not items_with_titles:
        return []

    tmdb_ids = [item.tmdb_id for item, _ in items_with_titles if item.tmdb_id is not None]

    # Check which items are watched previously in UserTitle across any source
    watched_tmdb_ids = set(
        session.scalars(
            select(UserTitle.tmdb_id).where(
                UserTitle.user_id == user.id,
                UserTitle.tmdb_id.in_(tmdb_ids),
                or_(UserTitle.watched.is_(True), UserTitle.rating.is_not(None)),
            )
        )
    )

    # Gather match scores from Recommendation
    recommendations = {
        rec.tmdb_id: round(rec.score * 100)
        for rec in session.scalars(
            select(Recommendation).where(
                Recommendation.user_id == user.id,
                Recommendation.tmdb_id.in_(tmdb_ids),
            )
        )
    }

    # Gather match scores for rated titles from user_rated_matches if not in recommendations
    rated_matches = user_rated_matches(session, user)

    # For any titles without a match score in recommendations or rated_matches,
    # try scoring them if they have a Title
    missing_score_ids = [
        tid for tid in tmdb_ids if tid not in recommendations and tid not in rated_matches
    ]
    if missing_score_ids:
        try:
            feed_ids = feed_films(session, user)
            scored = score_films(session, user, [*feed_ids, *missing_score_ids])
            for s in scored:
                if s.tmdb_id in missing_score_ids:
                    recommendations[s.tmdb_id] = round(s.score * 100)
        except Exception:
            pass

    results: list[InProgressItem] = []
    seen_tmdb: set[int] = set()
    for item, title in items_with_titles:
        assert item.tmdb_id is not None
        if item.tmdb_id in seen_tmdb:
            continue
        seen_tmdb.add(item.tmdb_id)

        is_rewatch = bool(item.played or item.tmdb_id in watched_tmdb_ids)
        match_pct = recommendations.get(item.tmdb_id) or rated_matches.get(item.tmdb_id)

        results.append(
            InProgressItem(
                tmdb_id=item.tmdb_id,
                title=title.title if title else item.name,
                year=title.year if title else item.year,
                poster_path=title.poster_path if title else None,
                runtime=title.runtime if title else None,
                playback_position_ticks=item.playback_position_ticks,
                playback_percentage=round(item.playback_percentage, 1),
                playback_updated_at=item.playback_updated_at,
                jellyfin_item_id=item.item_id,
                jellyfin_url=f"{jellyfin_url}/web/#/details?id={item.item_id}"
                if jellyfin_url
                else None,
                match=match_pct,
                is_rewatch=is_rewatch,
            )
        )

    # Sort:
    # 1. Non-rewatches first (is_rewatch=False), rewatches at the end (is_rewatch=True)
    # 2. Within each group: decreasing match percentage (most recommended first)
    # 3. Tie-breaker: higher playback percentage, then playback_updated_at
    results.sort(
        key=lambda x: (
            x.is_rewatch,
            -(x.match if x.match is not None else -1),
            -(x.playback_percentage),
            -(x.playback_updated_at.timestamp() if x.playback_updated_at else 0),
        )
    )

    return results


@router.get("/me/rating-prompts")
def list_rating_prompts(user: CurrentUser, session: DbSession) -> list[RatingPromptItem]:
    """Active prompts to rate movies recently finished on Jellyfin."""
    stmt = (
        select(RatingPrompt, Title)
        .join(Title, Title.tmdb_id == RatingPrompt.tmdb_id)
        .where(
            RatingPrompt.user_id == user.id,
            RatingPrompt.dismissed.is_(False),
        )
        .order_by(RatingPrompt.created_at.desc())
    )
    return [
        RatingPromptItem(
            id=prompt.id,
            tmdb_id=prompt.tmdb_id,
            title=title.title,
            year=title.year,
            poster_path=title.poster_path,
            created_at=prompt.created_at,
        )
        for prompt, title in session.execute(stmt)
    ]


@router.post("/me/rating-prompts/{tmdb_id}/dismiss", status_code=status.HTTP_204_NO_CONTENT)
@router.delete("/me/rating-prompts/{tmdb_id}", status_code=status.HTTP_204_NO_CONTENT)
def dismiss_rating_prompt(tmdb_id: int, user: CurrentUser, session: DbSession) -> Response:
    """Dismiss a rating prompt without rating the film."""
    prompt = session.scalar(
        select(RatingPrompt).where(RatingPrompt.user_id == user.id, RatingPrompt.tmdb_id == tmdb_id)
    )
    if prompt is not None:
        prompt.dismissed = True
        session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class ShortlistSyncResponse(BaseModel):
    synced_count: int
    skipped_count: int
    playlist_name: str


@router.post("/jellyfin/sync-shortlist")
def sync_shortlist_to_jellyfin(user: CurrentUser, session: DbSession) -> ShortlistSyncResponse:
    """Sync the user's shortlisted movies that are in Jellyfin into a Jellyfin playlist."""
    jellyfin = client_from_settings(session)
    if jellyfin is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "An admin needs to connect Jellyfin first")
    if not user.jellyfin_user_id:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Link your Jellyfin account first in Settings"
        )
    shortlisted_tmdb_ids = list(
        session.scalars(select(ShortlistItem.tmdb_id).where(ShortlistItem.user_id == user.id))
    )
    if not shortlisted_tmdb_ids:
        return ShortlistSyncResponse(
            synced_count=0,
            skipped_count=0,
            playlist_name="iWantToWatch Shortlist",
        )
    library_rows = session.execute(
        select(LibraryItem.tmdb_id, LibraryItem.item_id).where(
            LibraryItem.user_id == user.id,
            LibraryItem.tmdb_id.in_(shortlisted_tmdb_ids),
        )
    ).all()
    tmdb_to_item: dict[int, str] = {}
    for tmdb_id, item_id in library_rows:
        if tmdb_id is not None and tmdb_id not in tmdb_to_item:
            tmdb_to_item[tmdb_id] = item_id
    item_ids = [tmdb_to_item[tid] for tid in shortlisted_tmdb_ids if tid in tmdb_to_item]
    skipped_count = len(shortlisted_tmdb_ids) - len(item_ids)
    playlist_name = "iWantToWatch Shortlist"
    try:
        synced_count = jellyfin.sync_shortlist_playlist(
            user.jellyfin_user_id, item_ids, playlist_name=playlist_name
        )
    except JellyfinError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(error)) from error
    return ShortlistSyncResponse(
        synced_count=synced_count,
        skipped_count=skipped_count,
        playlist_name=playlist_name,
    )


async def _json_body(request: Request) -> dict[str, Any]:
    """The Webhook plugin posts JSON as text/plain unless told otherwise."""
    try:
        body = json.loads(await request.body())
    except ValueError as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Expected a JSON object") from error
    if not isinstance(body, dict):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Expected a JSON object")
    return body


@router.post("/webhooks/jellyfin", status_code=status.HTTP_204_NO_CONTENT)
def jellyfin_webhook(
    request: Request,
    session: DbSession,
    body: Annotated[dict[str, Any], Depends(_json_body)],
    token: str = Query(""),
) -> Response:
    """Receive Jellyfin Webhook plugin notifications (Generic destination).

    Only the user and item IDs are used: the item is then re-read from Jellyfin.
    """
    expected = get_setting(session, WEBHOOK_TOKEN_SETTING)
    if not expected or not secrets.compare_digest(token, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong webhook token")
    record_webhook(session)
    fields = {key.lower(): str(value) for key, value in body.items() if value is not None}
    if fields.get("itemtype") != "Movie" or IGNORED_EVENTS & {
        fields.get("notificationtype"),
        fields.get("savereason"),
    }:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    worker = request.app.state.jellyfin_worker
    if fields.get("userid") and fields.get("itemid"):
        user = session.scalar(
            select(User).where(User.jellyfin_user_id == normalise_id(fields["userid"]))
        )
        if user is not None:
            worker.request_item_sync(user.id, normalise_id(fields["itemid"]))
    else:
        # Added or deleted: library changes reach every user who can see the item.
        worker.request_full_sync()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
