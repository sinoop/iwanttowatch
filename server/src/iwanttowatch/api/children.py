"""Household child profiles, age limits from birth year, and assigning films to a child."""

import secrets
from datetime import date

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from iwanttowatch.api.deps import AdultUser, DbSession, ParentUser, Tmdb
from iwanttowatch.api.reactions import load_title
from iwanttowatch.api.schemas import BirthYear, Me
from iwanttowatch.availability import availability
from iwanttowatch.children import refresh_limit
from iwanttowatch.models import Recommendation, ShortlistItem, User
from iwanttowatch.tmdb import client_from_settings

router = APIRouter(prefix="/api/v1")


class ChildOut(BaseModel):
    id: int
    name: str
    birth_year: int
    max_certificate: str


class ChildCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    birth_year: BirthYear


class ChildUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    birth_year: BirthYear


def _child_out(user: User) -> ChildOut:
    return ChildOut(
        id=user.id,
        name=user.display_name,
        birth_year=user.birth_year or date.today().year,
        max_certificate=user.max_certificate or "",
    )


def _child(session: DbSession, child_id: int) -> User:
    child = session.get(User, child_id)
    if child is None or not child.is_child:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Child profile not found")
    return child


def _validate_birth_year(birth_year: int) -> int:
    if birth_year > date.today().year:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "That year hasn't happened yet")
    return birth_year


@router.get("/children")
def list_children(_parent: ParentUser, session: DbSession) -> list[ChildOut]:
    """The household's child profiles, available to any signed-in adult."""
    children = session.scalars(
        select(User).where(User.is_child.is_(True)).order_by(User.display_name)
    )
    return [_child_out(c) for c in children]


@router.post("/children", status_code=status.HTTP_201_CREATED)
def create_child(
    body: ChildCreate, adult: AdultUser, session: DbSession, request: Request
) -> ChildOut:
    """Create a household child profile; its age limit comes from its birth year."""
    birth_year = _validate_birth_year(body.birth_year)
    tmdb = client_from_settings(session, request.app.state.engine, request.app.state.tmdb_base_url)
    child = User(
        username=f"child-{secrets.token_hex(8)}",
        display_name=body.name.strip(),
        is_child=True,
        birth_year=birth_year,
        region=adult.region,
        languages=list(adult.languages),
        subscriptions=list(adult.subscriptions),
        show_rent_buy=adult.show_rent_buy,
    )
    if not refresh_limit(child, tmdb):
        child.max_certificate, child.allowed_certificates = "", []
    session.add(child)
    session.commit()
    if tmdb is not None:
        request.app.state.feed_worker.request(child.id)
    return _child_out(child)


@router.put("/children/{child_id}")
def update_child(
    child_id: int, body: ChildUpdate, _adult: AdultUser, session: DbSession, request: Request
) -> ChildOut:
    child = _child(session, child_id)
    birth_year = _validate_birth_year(body.birth_year)
    tmdb = client_from_settings(session, request.app.state.engine, request.app.state.tmdb_base_url)
    child.display_name = body.name.strip()
    child.birth_year = birth_year
    if not refresh_limit(child, tmdb):
        child.max_certificate, child.allowed_certificates = "", []
    session.commit()
    request.app.state.feed_worker.rescore_soon(child.id)
    return _child_out(child)


@router.delete("/children/{child_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_child(
    child_id: int, _adult: AdultUser, session: DbSession, request: Request
) -> Response:
    child = session.get(User, child_id)
    if child is not None and child.is_child:
        if request.session.get("child_id") == child.id:
            request.session.pop("child_id", None)
        session.delete(child)
        session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/children/{child_id}/switch")
def switch_to_child(child_id: int, _parent: ParentUser, session: DbSession, request: Request) -> Me:
    """Switch to any household child profile."""
    child = _child(session, child_id)
    request.session["child_id"] = child.id
    return Me.model_validate(child)


@router.post("/children/exit")
def exit_child(parent: ParentUser, request: Request) -> Me:
    """Switch back from a child profile to your adult account."""
    request.session.pop("child_id", None)
    return Me.model_validate(parent)


@router.put("/children/{child_id}/shortlist/{tmdb_id}", status_code=status.HTTP_204_NO_CONTENT)
def assign_to_child(
    child_id: int,
    tmdb_id: int,
    _adult: AdultUser,
    session: DbSession,
    request: Request,
    tmdb: Tmdb,
) -> Response:
    """Assign a film to a child profile's shortlist so it shows up in their picks."""
    child = _child(session, child_id)
    load_title(session, request, tmdb_id)
    availability(session, tmdb, [tmdb_id], child.region)
    if session.get(ShortlistItem, (child.id, tmdb_id)) is None:
        session.add(ShortlistItem(user_id=child.id, tmdb_id=tmdb_id))
        session.commit()
        if session.get(Recommendation, (child.id, tmdb_id)) is None:
            request.app.state.feed_worker.rescore_soon(child.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/children/{child_id}/shortlist/{tmdb_id}", status_code=status.HTTP_204_NO_CONTENT)
def unassign_from_child(
    child_id: int, tmdb_id: int, _adult: AdultUser, session: DbSession
) -> Response:
    child = _child(session, child_id)
    entry = session.get(ShortlistItem, (child.id, tmdb_id))
    if entry is not None:
        session.delete(entry)
        session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
