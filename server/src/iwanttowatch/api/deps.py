from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from iwanttowatch.db import get_session
from iwanttowatch.models import User
from iwanttowatch.tmdb import TmdbClient, client_from_settings

DbSession = Annotated[Session, Depends(get_session)]


def get_parent_user(request: Request, session: DbSession) -> User:
    user_id = request.session.get("user_id")
    user = session.get(User, user_id) if user_id is not None else None
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    return user


ParentUser = Annotated[User, Depends(get_parent_user)]


def get_current_user(request: Request, session: DbSession) -> User:
    parent = get_parent_user(request, session)
    child_id = request.session.get("child_id")
    if child_id is not None:
        child = session.get(User, child_id)
        if child is None or not child.is_child:
            request.session.pop("child_id", None)
            return parent
        return child
    return parent


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_adult_user(user: CurrentUser) -> User:
    if user.is_child:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed on a child profile")
    return user


AdultUser = Annotated[User, Depends(get_adult_user)]


def get_admin_user(user: CurrentUser) -> User:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only an admin can do this")
    return user


AdminUser = Annotated[User, Depends(get_admin_user)]


def get_tmdb(request: Request, session: DbSession) -> TmdbClient:
    tmdb = client_from_settings(session, request.app.state.engine, request.app.state.tmdb_base_url)
    if tmdb is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Add a TMDb API key in Settings first")
    return tmdb


Tmdb = Annotated[TmdbClient, Depends(get_tmdb)]
