"""Parent-managed child profiles and per-country film certificate limits."""

import secrets
import time
from typing import Annotated

from argon2.exceptions import VerifyMismatchError
from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from iwanttowatch.api.auth import hasher
from iwanttowatch.api.deps import AdultUser, CurrentUser, DbSession, ParentUser
from iwanttowatch.api.schemas import Me
from iwanttowatch.children import allowed_certificates, certificates_for_region
from iwanttowatch.models import User
from iwanttowatch.tmdb import TmdbClient, client_from_settings

router = APIRouter(prefix="/api/v1")

Region = Annotated[str, Field(pattern=r"^[A-Z]{2}$")]
Pin = Annotated[str, Field(pattern=r"^[0-9]{4,8}$")]
# Wrong PINs allowed before leaving a child profile is locked for a while.
PIN_ATTEMPTS = 5
PIN_LOCKOUT_SECONDS = 300


class CertificateOption(BaseModel):
    code: str
    meaning: str


class ChildOut(BaseModel):
    id: int
    name: str
    max_certificate: str


class ChildCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    max_certificate: str = Field(min_length=1, max_length=16)


class ChildUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    max_certificate: str = Field(min_length=1, max_length=16)


class PinStatus(BaseModel):
    pin_set: bool


class PinUpdate(BaseModel):
    pin: Pin


class PinCheck(BaseModel):
    pin: str = Field(max_length=8)


def _child_out(user: User) -> ChildOut:
    return ChildOut(id=user.id, name=user.display_name, max_certificate=user.max_certificate or "")


def _validate_certificate(tmdb: TmdbClient | None, region: str, certificate: str) -> str:
    code = certificate.strip()
    for option in certificates_for_region(tmdb, region):
        if option.code.upper() == code.upper():
            return option.code
    raise HTTPException(
        status.HTTP_400_BAD_REQUEST,
        f"{certificate!r} isn't a child certificate for region {region}",
    )


def _owned_child(session: DbSession, parent_id: int, child_id: int) -> User:
    child = session.get(User, child_id)
    if child is None or child.parent_id != parent_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Child profile not found")
    return child


@router.get("/certificates")
def list_certificates(
    user: CurrentUser, session: DbSession, request: Request, region: Region | None = None
) -> list[CertificateOption]:
    """Certificates a parent can set as a child's age limit in the country."""
    tmdb = client_from_settings(session, request.app.state.engine, request.app.state.tmdb_base_url)
    return [
        CertificateOption(code=c.code, meaning=c.meaning)
        for c in certificates_for_region(tmdb, region or user.region)
    ]


@router.get("/children")
def list_children(parent: AdultUser, session: DbSession) -> list[ChildOut]:
    """The child profiles managed by the signed-in parent."""
    children = session.scalars(
        select(User).where(User.parent_id == parent.id).order_by(User.display_name)
    )
    return [_child_out(c) for c in children]


@router.post("/children", status_code=status.HTTP_201_CREATED)
def create_child(
    body: ChildCreate, parent: AdultUser, session: DbSession, request: Request
) -> ChildOut:
    """Create a child profile under your account with a maximum film certificate."""
    tmdb = client_from_settings(session, request.app.state.engine, request.app.state.tmdb_base_url)
    cert = _validate_certificate(tmdb, parent.region, body.max_certificate)
    child = User(
        username=f"child-{secrets.token_hex(8)}",
        display_name=body.name.strip(),
        parent_id=parent.id,
        max_certificate=cert,
        allowed_certificates=allowed_certificates(parent.region, cert, tmdb),
        region=parent.region,
        languages=list(parent.languages),
        subscriptions=list(parent.subscriptions),
    )
    session.add(child)
    session.commit()
    if tmdb is not None:
        request.app.state.feed_worker.request(child.id)
    return _child_out(child)


@router.put("/children/{child_id}")
def update_child(
    child_id: int, body: ChildUpdate, parent: AdultUser, session: DbSession, request: Request
) -> ChildOut:
    child = _owned_child(session, parent.id, child_id)
    tmdb = client_from_settings(session, request.app.state.engine, request.app.state.tmdb_base_url)
    child.display_name = body.name.strip()
    child.max_certificate = _validate_certificate(tmdb, child.region, body.max_certificate)
    child.allowed_certificates = allowed_certificates(child.region, child.max_certificate, tmdb)
    session.commit()
    request.app.state.feed_worker.rescore_soon(child.id)
    return _child_out(child)


@router.delete("/children/{child_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_child(
    child_id: int, parent: AdultUser, session: DbSession, request: Request
) -> Response:
    child = session.get(User, child_id)
    if child is not None and child.parent_id == parent.id:
        if request.session.get("child_id") == child.id:
            request.session.pop("child_id", None)
        session.delete(child)
        session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me/parent-pin")
def read_parent_pin(parent: AdultUser) -> PinStatus:
    return PinStatus(pin_set=parent.parent_pin_hash is not None)


@router.put("/me/parent-pin")
def set_parent_pin(body: PinUpdate, parent: AdultUser, session: DbSession) -> PinStatus:
    """Set the PIN that's needed to leave a child profile."""
    parent.parent_pin_hash = hasher.hash(body.pin)
    session.commit()
    return PinStatus(pin_set=True)


@router.post("/children/{child_id}/switch")
def switch_to_child(child_id: int, parent: AdultUser, session: DbSession, request: Request) -> Me:
    """Use iWantToWatch as one of your child profiles; leaving it needs your parent PIN."""
    child = _owned_child(session, parent.id, child_id)
    if parent.parent_pin_hash is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Set a parent PIN first")
    request.session["child_id"] = child.id
    return Me.model_validate(child)


@router.post("/children/exit")
def exit_child(body: PinCheck, parent: ParentUser, request: Request) -> Me:
    """Switch back from a child profile to your parent account with your parent PIN."""
    if request.session.get("child_id") is None:
        return Me.model_validate(parent)
    failures: dict[int, list[float]] = request.app.state.pin_failures
    now = time.monotonic()
    recent = [t for t in failures.get(parent.id, []) if now - t < PIN_LOCKOUT_SECONDS]
    if len(recent) >= PIN_ATTEMPTS:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Too many wrong PINs; try again in a few minutes"
        )
    try:
        hasher.verify(parent.parent_pin_hash or "", body.pin)
    except (VerifyMismatchError, ValueError):
        failures[parent.id] = [*recent, now]
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Wrong PIN") from None
    failures.pop(parent.id, None)
    request.session.pop("child_id", None)
    return Me.model_validate(parent)
