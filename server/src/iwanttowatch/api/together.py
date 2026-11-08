"""Watch together: pick who's watching, share your taste, and get group picks."""

import json
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Form, HTTPException, Query, Request, Response, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from iwanttowatch.api.deps import AdultUser, CurrentUser, DbSession, Tmdb
from iwanttowatch.api.reactions import load_title
from iwanttowatch.api.schemas import ImdbScore, imdb_score
from iwanttowatch.api.streaming import (
    PlatformCount,
    TitleAvailability,
    platform_counts,
    shown_for,
    title_availability,
)
from iwanttowatch.availability import availability
from iwanttowatch.children import allowed_for
from iwanttowatch.db import utcnow
from iwanttowatch.models import (
    Availability,
    GroupShortlistItem,
    Guest,
    LibraryItem,
    TasteShare,
    Title,
    User,
)
from iwanttowatch.moods import moods_for
from iwanttowatch.tmdb import client_from_settings
from iwanttowatch.together import (
    ShareError,
    ShareRevoked,
    fetch_share,
    group_picks,
    guest_member,
    local_member,
    new_share_token,
    parse_share,
    share_owner,
    shared_profile,
    store_share,
)

router = APIRouter(prefix="/api/v1")

# A friend's shared taste is fetched again when it's this old, which is also when
# a revoked link stops counting.
GUEST_REFRESH = timedelta(hours=1)
# A card of 1,000 ratings and a few thousand seen films is about 100 KB.
MAX_CARD_BYTES = 1024 * 1024


class Person(BaseModel):
    id: int
    name: str
    # Set on child profiles, e.g. "U/A 7+" or "PG".
    max_certificate: str | None = None


class GuestOut(BaseModel):
    id: int
    name: str
    # Added from a taste card file rather than a link, so it doesn't update itself.
    from_card: bool
    ratings: int
    fetched_at: datetime
    error: str | None


class ShareOut(BaseModel):
    # The link is this server's address followed by /api/v1/shared/{token}.
    token: str | None


class TogetherOptions(BaseModel):
    household: list[Person]
    guests: list[GuestOut]
    share: ShareOut


class SharedLabel(BaseModel):
    tmdb_id: int
    value: float
    weight: float
    explicit: bool


class SharedTaste(BaseModel):
    format: Literal["iwanttowatch-taste"]
    version: int
    labels: list[SharedLabel]
    seen: list[int]


class GuestCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    link: str = Field(pattern=r"^https?://.+/api/v1/shared/[A-Za-z0-9_-]+$", max_length=2048)


class MemberMatch(BaseModel):
    key: str
    name: str
    match: int


class GroupItem(BaseModel):
    tmdb_id: int
    title: str
    original_title: str
    original_language: str
    year: int | None
    runtime: int | None
    certificate: str | None = None
    poster_path: str | None
    genres: list[str]
    moods: list[str]
    # The average of everyone's match, 0–100. The order also penalises films anyone is
    # likely to dislike, so a lower average can rank above a higher one.
    match: int
    matches: list[MemberMatch]
    reasons: list[str]
    availability: TitleAvailability
    imdb: ImdbScore | None
    # Who saved it to the group shortlist, if anyone.
    shortlisted_by: str | None


class GroupPage(BaseModel):
    total: int
    items: list[GroupItem]
    # Where the picks can be played (before the platform filter).
    platforms: list[PlatformCount]
    # Group shortlist films among the picks (before the platform filter).
    shortlist_count: int


def _guest_out(guest: Guest) -> GuestOut:
    return GuestOut(
        id=guest.id,
        name=guest.name,
        from_card=guest.link is None,
        ratings=sum(1 for x in guest.labels if x["explicit"]),
        fetched_at=guest.fetched_at.replace(tzinfo=UTC),
        error=guest.error,
    )


def _percent(value: float) -> int:
    return min(max(round(value * 100), 1), 99)


@router.get("/together")
def together_options(user: CurrentUser, session: DbSession) -> TogetherOptions:
    """Everyone on this server, the friends you've added, and your share link."""
    household = session.scalars(select(User).order_by(User.display_name)).all()
    guests = (
        session.scalars(select(Guest).where(Guest.owner_id == user.id).order_by(Guest.name)).all()
        if user.parent_id is None
        else []
    )
    share = session.get(TasteShare, user.id) if user.parent_id is None else None
    return TogetherOptions(
        household=[
            Person(id=u.id, name=u.display_name, max_certificate=u.max_certificate)
            for u in household
        ],
        guests=[_guest_out(g) for g in guests],
        share=ShareOut(token=share.token if share else None),
    )


