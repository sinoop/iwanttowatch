"""Acquisition Radar & Theatrical Tracking.

Surfaces high-value movies to acquire or monitor in Radarr:
1. Missing from Streaming: unwatched high-match recommendations not available
   on any subscribed streaming platform or Jellyfin.
2. Now in Theaters: high-taste theatrical releases discovered from TMDb
   (with_release_type=2|3, now_playing) queued in Radarr monitored with
   minimumAvailability="released" so digital/physical releases are acquired
   automatically without pulling CAM/telesync rips.
"""

import logging
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from iwanttowatch.availability import availability, watchable
from iwanttowatch.catalog import ensure_titles
from iwanttowatch.children import library_owners
from iwanttowatch.feed import (
    DOCUMENTARY_GENRE_ID,
    hidden,
    is_documentary,
    score_films,
    seen,
    shortlisted,
)
from iwanttowatch.models import (
    LibraryItem,
    Recommendation,
    Title,
    User,
    get_setting,
)
from iwanttowatch.radarr import (
    DEFAULT_MIN_AVAILABILITY,
    MIN_AVAILABILITY_SETTING,
    QUALITY_PROFILE_SETTING,
    ROOT_FOLDER_SETTING,
    RadarrError,
    client_from_settings,
    queue_movie,
)
from iwanttowatch.tmdb import TmdbClient, TmdbError

log = logging.getLogger(__name__)

NOW_PLAYING_CACHE = timedelta(hours=12)
THEATRICAL_DISCOVER_CACHE = timedelta(hours=12)


