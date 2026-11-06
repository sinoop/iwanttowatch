from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import exists, select

from cinematch.api.deps import CurrentUser, DbSession
from cinematch.api.schemas import LoginRequest, Me, SetupRequest, SetupStatus
from cinematch.db import User

router = APIRouter(prefix="/api/v1")
hasher = PasswordHasher()
# Verified when the username is unknown, so both failures take the same time.
_DUMMY_HASH = hasher.hash("cinematch-dummy-password")


@router.get("/setup")
def setup_status(session: DbSession) -> SetupStatus:
    return SetupStatus(complete=session.scalar(select(exists().select_from(User))) or False)


@router.post("/setup", status_code=status.HTTP_201_CREATED)
def complete_setup(body: SetupRequest, request: Request, session: DbSession) -> Me:
    """Create the first (admin) account. Only allowed while no account exists."""
    if session.scalar(select(exists().select_from(User))):
        raise HTTPException(status.HTTP_409_CONFLICT, "Setup is already complete")
    user = User(
        username=body.username,
        display_name=body.display_name,
        password_hash=hasher.hash(body.password),
        is_admin=True,
        region=body.region,
        languages=body.languages,
    )
    session.add(user)
    session.commit()
    request.session["user_id"] = user.id
    return Me.model_validate(user)


@router.post("/auth/login")
def login(body: LoginRequest, request: Request, session: DbSession) -> Me:
    user = session.scalar(select(User).where(User.username == body.username))
    try:
        hasher.verify(
            user.password_hash if user and user.password_hash else _DUMMY_HASH, body.password
        )
    except VerificationError:
        user = None
    if user is None or user.password_hash is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong username or password")
    request.session["user_id"] = user.id
    return Me.model_validate(user)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request) -> Response:
    request.session.clear()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me")
def me(user: CurrentUser) -> Me:
    return Me.model_validate(user)
