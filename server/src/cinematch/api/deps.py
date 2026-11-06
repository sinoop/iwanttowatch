from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from cinematch.db import User, get_session

DbSession = Annotated[Session, Depends(get_session)]


def get_current_user(request: Request, session: DbSession) -> User:
    user_id = request.session.get("user_id")
    user = session.get(User, user_id) if user_id is not None else None
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