def inspect_missing_candidates(
    session: Session,
    tmdb: TmdbClient,
    user: User,
    min_match: int = 70,
    scope: str = "user",
) -> dict[str, Any]:
    """Inspect unwatched, high-match recommendations not streamable on subscriptions or Jellyfin."""
    client = client_from_settings(session, timeout=3.0)
    radarr_configured = client is not None

    owners = library_owners(session, user)
    in_library = set(
        session.scalars(select(LibraryItem.tmdb_id).where(LibraryItem.user_id.in_(owners)))
    )
    user_seen = seen(session, user.id)
    user_hidden = hidden(session, user.id)

    # Gather high-match recommendations
    min_score = min_match / 100.0
    rec_rows = session.execute(
        select(Recommendation.tmdb_id, Recommendation.score, Recommendation.reasons)
        .where(Recommendation.user_id == user.id, Recommendation.score >= min_score)
        .order_by(Recommendation.score.desc())
    ).all()

    scores_by_id: dict[int, float] = {r[0]: float(r[1]) for r in rec_rows}
    reasons_by_id: dict[int, list[str]] = {r[0]: list(r[2]) for r in rec_rows}

    # Also check user's shortlists
    shortlist_ids = shortlisted(session, user.id)
    unscored_shortlist = [
        sid
        for sid in shortlist_ids
        if sid not in scores_by_id and sid not in user_seen and sid not in in_library
    ]
    if unscored_shortlist:
        try:
            scored = score_films(session, user, unscored_shortlist)
            for s in scored:
                if s.score >= min_score:
                    scores_by_id[s.tmdb_id] = s.score
                    reasons_by_id[s.tmdb_id] = s.reasons
        except Exception as err:
            log.warning("Could not score shortlist items for radar: %s", err)

    candidate_ids = [
        cid
        for cid in scores_by_id
        if cid not in user_seen and cid not in in_library and cid not in user_hidden
    ]

    if not candidate_ids:
        return {
            "radarr_configured": radarr_configured,
            "scope": scope,
            "min_match": min_match,
            "total_missing": 0,
            "to_request_count": 0,
            "downloading_count": 0,
            "downloaded_count": 0,
            "items": [],
        }

    # Filter out streamable titles on user's active streaming subscriptions
    avail_rows = availability(session, tmdb, candidate_ids, user.region)
    unstreamable_ids: list[int] = []
    for cid in candidate_ids:
        row = avail_rows.get(cid)
        offers = watchable(row.offers, user.subscriptions) if row else []
        if len(offers) == 0:
            unstreamable_ids.append(cid)

    if not unstreamable_ids:
        return {
            "radarr_configured": radarr_configured,
            "scope": scope,
            "min_match": min_match,
            "total_missing": 0,
            "to_request_count": 0,
            "downloading_count": 0,
            "downloaded_count": 0,
            "items": [],
        }

    titles = {
        t.tmdb_id: t
        for t in session.scalars(select(Title).where(Title.tmdb_id.in_(unstreamable_ids)))
    }
    missing_title_ids = [cid for cid in unstreamable_ids if cid not in titles]
    if missing_title_ids:
        fetched = ensure_titles(session, tmdb, missing_title_ids)
        titles.update(fetched)

    # Radarr inspection
    radarr_movies: dict[int, dict[str, Any]] = {}
    if client is not None:
        try:
            radarr_movies = {
                m["tmdbId"]: m
                for m in client.get_all_movies()
                if isinstance(m, dict) and "tmdbId" in m
            }
        except RadarrError as err:
            log.warning("Could not list Radarr movies during radar inspection: %s", err)

    items: list[dict[str, Any]] = []
    to_request_count = 0
    downloading_count = 0
    downloaded_count = 0

    # Sort candidates by match score descending
    sorted_ids = sorted(unstreamable_ids, key=lambda i: scores_by_id.get(i, 0.0), reverse=True)

    for tmdb_id in sorted_ids:
        t = titles.get(tmdb_id)
        if not t or is_documentary(t):
            continue

        match_pct = round(scores_by_id.get(tmdb_id, 0.0) * 100)
        reasons = reasons_by_id.get(tmdb_id, [])

        imdb_dict = None
        if t.imdb_id and t.imdb_rating is not None and t.imdb_votes:
            imdb_dict = {"id": t.imdb_id, "rating": t.imdb_rating, "votes": t.imdb_votes}

        rm = radarr_movies.get(tmdb_id)
        radarr_movie_id = rm.get("id") if rm else None
        slug = rm.get("titleSlug") if rm else None
        radarr_url = f"{client.base_url}/movie/{slug}" if client and slug else None

        if rm:
            if rm.get("hasFile"):
                radarr_status = "downloaded"
                downloaded_count += 1
            elif rm.get("monitored"):
                radarr_status = "downloading"
                downloading_count += 1
            else:
                radarr_status = "to_request"
                to_request_count += 1
        else:
            radarr_status = "to_request"
            to_request_count += 1

        items.append(
            {
                "tmdb_id": tmdb_id,
                "title": t.title,
                "original_title": t.original_title,
                "original_language": t.original_language,
                "year": t.year,
                "runtime": t.runtime,
                "poster_path": t.poster_path,
                "genres": t.genres,
                "match_pct": match_pct,
                "reasons": reasons,
                "imdb": imdb_dict,
                "radarr_status": radarr_status,
                "radarr_movie_id": radarr_movie_id,
                "radarr_url": radarr_url,
                "is_theatrical": False,
                "theatrical_release_date": t.release_date.isoformat() if t.release_date else None,
            }
        )

    return {
        "radarr_configured": radarr_configured,
        "scope": scope,
        "min_match": min_match,
        "total_missing": len(items),
        "to_request_count": to_request_count,
        "downloading_count": downloading_count,
        "downloaded_count": downloaded_count,
        "items": items,
    }


