"""Guest voting: a host shares a link, and guests vote on films without an account.

The ballot is the household's group picks with the group shortlist first. Guests see
only posters, titles, and where each film streams for the host; they never see
anyone's ratings or matches. Votes and guest names go when the vote is closed or
expires.
"""

import secrets
import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from iwanttowatch.api.deps import AdultUser, DbSession, Tmdb
from iwanttowatch.api.streaming import TitleAvailability, shown_for, title_availability
from iwanttowatch.availability import availability
from iwanttowatch.catalog import ensure_titles, search_movies
from iwanttowatch.children import allowed_for
from iwanttowatch.db import utcnow
from iwanttowatch.models import (
    GroupShortlistItem,
    LibraryItem,
    Title,
    User,
    Vote,
    Voter,
    VoteSession,
)
from iwanttowatch.together import group_picks, household_matches, local_member

router = APIRouter(prefix="/api/v1")

VOTE_LENGTH = timedelta(hours=24)
BALLOT_SIZE = 24
# Films guests can add from search, on top of the ballot.
MAX_ADDED = 12
MAX_VOTERS = 30
SEARCH_RESULTS = 8
# Requests per minute from one address to the pages guests use without signing in.
GUEST_REQUESTS_PER_MINUTE = 120

Choice = Literal["yes", "maybe", "no", "seen"]
# How much each vote counts towards a film; the household's match counts as one voter.
CHOICE_VALUE = {"yes": 1.0, "maybe": 0.5, "no": 0.0}

_recent: dict[str, deque[float]] = defaultdict(deque)


def guest_rate_limit(request: Request) -> None:
    address = request.client.host if request.client else "unknown"
    now = time.monotonic()
    hits = _recent[address]
    while hits and now - hits[0] > 60:
        hits.popleft()
    if len(hits) >= GUEST_REQUESTS_PER_MINUTE:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many requests; wait a minute")
    hits.append(now)


GuestLimit = Annotated[None, Depends(guest_rate_limit)]


class VoteCreate(BaseModel):
    # Household members watching; the host usually included.
    users: list[int] = Field(min_length=1)


class Tally(BaseModel):
    yes: list[str]
    maybe: list[str]
    no: list[str]
    seen: list[str]


class TallyFilm(BaseModel):
    tmdb_id: int
    title: str
    year: int | None
    poster_path: str | None
    # The household's average match, 0–100, when anyone at home is watching.
    match: int | None
    tally: Tally
    # Votes and the household's match combined, 0–100; None once a guest has seen it.
    score: int | None
    # Added by a guest from search.
    added: bool


class VoteSessionOut(BaseModel):
    # The guests' page is this server's address followed by /vote/{token}.
    token: str
    expires_at: datetime
    voters: list[str]
    # Best first; films a guest has seen come last.
    films: list[TallyFilm]


class BallotFilm(BaseModel):
    tmdb_id: int
    title: str
    original_title: str
    year: int | None
    runtime: int | None
    genres: list[str]
    poster_path: str | None
    availability: TitleAvailability


class Ballot(BaseModel):
    expires_at: datetime
    films: list[BallotFilm]
    # This guest's votes, when the request carries their voter token.
    votes: dict[int, Choice]
    # Whether more films can still be added from search.
    can_add: bool


class JoinRequest(BaseModel):
    name: str = Field(min_length=1, max_length=32)


class Joined(BaseModel):
    # Send as the X-Voter header to vote.
    voter_token: str


class VoteUpdate(BaseModel):
    choice: Choice


class SearchResult(BaseModel):
    tmdb_id: int
    title: str
    year: int | None
    poster_path: str | None
    on_ballot: bool


def _purge_expired(session: Session) -> None:
    session.execute(delete(VoteSession).where(VoteSession.expires_at < utcnow()))


def _open_session(session: Session, token: str) -> VoteSession:
    # Committed at once: TMDb lookups after this write their cache on another connection.
    _purge_expired(session)
    session.commit()
    vote = session.scalar(select(VoteSession).where(VoteSession.token == token))
    if vote is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This vote has ended or the link is wrong")
    return vote


def _members(session: Session, vote: VoteSession) -> list[User]:
    return list(session.scalars(select(User).where(User.id.in_(vote.user_ids))))


def _places(
    session: Session, tmdb: Tmdb, host: User, ids: list[int]
) -> dict[int, TitleAvailability]:
    """Where the host can play each film: their Jellyfin libraries or services."""
    rows = availability(session, tmdb, ids, host.region)
    library = set(
        session.scalars(
            select(LibraryItem.tmdb_id).where(
                LibraryItem.user_id == (host.parent_id or host.id), LibraryItem.tmdb_id.in_(ids)
            )
        )
    )
    return {i: title_availability(i, rows.get(i), i in library, host.subscriptions) for i in ids}


def _voter(session: Session, vote: VoteSession, token: str | None) -> Voter | None:
    if not token:
        return None
    return session.scalar(select(Voter).where(Voter.session_id == vote.id, Voter.token == token))