@router.get("/together/picks")
def together_picks(
    user: CurrentUser,
    session: DbSession,
    request: Request,
    users: Annotated[list[int], Query()] = [],  # noqa: B006 (FastAPI copies defaults)
    guests: Annotated[list[int], Query()] = [],  # noqa: B006
    available_only: bool = True,
    # "jellyfin" or TMDb provider IDs; when given, only films on one of them.
    platforms: Annotated[list[str], Query()] = [],  # noqa: B006
    # Only the group shortlist.
    shortlist: bool = False,
    limit: int = Query(24, ge=1, le=100),
) -> GroupPage:
    """Films for everyone chosen, from the household members' feeds; where to watch
    them is worked out for you, the host."""
    people = {u.id: u for u in session.scalars(select(User).where(User.id.in_(users)))}
    friends = (
        session.scalars(select(Guest).where(Guest.owner_id == user.id, Guest.id.in_(guests))).all()
        if user.parent_id is None
        else []
    )
    tmdb = client_from_settings(session, request.app.state.engine, request.app.state.tmdb_base_url)
    current = []
    for guest in friends:
        stale = utcnow() - guest.fetched_at.replace(tzinfo=UTC) >= GUEST_REFRESH
        if tmdb is not None and guest.link is not None and stale:
            try:
                store_share(session, tmdb, guest, fetch_share(guest.link))
            except ShareRevoked:
                session.delete(guest)
                continue
            except ShareError as error:
                guest.error = str(error)
        current.append(guest)
    session.commit()

    members = [local_member(session, people[i]) for i in users if i in people]
    members += [guest_member(g) for g in current]
    saved = {
        item.tmdb_id: name
        for item, name in session.execute(
            select(GroupShortlistItem, User.display_name).join(
                User, User.id == GroupShortlistItem.added_by
            )
        )
    }
    picks = group_picks(session, list(people), members, saved)
    ids = [p.tmdb_id for p in picks]
    titles = {t.tmdb_id: t for t in session.scalars(select(Title).where(Title.tmdb_id.in_(ids)))}
    owner_id = user.parent_id or user.id
    library = set(
        session.scalars(
            select(LibraryItem.tmdb_id).where(
                LibraryItem.user_id == owner_id, LibraryItem.tmdb_id.in_(ids)
            )
        )
    )
    offers = {
        row.tmdb_id: row
        for row in session.scalars(
            select(Availability).where(
                Availability.region == user.region, Availability.tmdb_id.in_(ids)
            )
        )
    }
    items = []
    places = []
    shortlist_count = 0
    for pick in picks:
        title = titles[pick.tmdb_id]
        if not allowed_for(title, user.region, user.allowed_certificates):
            continue
        shortlist_count += pick.tmdb_id in saved
        if shortlist and pick.tmdb_id not in saved:
            continue
        where = title_availability(
            pick.tmdb_id, offers.get(pick.tmdb_id), pick.tmdb_id in library, user.subscriptions
        )
        places.append(where)
        if not shown_for(where, available_only, platforms):
            continue
        # Kids can't see other people's ratings, including in group reasons.
        reasons = (
            [r for r in pick.reasons if r.startswith(f"{user.display_name}: ")]
            if user.parent_id is not None
            else pick.reasons
        )
        items.append(
            GroupItem(
                tmdb_id=title.tmdb_id,
                title=title.title,
                original_title=title.original_title,
                original_language=title.original_language,
                year=title.year,
                runtime=title.runtime,
                certificate=(title.certifications or {}).get(user.region),
                poster_path=title.poster_path,
                genres=title.genres,
                moods=moods_for(title),
                match=_percent(sum(pick.matches) / len(pick.matches)),
                matches=[
                    MemberMatch(key=m.key, name=m.name, match=_percent(value))
                    for m, value in zip(members, pick.matches, strict=True)
                ],
                reasons=reasons,
                availability=where,
                imdb=imdb_score(title),
                shortlisted_by=saved.get(pick.tmdb_id),
            )
        )
    return GroupPage(
        total=len(items),
        items=items[:limit],
        platforms=platform_counts(places),
        shortlist_count=shortlist_count,
    )