def inspect_theatrical_candidates(
    session: Session,
    tmdb: TmdbClient,
    user: User,
    region: str | None = None,
    min_match: int = 50,
) -> dict[str, Any]:
    """Discover high-taste theatrical releases using TMDb and check Radarr monitoring status."""
    client = client_from_settings(session, timeout=3.0)
    radarr_configured = client is not None
    target_region = (region or user.region or "IN").upper()

    owners = library_owners(session, user)
    in_library = set(
        session.scalars(select(LibraryItem.tmdb_id).where(LibraryItem.user_id.in_(owners)))
    )
    user_seen = seen(session, user.id)

    theatrical_ids: list[int] = []

    # 1. Fetch from /movie/now_playing
    try:
        now_playing_data = tmdb.get(
            "/movie/now_playing",
            {"region": target_region, "page": 1},
            cache_for=NOW_PLAYING_CACHE,
        )
        for item in now_playing_data.get("results", []):
            if "id" in item:
                theatrical_ids.append(int(item["id"]))
    except TmdbError as err:
        log.warning("Could not fetch TMDb now_playing for %s: %s", target_region, err)

    # 2. Discover theatrical releases with_release_type=2|3
    today = date.today()
    start_date = (today - timedelta(days=90)).isoformat()
    end_date = (today + timedelta(days=21)).isoformat()
    try:
        discover_data = tmdb.get(
            "/discover/movie",
            {
                "region": target_region,
                "with_release_type": "2|3",
                "primary_release_date.gte": start_date,
                "primary_release_date.lte": end_date,
                "sort_by": "popularity.desc",
                "without_genres": str(DOCUMENTARY_GENRE_ID),
                "include_adult": "false",
                "page": 1,
            },
            cache_for=THEATRICAL_DISCOVER_CACHE,
        )
        for item in discover_data.get("results", []):
            if "id" in item:
                theatrical_ids.append(int(item["id"]))
    except TmdbError as err:
        log.warning("Could not fetch TMDb theatrical discover for %s: %s", target_region, err)

    unique_theatrical_ids = [
        tid
        for tid in dict.fromkeys(theatrical_ids)
        if tid not in user_seen and tid not in in_library
    ]

    if not unique_theatrical_ids:
        return {
            "radarr_configured": radarr_configured,
            "region": target_region,
            "total_theatrical": 0,
            "to_track_count": 0,
            "tracking_count": 0,
            "downloaded_count": 0,
            "items": [],
        }

    # Ensure titles in catalog
    titles = ensure_titles(session, tmdb, unique_theatrical_ids[:60])
    valid_ids = [
        tid
        for tid in unique_theatrical_ids[:60]
        if tid in titles and not is_documentary(titles[tid])
    ]

    # Score candidates against user's taste model
    scores_by_id: dict[int, float] = {}
    reasons_by_id: dict[int, list[str]] = {}
    if valid_ids:
        try:
            scored = score_films(session, user, valid_ids)
            for s in scored:
                scores_by_id[s.tmdb_id] = s.score
                reasons_by_id[s.tmdb_id] = s.reasons
        except Exception as err:
            log.warning("Could not score theatrical candidates: %s", err)

    # Filter to min_match or top matching titles
    min_score = min_match / 100.0
    filtered_ids = [tid for tid in valid_ids if scores_by_id.get(tid, 0.0) >= min_score]
    if not filtered_ids and valid_ids:
        # If none reached threshold, show top 10 highest-matching theatrical releases
        filtered_ids = sorted(valid_ids, key=lambda i: scores_by_id.get(i, 0.0), reverse=True)[:10]

    # Sort descending by taste score
    filtered_ids.sort(key=lambda i: scores_by_id.get(i, 0.0), reverse=True)

    # Radarr inspection
    radarr_movies: dict[int, dict[str, Any]] = {}
    if client is not None:
        try:
            radarr_movies = {
                m["tmdbId"]: m
                for m in client.get_all_movies()
                if isinstance(m, dict) and "tmdbId" in m
            }
        except RadarrError as err:
            log.warning("Could not list Radarr movies during theatrical radar inspection: %s", err)

    items: list[dict[str, Any]] = []
    to_track_count = 0
    tracking_count = 0
    downloaded_count = 0

    for tmdb_id in filtered_ids:
        t = titles.get(tmdb_id)
        if not t:
            continue

        match_pct = round(scores_by_id.get(tmdb_id, 0.0) * 100)
        reasons = reasons_by_id.get(tmdb_id, [])

        imdb_dict = None
        if t.imdb_id and t.imdb_rating is not None and t.imdb_votes:
            imdb_dict = {"id": t.imdb_id, "rating": t.imdb_rating, "votes": t.imdb_votes}

        rm = radarr_movies.get(tmdb_id)
        radarr_movie_id = rm.get("id") if rm else None
        slug = rm.get("titleSlug") if rm else None
        radarr_url = f"{client.base_url}/movie/{slug}" if client and slug else None

        if rm:
            if rm.get("hasFile"):
                radarr_status = "downloaded"
                downloaded_count += 1
            elif rm.get("monitored"):
                radarr_status = "tracking"
                tracking_count += 1
            else:
                radarr_status = "to_track"
                to_track_count += 1
        else:
            radarr_status = "to_track"
            to_track_count += 1

        items.append(
            {
                "tmdb_id": tmdb_id,
                "title": t.title,
                "original_title": t.original_title,
                "original_language": t.original_language,
                "year": t.year,
                "runtime": t.runtime,
                "poster_path": t.poster_path,
                "genres": t.genres,
                "match_pct": match_pct,
                "reasons": reasons,
                "imdb": imdb_dict,
                "radarr_status": radarr_status,
                "radarr_movie_id": radarr_movie_id,
                "radarr_url": radarr_url,
                "is_theatrical": True,
                "theatrical_release_date": t.release_date.isoformat() if t.release_date else None,
            }
        )

    return {
        "radarr_configured": radarr_configured,
        "region": target_region,
        "total_theatrical": len(items),
        "to_track_count": to_track_count,
        "tracking_count": tracking_count,
        "downloaded_count": downloaded_count,
        "items": items,
    }