def _session_out(session: Session, vote: VoteSession) -> VoteSessionOut:
    ids = [entry["tmdb_id"] for entry in vote.ballot]
    titles = {t.tmdb_id: t for t in session.scalars(select(Title).where(Title.tmdb_id.in_(ids)))}
    voters = list(session.scalars(select(Voter).where(Voter.session_id == vote.id)))
    names = {v.id: v.name for v in voters}
    tallies: dict[int, dict[str, list[str]]] = {
        i: {"yes": [], "maybe": [], "no": [], "seen": []} for i in ids
    }
    for v in session.scalars(select(Vote).where(Vote.voter_id.in_(names))):
        if v.tmdb_id in tallies:
            tallies[v.tmdb_id][v.choice].append(names[v.voter_id])
    films = []
    for entry in vote.ballot:
        tmdb_id, match = entry["tmdb_id"], entry.get("match")
        tally = tallies[tmdb_id]
        values = [CHOICE_VALUE[c] for c in ("yes", "maybe", "no") for _ in tally[c]]
        if match is not None:
            values.append(match)
        combined = sum(values) / len(values) if values else None
        title = titles[tmdb_id]
        films.append(
            TallyFilm(
                tmdb_id=tmdb_id,
                title=title.title,
                year=title.year,
                poster_path=title.poster_path,
                match=round(match * 100) if match is not None else None,
                tally=Tally(**tally),
                score=None if tally["seen"] or combined is None else round(combined * 100),
                added=bool(entry.get("added")),
            )
        )
    films.sort(key=lambda f: (f.score is None, -(f.score or 0)))
    return VoteSessionOut(
        token=vote.token,
        expires_at=vote.expires_at.replace(tzinfo=UTC),
        voters=[v.name for v in voters],
        films=films,
    )


@router.post("/together/vote", status_code=status.HTTP_201_CREATED)
def start_vote(body: VoteCreate, user: AdultUser, session: DbSession, tmdb: Tmdb) -> VoteSessionOut:
    """Start a guest vote on the group picks for these household members, replacing
    the host's previous vote."""
    people = list(session.scalars(select(User).where(User.id.in_(body.users))))
    if not people:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Pick at least one person at home")
    members = [local_member(session, p) for p in people]
    saved = set(session.scalars(select(GroupShortlistItem.tmdb_id)))
    picks = group_picks(session, [p.id for p in people], members, saved)
    titles = {
        t.tmdb_id: t
        for t in session.scalars(select(Title).where(Title.tmdb_id.in_([p.tmdb_id for p in picks])))
    }
    picks = [
        p for p in picks if allowed_for(titles[p.tmdb_id], user.region, user.allowed_certificates)
    ]
    places = _places(session, tmdb, user, [p.tmdb_id for p in picks])
    playable = [p for p in picks if shown_for(places[p.tmdb_id], True, [])]
    ordered = [p for p in playable if p.tmdb_id in saved] + [
        p for p in playable if p.tmdb_id not in saved
    ]
    ballot = [
        {"tmdb_id": p.tmdb_id, "match": sum(p.matches) / len(p.matches)}
        for p in ordered[:BALLOT_SIZE]
    ]
    if not ballot:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "No group picks are on your Jellyfin server or services yet",
        )
    session.execute(delete(VoteSession).where(VoteSession.host_id == user.id))
    vote = VoteSession(
        token=secrets.token_urlsafe(18),
        host_id=user.id,
        user_ids=[p.id for p in people],
        ballot=ballot,
        expires_at=utcnow() + VOTE_LENGTH,
    )
    session.add(vote)
    session.commit()
    return _session_out(session, vote)


@router.get("/together/vote")
def read_vote(user: AdultUser, session: DbSession) -> VoteSessionOut | None:
    """The host's running vote with everyone's votes so far, or nothing."""
    _purge_expired(session)
    session.commit()
    vote = session.scalar(select(VoteSession).where(VoteSession.host_id == user.id))
    return _session_out(session, vote) if vote else None


@router.delete("/together/vote", status_code=status.HTTP_204_NO_CONTENT)
def close_vote(user: AdultUser, session: DbSession) -> None:
    """End the vote; guests' names and votes are deleted with it."""
    session.execute(delete(VoteSession).where(VoteSession.host_id == user.id))
    session.commit()


