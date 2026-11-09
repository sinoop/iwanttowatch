"""Watch together: films a group is likely to enjoy, for household members on this
server and friends who shared their taste from another server, by a link the host's
server fetches or by a taste card file they send.

Each film is scored for each person by the same recommender as their own feed, then
combined as the average with a penalty when anyone is likely to dislike it (least
misery), so one person's favourite can't carry a film another would hate.
"""

import secrets
from collections.abc import Collection
from dataclasses import dataclass, field
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from iwanttowatch.catalog import ensure_titles
from iwanttowatch.children import allowed_for, family_tagged_films
from iwanttowatch.db import utcnow
from iwanttowatch.feed import hidden, seen, user_labels
from iwanttowatch.models import Guest, Recommendation, TasteShare, Title, User
from iwanttowatch.recommender import Label, score
from iwanttowatch.tmdb import TmdbClient

SHARE_FORMAT = "iwanttowatch-taste"
# Strongest labels first: explicit ratings, then the rest by weight.
MAX_SHARED_LABELS = 1000
FETCH_TIMEOUT_SECONDS = 10
# Below this predicted match for anyone, a film is penalised for the whole group.
MISERY_THRESHOLD = 0.6
MISERY_PENALTY = 2.0


class ShareError(Exception):
    pass


class ShareRevoked(ShareError):
    pass


@dataclass
class Member:
    key: str
    name: str
    labels: list[Label]
    # Watched or rated, so nobody sits through it twice.
    seen: set[int]
    # Turned down or not interested; local members only.
    hidden: set[int] = field(default_factory=set)
    birth_year: int | None = None
    region: str | None = None
    # Child profiles only; see User.allowed_certificates.
    allowed_certificates: list[str] | None = None
    family_picks: set[int] = field(default_factory=set)


@dataclass
class Pick:
    tmdb_id: int
    score: float
    # Each member's predicted match, 0–1, in member order.
    matches: list[float]
    reasons: list[str]


def shared_profile(session: Session, user_id: int) -> dict[str, Any]:
    """What a share link serves: TMDb IDs with how much the person liked each, and the
    films they've seen. No names, usernames, or server details."""
    labels = sorted(user_labels(session, user_id), key=lambda x: (not x.explicit, -x.weight))
    return {
        "format": SHARE_FORMAT,
        "version": 1,
        "labels": [
            {"tmdb_id": x.tmdb_id, "value": x.value, "weight": x.weight, "explicit": x.explicit}
            for x in labels[:MAX_SHARED_LABELS]
        ],
        "seen": sorted(seen(session, user_id)),
    }


def new_share_token() -> str:
    return secrets.token_urlsafe(24)


def share_owner(session: Session, token: str) -> int | None:
    return session.scalar(select(TasteShare.user_id).where(TasteShare.token == token))


def fetch_share(link: str) -> dict[str, Any]:
    """Download a friend's shared taste, checking it is one."""
    try:
        response = httpx.get(link, timeout=FETCH_TIMEOUT_SECONDS, follow_redirects=True)
    except httpx.HTTPError as error:
        raise ShareError(f"Couldn't reach the link: {error}") from error
    if response.status_code in (403, 404, 410):
        raise ShareRevoked("The link was revoked or is wrong")
    if response.status_code >= 400:
        raise ShareError(f"The link answered HTTP {response.status_code}")
    try:
        return parse_share(response.json())
    except ShareError as error:
        raise ShareError("The link isn't an iWantToWatch taste profile") from error


def parse_share(data: Any) -> dict[str, Any]:
    """Check a shared taste (from a link or a taste card file) and keep what's needed."""
    try:
        labels = [
            {
                "tmdb_id": int(x["tmdb_id"]),
                "value": min(max(float(x["value"]), 0.0), 1.0),
                "weight": min(max(float(x["weight"]), 0.0), 1.0),
                "explicit": bool(x["explicit"]),
            }
            for x in data["labels"][:MAX_SHARED_LABELS]
        ]
        watched = [int(i) for i in data["seen"]]
        right_format = data.get("format") == SHARE_FORMAT
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        raise ShareError("This isn't an iWantToWatch taste profile") from error
    if not right_format:
        raise ShareError("This isn't an iWantToWatch taste profile")
    return {"labels": labels, "seen": watched}