def queue_radar_candidates(
    session: Session,
    user: User,
    tmdb_ids: list[int],
    minimum_availability: str | None = None,
) -> dict[str, Any]:
    """Batch queue or track radar candidate titles in Radarr.

    For theatrical early tracking, default minimum_availability="released" ensures Radarr
    only downloads official physical/digital releases and ignores CAM/telesync rips.
    """
    client = client_from_settings(session)
    if client is None:
        raise RadarrError("Radarr is not configured in Settings")

    if not tmdb_ids:
        return {"success": True, "requested_count": 0, "failed_count": 0, "items": []}

    titles = {
        t.tmdb_id: t for t in session.scalars(select(Title).where(Title.tmdb_id.in_(tmdb_ids)))
    }

    profile_id_str = get_setting(session, QUALITY_PROFILE_SETTING)
    profile_id = int(profile_id_str) if profile_id_str and profile_id_str.isdigit() else None
    if profile_id is None:
        profiles = client.quality_profiles()
        if profiles:
            profile_id = profiles[0]["id"]

    default_root_folder = get_setting(session, ROOT_FOLDER_SETTING)
    if not default_root_folder:
        root_folders = client.root_folders()
        if root_folders:
            default_root_folder = root_folders[0]["path"]

    min_avail = (
        minimum_availability
        or get_setting(session, MIN_AVAILABILITY_SETTING)
        or DEFAULT_MIN_AVAILABILITY
    )

    results: list[dict[str, Any]] = []
    requested_count = 0
    failed_count = 0

    for tmdb_id in dict.fromkeys(tmdb_ids):
        t = titles.get(tmdb_id)
        title_str = t.title if t else f"Movie {tmdb_id}"
        year = t.year if t else None
        lang = t.original_language if t else None

        try:
            queue_movie(
                session=session,
                tmdb_id=tmdb_id,
                title=title_str,
                year=year,
                language=lang,
                client=client,
                profile_id=profile_id,
                default_root_folder=default_root_folder,
                min_avail=min_avail,
                search=True,
            )
            requested_count += 1
            results.append(
                {
                    "tmdb_id": tmdb_id,
                    "title": title_str,
                    "status": "queued",
                    "detail": f"Queued in Radarr (availability: {min_avail})",
                }
            )
        except RadarrError as err:
            failed_count += 1
            log.warning("Failed to queue radar title %s (%s): %s", title_str, tmdb_id, err)
            results.append(
                {
                    "tmdb_id": tmdb_id,
                    "title": title_str,
                    "status": "failed",
                    "detail": str(err),
                }
            )

    return {
        "success": failed_count == 0,
        "requested_count": requested_count,
        "failed_count": failed_count,
        "items": results,
    }
