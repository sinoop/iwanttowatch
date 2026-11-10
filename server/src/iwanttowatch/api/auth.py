from datetime import date

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import exists, select

from iwanttowatch.api.deps import CurrentUser, DbSession
from iwanttowatch.api.schemas import LoginRequest, Me, ProfileUpdate, SetupRequest, SetupStatus
from iwanttowatch.jellyfin import JellyfinError, client_from_settings
from iwanttowatch.models import User

router = APIRouter(prefix="/api/v1")
hasher = PasswordHasher()
# Verified when the username is unknown, so both failures take the same time.
_DUMMY_HASH = hasher.hash("iwanttowatch-dummy-password")


@router.get("/setup")
def setup_status(session: DbSession) -> SetupStatus:
    return SetupStatus(
        complete=session.scalar(select(exists().select_from(User))) or False,
        jellyfin_login=client_from_settings(session) is not None,
    )


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
        user = _jellyfin_login(request, session, body.username, body.password)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong username or password")
    request.session["user_id"] = user.id
    return Me.model_validate(user)


def _jellyfin_login(
    request: Request, session: DbSession, username: str, password: str
) -> User | None:
    """Sign in with Jellyfin credentials, creating the account on first sign-in."""
    jellyfin = client_from_settings(session)
    if jellyfin is None:
        return None
    try:
        identity = jellyfin.authenticate(username, password)
    except JellyfinError as error:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Couldn't reach Jellyfin to check your password"
        ) from error
    if identity is None:
        return None
    jellyfin_id, name = identity
    user = session.scalar(select(User).where(User.jellyfin_user_id == jellyfin_id))
    if user is None:
        # New household members start with the admin's region and languages.
        admin = session.scalars(select(User).where(User.is_admin).order_by(User.id)).first()
        assert admin is not None
        taken = set(session.scalars(select(User.username)))
        candidates = [name, f"{name} (Jellyfin)"] + [f"{name} ({n})" for n in range(2, 100)]
        user = User(
            username=next(c for c in candidates if c not in taken),
            display_name=name,
            jellyfin_user_id=jellyfin_id,
            region=admin.region,
            languages=list(admin.languages),
        )
        session.add(user)
        session.commit()
        request.app.state.jellyfin_worker.request_full_sync()
    return user


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request) -> Response:
    request.session.clear()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me")
def me(user: CurrentUser) -> Me:
    return Me.model_validate(user)


VALID_CONTENT_TYPES = {"movies", "standup", "concerts", "all"}


@router.put("/me/profile")
def update_profile(
    body: ProfileUpdate, user: CurrentUser, session: DbSession, request: Request
) -> Me:
    if body.birth_year is not None and body.birth_year > date.today().year:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "That year hasn't happened yet")
    if "birth_year" in body.model_fields_set:
        user.birth_year = body.birth_year
    if body.default_content_type is not None:
        if body.default_content_type not in VALID_CONTENT_TYPES:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"Content type must be one of {sorted(VALID_CONTENT_TYPES)}",
            )
        user.default_content_type = body.default_content_type
    session.commit()
    request.app.state.feed_worker.rescore_soon(user.id)
    return Me.model_validate(user)