def store_share(session: Session, tmdb: TmdbClient, guest: Guest, data: dict[str, Any]) -> None:
    """Keep a fetched share, with the titles needed to score against it."""
    ensure_titles(session, tmdb, [x["tmdb_id"] for x in data["labels"]])
    guest.labels, guest.seen = data["labels"], data["seen"]
    guest.fetched_at, guest.error = utcnow(), None


def local_member(session: Session, user: User) -> Member:
    return Member(
        key=f"user:{user.id}",
        name=user.display_name,
        labels=user_labels(session, user.id),
        seen=seen(session, user.id),
        hidden=hidden(session, user.id),
        birth_year=user.birth_year,
        region=user.region,
        allowed_certificates=user.allowed_certificates,
        family_picks=family_tagged_films(session) if user.is_child else set(),
    )


def guest_member(guest: Guest) -> Member:
    return Member(
        key=f"guest:{guest.id}",
        name=guest.name,
        labels=[
            Label(x["tmdb_id"], x["value"], x["weight"], explicit=x["explicit"])
            for x in guest.labels
        ],
        seen=set(guest.seen),
    )


def group_score(matches: list[float]) -> float:
    """The average match, minus a penalty for anyone likely to be miserable."""
    misery = max(0.0, MISERY_THRESHOLD - min(matches))
    return sum(matches) / len(matches) - MISERY_PENALTY * misery


def household_matches(
    session: Session, members: list[Member], ids: Collection[int]
) -> dict[int, float]:
    """Each film's average match for the members, as on a group card."""
    if not members:
        return {}
    wanted = set(ids) | {x.tmdb_id for m in members for x in m.labels}
    titles = {t.tmdb_id: t for t in session.scalars(select(Title).where(Title.tmdb_id.in_(wanted)))}
    found = [i for i in ids if i in titles]
    totals = dict.fromkeys(found, 0.0)
    for m in members:
        for s in score(
            titles, m.labels, found, m.birth_year, child=m.allowed_certificates is not None
        ):
            totals[s.tmdb_id] += s.score
    return {i: total / len(members) for i, total in totals.items()}


def group_picks(
    session: Session, user_ids: list[int], members: list[Member], saved: Collection[int] = ()
) -> list[Pick]:
    """Films from the household members' feeds and the group shortlist (`saved`), best
    for everyone together first."""
    pool = set(
        session.scalars(select(Recommendation.tmdb_id).where(Recommendation.user_id.in_(user_ids)))
    ) | set(saved)
    for member in members:
        # Saving a film for the group overrides having turned it down before.
        pool -= member.seen | (member.hidden - set(saved))
    if not pool or not members:
        return []
    wanted = pool | {x.tmdb_id for m in members for x in m.labels}
    titles = {t.tmdb_id: t for t in session.scalars(select(Title).where(Title.tmdb_id.in_(wanted)))}
    candidates = sorted(
        i
        for i in pool
        if i in titles
        and all(allowed_for(titles[i], m.region or "", m.allowed_certificates) for m in members)
    )
    if not candidates:
        return []
    scored = [
        {
            s.tmdb_id: s
            for s in score(
                titles,
                m.labels,
                candidates,
                m.birth_year,
                child=m.allowed_certificates is not None,
                family_picks=m.family_picks,
            )
        }
        for m in members
    ]

    picks = []
    for tmdb_id in candidates:
        matches = [by_id[tmdb_id].score for by_id in scored]
        # The reason from whoever it suits best, said for them.
        best = sorted(range(len(members)), key=lambda n: -matches[n])
        reasons = [
            f"{members[n].name}: {scored[n][tmdb_id].reasons[0]}"
            for n in best
            if scored[n][tmdb_id].reasons
        ][:2]
        picks.append(Pick(tmdb_id, group_score(matches), matches, reasons))
    picks.sort(key=lambda p: -p.score)
    return picks