@router.put("/together/shortlist/{tmdb_id}", status_code=status.HTTP_204_NO_CONTENT)
def add_to_group_shortlist(
    tmdb_id: int, user: CurrentUser, session: DbSession, request: Request, tmdb: Tmdb
) -> Response:
    """Save a film for everyone on this server to choose from on Watch together."""
    title = load_title(session, request, tmdb_id)
    if not allowed_for(title, user.region, user.allowed_certificates):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "This film is above this profile's age limit"
        )
    # Look up where it streams before writing: the lookup caches on its own connection.
    availability(session, tmdb, [tmdb_id], user.region)
    if session.get(GroupShortlistItem, tmdb_id) is None:
        session.add(GroupShortlistItem(tmdb_id=tmdb_id, added_by=user.id))
        session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/together/shortlist/{tmdb_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_from_group_shortlist(tmdb_id: int, user: CurrentUser, session: DbSession) -> Response:
    """Adults can take any film off; a child only the ones they added."""
    entry = session.get(GroupShortlistItem, tmdb_id)
    if entry is not None:
        if user.parent_id is not None and entry.added_by != user.id:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Ask a grown-up to take this film off the list"
            )
        session.delete(entry)
        session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/guests", status_code=status.HTTP_201_CREATED)
def add_guest(body: GuestCreate, user: AdultUser, session: DbSession, tmdb: Tmdb) -> GuestOut:
    """Add a friend from another server by the share link they sent you."""
    try:
        data = fetch_share(body.link)
    except ShareError as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(error)) from error
    guest = Guest(owner_id=user.id, name=body.name.strip(), link=body.link)
    session.add(guest)
    store_share(session, tmdb, guest, data)
    session.commit()
    return _guest_out(guest)


@router.post("/guests/card", status_code=status.HTTP_201_CREATED)
def add_guest_from_card(
    name: Annotated[str, Form(min_length=1, max_length=64)],
    file: UploadFile,
    user: AdultUser,
    session: DbSession,
    tmdb: Tmdb,
) -> GuestOut:
    """Add a friend by the taste card file they sent you, for when your server can't
    reach theirs. A card doesn't update itself; they can send you a new one."""
    content = file.file.read(MAX_CARD_BYTES + 1)
    if len(content) > MAX_CARD_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "The file is larger than 1 MB")
    try:
        data = parse_share(json.loads(content))
    except (ValueError, ShareError) as error:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"{file.filename or 'This'} isn't a taste card"
        ) from error
    guest = Guest(owner_id=user.id, name=name.strip(), link=None)
    session.add(guest)
    store_share(session, tmdb, guest, data)
    session.commit()
    return _guest_out(guest)


@router.delete("/guests/{guest_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_guest(guest_id: int, user: AdultUser, session: DbSession) -> Response:
    guest = session.get(Guest, guest_id)
    if guest is not None and guest.owner_id == user.id:
        session.delete(guest)
        session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/me/share")
def create_share(user: AdultUser, session: DbSession) -> ShareOut:
    """Make a new share link; any earlier link stops working."""
    share = session.get(TasteShare, user.id) or TasteShare(user_id=user.id)
    share.token, share.created_at = new_share_token(), utcnow()
    session.add(share)
    session.commit()
    return ShareOut(token=share.token)


@router.delete("/me/share", status_code=status.HTTP_204_NO_CONTENT)
def revoke_share(user: AdultUser, session: DbSession) -> Response:
    share = session.get(TasteShare, user.id)
    if share is not None:
        session.delete(share)
        session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me/taste-card")
def download_taste_card(user: AdultUser, session: DbSession, response: Response) -> SharedTaste:
    """Your shared taste as a file, for friends whose server can't reach yours. It holds
    the same as a share link: films and how much you liked them, without your name."""
    response.headers["Content-Disposition"] = 'attachment; filename="taste-card.json"'
    return SharedTaste.model_validate(shared_profile(session, user.id))


@router.get("/shared/{token}")
def read_share(token: str, session: DbSession) -> SharedTaste:
    """A user's shared taste, for friends' servers; no sign-in, only the secret link."""
    owner = share_owner(session, token)
    if owner is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This link was revoked")
    return SharedTaste.model_validate(shared_profile(session, owner))
