"""One-time invite links that let a new household member set up an account."""

import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from iwanttowatch.api.auth import hasher
from iwanttowatch.api.deps import AdminUser, DbSession
from iwanttowatch.api.schemas import Me, NewAccount
from iwanttowatch.db import utcnow
from iwanttowatch.jellyfin import client_from_settings
from iwanttowatch.models import Invite, User

router = APIRouter(prefix="/api/v1/invites")
INVITE_LENGTH = timedelta(days=7)


class InviteCreate(BaseModel):
    # Who it's for, suggested as their display name.
    name: str | None = Field(None, max_length=128)


class InviteOut(BaseModel):
    id: int
    token: str
    name: str | None
    created_by: str
    expires_at: datetime


class InvitePreview(BaseModel):
    name: str | None
    invited_by: str
    # Whether the new member could sign in with Jellyfin instead.
    jellyfin_login: bool


def _pending(session: DbSession) -> None:
    session.execute(delete(Invite).where(Invite.expires_at < utcnow()))


def _invite_out(session: DbSession, invite: Invite) -> InviteOut:
    admin = session.get(User, invite.created_by)
    assert admin is not None
    return InviteOut(
        id=invite.id,
        token=invite.token,
        name=invite.name,
        created_by=admin.display_name,
        expires_at=invite.expires_at.replace(tzinfo=UTC),
    )


def _open_invite(session: DbSession, token: str) -> Invite:
    _pending(session)
    invite = session.scalar(select(Invite).where(Invite.token == token))
    if invite is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "This invite has expired or was already used"
        )
    return invite


@router.post("", status_code=status.HTTP_201_CREATED)
def create_invite(body: InviteCreate, user: AdminUser, session: DbSession) -> InviteOut:
    """A link that sets up one new account within a week."""
    invite = Invite(
        token=secrets.token_urlsafe(24),
        created_by=user.id,
        name=(body.name or "").strip() or None,
        expires_at=utcnow() + INVITE_LENGTH,
    )
    session.add(invite)
    session.commit()
    return _invite_out(session, invite)


@router.get("")
def list_invites(user: AdminUser, session: DbSession) -> list[InviteOut]:
    """Invites not yet used or expired, newest first."""
    _pending(session)
    session.commit()
    invites = session.scalars(select(Invite).order_by(Invite.id.desc()))
    return [_invite_out(session, invite) for invite in invites]


@router.delete("/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_invite(invite_id: int, user: AdminUser, session: DbSession) -> Response:
    session.execute(delete(Invite).where(Invite.id == invite_id))
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{token}")
def preview_invite(token: str, session: DbSession) -> InvitePreview:
    """What the invite page shows before anyone signs in."""
    invite = _open_invite(session, token)
    session.commit()
    admin = session.get(User, invite.created_by)
    assert admin is not None
    return InvitePreview(
        name=invite.name,
        invited_by=admin.display_name,
        jellyfin_login=client_from_settings(session) is not None,
    )


@router.post("/{token}/accept", status_code=status.HTTP_201_CREATED)
def accept_invite(token: str, body: NewAccount, request: Request, session: DbSession) -> Me:
    """Create the new member's account, use up the invite, and sign them in."""
    invite = _open_invite(session, token)
    if session.scalar(select(User.id).where(User.username == body.username)):
        raise HTTPException(status.HTTP_409_CONFLICT, "That username is taken")
    admin = session.get(User, invite.created_by)
    assert admin is not None
    # Deleting it first means two people opening the same link can't both use it.
    if not session.execute(delete(Invite).where(Invite.id == invite.id)).rowcount:  # type: ignore[attr-defined]
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This invite was already used")
    # New members start with the inviting admin's region and languages, like Jellyfin sign-ins.
    user = User(
        username=body.username,
        display_name=body.display_name,
        password_hash=hasher.hash(body.password),
        region=admin.region,
        languages=list(admin.languages),
    )
    session.add(user)
    session.commit()
    request.session.clear()
    request.session["user_id"] = user.id
    return Me.model_validate(user)