@router.get("/vote/{token}")
def read_ballot(
    token: str,
    _limit: GuestLimit,
    session: DbSession,
    tmdb: Tmdb,
    x_voter: Annotated[str | None, Header()] = None,
) -> Ballot:
    vote = _open_session(session, token)
    host = session.get(User, vote.host_id)
    assert host is not None  # deleting the host deletes the vote
    ids = [entry["tmdb_id"] for entry in vote.ballot]
    titles = {t.tmdb_id: t for t in session.scalars(select(Title).where(Title.tmdb_id.in_(ids)))}
    places = _places(session, tmdb, host, ids)
    voter = _voter(session, vote, x_voter)
    votes = (
        {
            v.tmdb_id: v.choice
            for v in session.scalars(select(Vote).where(Vote.voter_id == voter.id))
        }
        if voter
        else {}
    )
    session.commit()
    return Ballot(
        expires_at=vote.expires_at.replace(tzinfo=UTC),
        films=[
            BallotFilm(
                tmdb_id=i,
                title=titles[i].title,
                original_title=titles[i].original_title,
                year=titles[i].year,
                runtime=titles[i].runtime,
                genres=titles[i].genres,
                poster_path=titles[i].poster_path,
                availability=places[i],
            )
            for i in ids
        ],
        votes=votes,  # type: ignore[arg-type]  # only Choice values are stored
        can_add=sum(1 for e in vote.ballot if e.get("added")) < MAX_ADDED,
    )


@router.post("/vote/{token}/join", status_code=status.HTTP_201_CREATED)
def join_vote(token: str, body: JoinRequest, _limit: GuestLimit, session: DbSession) -> Joined:
    vote = _open_session(session, token)
    name = " ".join(body.name.split())
    if not name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Enter your first name")
    voters = session.scalar(
        select(Voter.id).where(Voter.session_id == vote.id).offset(MAX_VOTERS - 1).limit(1)
    )
    if voters is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This vote is full")
    voter = Voter(session_id=vote.id, name=name, token=secrets.token_urlsafe(18))
    session.add(voter)
    session.commit()
    return Joined(voter_token=voter.token)


@router.put("/vote/{token}/votes/{tmdb_id}", status_code=status.HTTP_204_NO_CONTENT)
def cast_vote(
    token: str,
    tmdb_id: int,
    body: VoteUpdate,
    _limit: GuestLimit,
    session: DbSession,
    x_voter: Annotated[str | None, Header()] = None,
) -> None:
    vote = _open_session(session, token)
    voter = _voter(session, vote, x_voter)
    if voter is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Enter your name to vote")
    if all(entry["tmdb_id"] != tmdb_id for entry in vote.ballot):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That film isn't on the ballot")
    session.merge(Vote(voter_id=voter.id, tmdb_id=tmdb_id, choice=body.choice))
    session.commit()


@router.get("/vote/{token}/search")
def search_for_ballot(
    token: str,
    _limit: GuestLimit,
    session: DbSession,
    tmdb: Tmdb,
    query: str = Query(min_length=2, max_length=100),
) -> list[SearchResult]:
    """Films matching the query that the host can play, within any child's age limit."""
    vote = _open_session(session, token)
    host = session.get(User, vote.host_id)
    assert host is not None
    found = search_movies(tmdb, query)[:SEARCH_RESULTS]
    ids = [c["tmdb_id"] for c in found]
    titles = ensure_titles(session, tmdb, ids)
    session.commit()
    places = _places(session, tmdb, host, [i for i in ids if i in titles])
    people = _members(session, vote)
    on_ballot = {entry["tmdb_id"] for entry in vote.ballot}
    session.commit()
    return [
        SearchResult(
            tmdb_id=i,
            title=titles[i].title,
            year=titles[i].year,
            poster_path=titles[i].poster_path,
            on_ballot=i in on_ballot,
        )
        for i in ids
        if i in titles
        and shown_for(places[i], True, [])
        and all(allowed_for(titles[i], p.region, p.allowed_certificates) for p in [host, *people])
    ]


@router.post("/vote/{token}/films/{tmdb_id}", status_code=status.HTTP_204_NO_CONTENT)
def add_to_ballot(
    token: str,
    tmdb_id: int,
    _limit: GuestLimit,
    session: DbSession,
    tmdb: Tmdb,
    x_voter: Annotated[str | None, Header()] = None,
) -> None:
    """A guest adds a film they found; it must pass the same checks as search."""
    vote = _open_session(session, token)
    if _voter(session, vote, x_voter) is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Enter your name to add films")
    if any(entry["tmdb_id"] == tmdb_id for entry in vote.ballot):
        return
    if sum(1 for e in vote.ballot if e.get("added")) >= MAX_ADDED:
        raise HTTPException(status.HTTP_409_CONFLICT, "The ballot is full")
    host = session.get(User, vote.host_id)
    assert host is not None
    titles = ensure_titles(session, tmdb, [tmdb_id])
    session.commit()
    title = titles.get(tmdb_id)
    people = _members(session, vote)
    if title is None or not all(
        allowed_for(title, p.region, p.allowed_certificates) for p in [host, *people]
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That film can't be added")
    if not shown_for(_places(session, tmdb, host, [tmdb_id])[tmdb_id], True, []):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That film isn't on the host's services")
    match = household_matches(session, [local_member(session, p) for p in people], [tmdb_id])
    vote.ballot = [*vote.ballot, {"tmdb_id": tmdb_id, "match": match.get(tmdb_id), "added": True}]
    session.commit()
