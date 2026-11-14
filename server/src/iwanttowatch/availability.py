"""Where titles can be watched: streaming offers per region from TMDb (data by JustWatch).

Offers are stored per title and region and rechecked after three days. When a
recheck fails, the last known offers are kept and reported as stale.
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from iwanttowatch.db import utcnow
from iwanttowatch.models import Availability
from iwanttowatch.tmdb import TmdbClient, TmdbError, TmdbNotFound

log = logging.getLogger(__name__)

RECHECK_AFTER = timedelta(days=3)
CATALOGUE_CACHE = timedelta(days=7)
KINDS = ("flatrate", "free", "ads", "rent", "buy")
# Free and ad-supported offers need no subscription, so they count for everyone.
FREE = {"free", "ads"}
PARALLEL_REQUESTS = 8


def _by_priority(region: str) -> Any:
    def key(p: dict[str, Any]) -> tuple[int, str]:
        priority = (p.get("display_priorities") or {}).get(region, p.get("display_priority"))
        return (priority if priority is not None else 1000, p["provider_name"])

    return key


def provider_catalogue(tmdb: TmdbClient, region: str) -> list[dict[str, Any]]:
    """The region's movie streaming services, most prominent first."""
    found = tmdb.get("/watch/providers/movie", {"watch_region": region}, CATALOGUE_CACHE)
    return [
        {
            "provider_id": p["provider_id"],
            "name": p["provider_name"],
            "logo_path": p.get("logo_path"),
        }
        for p in sorted(found["results"], key=_by_priority(region))
    ]


def regions(tmdb: TmdbClient) -> list[dict[str, str]]:
    found = tmdb.get("/watch/providers/regions", None, CATALOGUE_CACHE)
    return sorted(
        ({"code": r["iso_3166_1"], "name": r["english_name"]} for r in found["results"]),
        key=lambda r: r["name"],
    )


def upsert_availability(
    session: Session,
    tmdb_id: int,
    region: str,
    result: tuple[list[dict[str, Any]], str | None] | None,
) -> None:
    """Persist fetched watch-provider offers for a title in a region."""
    if result is None:
        return
    offers, link = result
    values = {"offers": offers, "link": link, "checked_at": utcnow()}
    # An upsert, because a feed build and a page view may check the same title.
    session.execute(
        insert(Availability)
        .values(tmdb_id=tmdb_id, region=region, **values)
        .on_conflict_do_update(
            index_elements=[Availability.tmdb_id, Availability.region], set_=values
        )
    )


def availability(
    session: Session, tmdb: TmdbClient, tmdb_ids: list[int], region: str
) -> dict[int, Availability]:
    """Offers for each title in the region, checking TMDb for missing or stale ones."""
    known = {
        row.tmdb_id: row
        for row in session.scalars(
            select(Availability).where(
                Availability.tmdb_id.in_(tmdb_ids), Availability.region == region
            )
        )
    }
    due = [i for i in dict.fromkeys(tmdb_ids) if i not in known or is_stale(known[i])]
    with ThreadPoolExecutor(PARALLEL_REQUESTS) as pool:
        fetched = list(pool.map(lambda tmdb_id: _fetch(tmdb, tmdb_id, region), due))
    for tmdb_id, result in zip(due, fetched, strict=True):
        upsert_availability(session, tmdb_id, region, result)
    session.commit()
    return {
        row.tmdb_id: row
        for row in session.scalars(
            select(Availability)
            .where(Availability.tmdb_id.in_(tmdb_ids), Availability.region == region)
            .execution_options(populate_existing=True)
        )
    }


def _fetch(
    tmdb: TmdbClient, tmdb_id: int, region: str
) -> tuple[list[dict[str, Any]], str | None] | None:
    try:
        results = tmdb.get(f"/movie/{tmdb_id}/watch/providers")["results"]
    except TmdbNotFound:
        return [], None
    except TmdbError as error:
        log.warning("Couldn't check where %s streams: %s", tmdb_id, error)
        return None
    here = results.get(region) or {}
    offers = [
        {
            "provider_id": p["provider_id"],
            "name": p["provider_name"],
            "logo_path": p.get("logo_path"),
            "kind": kind,
        }
        for kind in KINDS
        for p in sorted(here.get(kind) or [], key=_by_priority(region))
    ]
    return offers, here.get("link")


def is_stale(row: Availability) -> bool:
    return utcnow() - row.checked_at.replace(tzinfo=UTC) >= RECHECK_AFTER


def watchable(offers: list[dict[str, Any]], subscriptions: list[int]) -> list[dict[str, Any]]:
    """The offers a user can play now: included in a service they pay for, or free."""
    playable: dict[int, dict[str, Any]] = {}
    for offer in offers:
        if offer["kind"] in FREE or (
            offer["kind"] == "flatrate" and offer["provider_id"] in subscriptions
        ):
            playable.setdefault(offer["provider_id"], offer)
    return list(playable.values())


def other_offers(offers: list[dict[str, Any]], subscriptions: list[int]) -> list[dict[str, Any]]:
    """The offers a user can't play now: services they don't pay for, renting, and buying.

    One entry per service and kind, in TMDb's order of prominence."""
    playable = {(o["provider_id"], o["kind"]) for o in watchable(offers, subscriptions)}
    others: dict[tuple[int, str], dict[str, Any]] = {}
    for offer in offers:
        key = (offer["provider_id"], offer["kind"])
        if key not in playable:
            others.setdefault(key, offer)
    return list(others.values())
