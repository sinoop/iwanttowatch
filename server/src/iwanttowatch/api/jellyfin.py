import json
import secrets
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import delete, func, select

from iwanttowatch.api.deps import CurrentUser, DbSession
from iwanttowatch.jellyfin import (
    SOURCE,
    WEBHOOK_TOKEN_SETTING,
    JellyfinError,
    client_from_settings,
    normalise_id,
    record_webhook,
)
from iwanttowatch.models import LibraryItem, User, UserTitle, get_setting

router = APIRouter(prefix="/api/v1")

# Saves Jellyfin makes while a film is playing; the stop that follows is what counts.
IGNORED_EVENTS = {"PlaybackStart", "PlaybackProgress"}


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
    body: JellyfinLogin, user: CurrentUser, request: Request, session: DbSession
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
def unlink_jellyfin_account(user: CurrentUser, session: DbSession) -> JellyfinAccount:
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
