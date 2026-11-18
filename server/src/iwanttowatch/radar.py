"""Acquisition Radar & Theatrical Tracking.

Surfaces high-value movies to acquire or monitor in Radarr:
1. Missing from Streaming: unwatched high-match recommendations not available
   on any subscribed streaming platform or Jellyfin.
2. Now in Theaters: high-taste theatrical releases discovered from TMDb
   (with_release_type=2|3, now_playing) queued in Radarr monitored with
   minimumAvailability="released" so digital/physical releases are acquired
   automatically without pulling CAM/telesync rips.
"""

import json
import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from iwanttowatch.availability import availability, watchable
from iwanttowatch.catalog import ensure_titles
from iwanttowatch.children import library_owners
from iwanttowatch.db import utcnow
from iwanttowatch.feed import (
    DOCUMENTARY_GENRE_ID,
    hidden,
    is_non_movie,
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
    set_setting,
)
from iwanttowatch.radarr import (
    DEFAULT_MIN_AVAILABILITY,
    MIN_AVAILABILITY_SETTING,
    QUALITY_PROFILE_SETTING,
    ROOT_FOLDER_SETTING,
    RadarrClient,
    RadarrError,
    client_from_settings,
    queue_movie,
    resolve_root_folder,
)
from iwanttowatch.tmdb import TmdbClient, TmdbError

log = logging.getLogger(__name__)

NOW_PLAYING_CACHE = timedelta(hours=12)
THEATRICAL_DISCOVER_CACHE = timedelta(hours=12)

AUTO_DOWNLOAD_ENABLED_SETTING = "radar_auto_download_enabled"
AUTO_DOWNLOAD_MIN_MATCH_SETTING = "radar_auto_download_min_match"
AUTO_DOWNLOAD_MIN_FREE_GB_SETTING = "radar_auto_download_min_free_gb"
AUTO_DOWNLOAD_WEEKLY_LIMIT_SETTING = "radar_auto_download_weekly_limit"
AUTO_DOWNLOAD_MIN_VOTES_SETTING = "radar_auto_download_min_votes"
AUTO_DOWNLOAD_RELEASED_ONLY_SETTING = "radar_auto_download_released_only"
AUTO_DOWNLOAD_HISTORY_SETTING = "radar_auto_download_history"
AUTO_DOWNLOAD_LAST_RUN_SETTING = "radar_auto_download_last_run"

DEFAULT_AUTO_MIN_MATCH = 85
DEFAULT_AUTO_MIN_FREE_GB = 20
DEFAULT_AUTO_WEEKLY_LIMIT = 3
DEFAULT_AUTO_MIN_VOTES = 500
DEFAULT_AUTO_RELEASED_ONLY = True

BYTES_PER_GB = 1024**3
ESTIMATED_MOVIE_BYTES = 5 * BYTES_PER_GB
MAX_AUTO_DOWNLOAD_HISTORY = 100


def format_bytes(bytes_count: int) -> str:
    """Format byte count into human-readable string (e.g. '46.6 GB', '500.0 MB')."""
    if bytes_count < 1024:
        return f"{bytes_count} B"
    kb = bytes_count / 1024
    if kb < 1024:
        return f"{kb:.1f} KB"
    mb = kb / 1024
    if mb < 1024:
        return f"{mb:.1f} MB"
    gb = mb / 1024
    return f"{gb:.1f} GB"


def is_auto_download_enabled(session: Session) -> bool:
    """Whether the autonomous background downloader is enabled."""
    return get_setting(session, AUTO_DOWNLOAD_ENABLED_SETTING) == "true"


def get_auto_download_config(session: Session) -> dict[str, Any]:
    """Read background auto-downloader settings with safe defaults."""
    enabled = is_auto_download_enabled(session)

    raw_match = get_setting(session, AUTO_DOWNLOAD_MIN_MATCH_SETTING)
    min_match = (
        max(50, min(100, int(raw_match)))
        if raw_match and raw_match.isdigit()
        else DEFAULT_AUTO_MIN_MATCH
    )

    raw_free = get_setting(session, AUTO_DOWNLOAD_MIN_FREE_GB_SETTING)
    min_free_gb = (
        max(0, min(100000, int(raw_free)))
        if raw_free and raw_free.isdigit()
        else DEFAULT_AUTO_MIN_FREE_GB
    )

    raw_weekly = get_setting(session, AUTO_DOWNLOAD_WEEKLY_LIMIT_SETTING)
    weekly_limit = (
        max(1, min(100, int(raw_weekly)))
        if raw_weekly and raw_weekly.isdigit()
        else DEFAULT_AUTO_WEEKLY_LIMIT
    )

    raw_votes = get_setting(session, AUTO_DOWNLOAD_MIN_VOTES_SETTING)
    min_votes = (
        max(0, min(1000000, int(raw_votes)))
        if raw_votes and raw_votes.isdigit()
        else DEFAULT_AUTO_MIN_VOTES
    )

    raw_released = get_setting(session, AUTO_DOWNLOAD_RELEASED_ONLY_SETTING)
    released_only = DEFAULT_AUTO_RELEASED_ONLY if raw_released is None else raw_released == "true"

    return {
        "enabled": enabled,
        "min_match": min_match,
        "min_free_space_gb": min_free_gb,
        "weekly_limit": weekly_limit,
        "min_votes": min_votes,
        "released_only": released_only,
    }


def save_auto_download_config(
    session: Session,
    *,
    enabled: bool,
    min_match: int = DEFAULT_AUTO_MIN_MATCH,
    min_free_space_gb: int = DEFAULT_AUTO_MIN_FREE_GB,
    weekly_limit: int = DEFAULT_AUTO_WEEKLY_LIMIT,
    min_votes: int = DEFAULT_AUTO_MIN_VOTES,
    released_only: bool = DEFAULT_AUTO_RELEASED_ONLY,
) -> dict[str, Any]:
    """Persist background auto-downloader settings."""
    set_setting(session, AUTO_DOWNLOAD_ENABLED_SETTING, "true" if enabled else "false")
    set_setting(session, AUTO_DOWNLOAD_MIN_MATCH_SETTING, str(max(50, min(100, min_match))))
    set_setting(
        session,
        AUTO_DOWNLOAD_MIN_FREE_GB_SETTING,
        str(max(0, min(100000, min_free_space_gb))),
    )
    set_setting(session, AUTO_DOWNLOAD_WEEKLY_LIMIT_SETTING, str(max(1, min(100, weekly_limit))))
    set_setting(session, AUTO_DOWNLOAD_MIN_VOTES_SETTING, str(max(0, min(1000000, min_votes))))
    set_setting(session, AUTO_DOWNLOAD_RELEASED_ONLY_SETTING, "true" if released_only else "false")
    return get_auto_download_config(session)


def inspect_radarr_disk_space(
    session: Session,
    client: RadarrClient | None = None,
    min_free_space_gb: int | None = None,
) -> dict[str, Any]:
    """Inspect remaining HDD free space across Radarr root folders."""
    if client is None:
        client = client_from_settings(session, timeout=3.0)
    if min_free_space_gb is None:
        min_free_space_gb = get_auto_download_config(session)["min_free_space_gb"]

    threshold_bytes = max(0, min_free_space_gb) * BYTES_PER_GB
    default_root_folder = get_setting(session, ROOT_FOLDER_SETTING)

    folders: list[dict[str, Any]] = []
    free_values: list[int] = []

    if client is not None:
        try:
            raw_folders = client.root_folders()
            for rf in raw_folders:
                if not isinstance(rf, dict) or "path" not in rf:
                    continue
                path = str(rf["path"])
                raw_free = rf.get("freeSpace")
                free_bytes = int(raw_free) if isinstance(raw_free, (int, float)) else None
                free_gb = round(free_bytes / BYTES_PER_GB, 2) if free_bytes is not None else None
                free_fmt = format_bytes(free_bytes) if free_bytes is not None else None
                below = bool(
                    threshold_bytes > 0 and free_bytes is not None and free_bytes < threshold_bytes
                )
                if free_bytes is not None:
                    free_values.append(free_bytes)
                folders.append(
                    {
                        "path": path,
                        "free_space_bytes": free_bytes,
                        "free_space_gb": free_gb,
                        "free_space_formatted": free_fmt,
                        "below_threshold": below,
                    }
                )
            if not default_root_folder and folders:
                default_root_folder = folders[0]["path"]
        except RadarrError as err:
            log.warning("Could not fetch Radarr root folders for disk space inspection: %s", err)

    min_free_bytes = min(free_values) if free_values else None
    min_free_fmt = format_bytes(min_free_bytes) if min_free_bytes is not None else None

    has_sufficient_space = True
    if threshold_bytes > 0 and folders:
        # Sufficient if at least one root folder meets the free space floor
        known_folders = [f for f in folders if f["free_space_bytes"] is not None]
        if known_folders and all(f["below_threshold"] for f in known_folders):
            has_sufficient_space = False

    return {
        "folders": folders,
        "default_root_folder": default_root_folder,
        "min_free_space_bytes": min_free_bytes,
        "min_free_space_formatted": min_free_fmt,
        "has_sufficient_space": has_sufficient_space,
    }


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
    disk_info = inspect_radarr_disk_space(session, client=client)

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
            "root_folders": disk_info["folders"],
            "min_free_space_bytes": disk_info["min_free_space_bytes"],
            "min_free_space_formatted": disk_info["min_free_space_formatted"],
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
            "root_folders": disk_info["folders"],
            "min_free_space_bytes": disk_info["min_free_space_bytes"],
            "min_free_space_formatted": disk_info["min_free_space_formatted"],
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
        if not t or is_non_movie(t):
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
                "release_date": t.release_date,
                "status": t.status,
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
        "root_folders": disk_info["folders"],
        "min_free_space_bytes": disk_info["min_free_space_bytes"],
        "min_free_space_formatted": disk_info["min_free_space_formatted"],
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
        tid for tid in unique_theatrical_ids[:60] if tid in titles and not is_non_movie(titles[tid])
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
                "release_date": t.release_date,
                "status": t.status,
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


def _load_auto_download_history(session: Session) -> list[dict[str, Any]]:
    raw = get_setting(session, AUTO_DOWNLOAD_HISTORY_SETTING)
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [entry for entry in parsed if isinstance(entry, dict) and "tmdb_id" in entry]
    except Exception:
        pass
    return []


def _save_auto_download_history(session: Session, history: list[dict[str, Any]]) -> None:
    trimmed = history[:MAX_AUTO_DOWNLOAD_HISTORY]
    set_setting(session, AUTO_DOWNLOAD_HISTORY_SETTING, json.dumps(trimmed))


def _load_auto_download_last_run(session: Session) -> dict[str, Any] | None:
    raw = get_setting(session, AUTO_DOWNLOAD_LAST_RUN_SETTING)
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict) and "ran_at" in parsed:
            return parsed
    except Exception:
        pass
    return None


def _save_auto_download_last_run(session: Session, summary: dict[str, Any]) -> None:
    set_setting(session, AUTO_DOWNLOAD_LAST_RUN_SETTING, json.dumps(summary))


def _downloads_in_past_week(history: list[dict[str, Any]], now: datetime) -> int:
    cutoff = now - timedelta(days=7)
    count = 0
    for entry in history:
        raw_ts = entry.get("queued_at")
        if not isinstance(raw_ts, str):
            continue
        try:
            dt = datetime.fromisoformat(raw_ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            if dt >= cutoff:
                count += 1
        except ValueError:
            continue
    return count


def _is_released_title(title: Title, today: date) -> bool:
    """Whether a title is released and eligible for physical/digital acquisition."""
    if title.status and title.status.strip().lower() not in ("released",):
        return False
    if title.release_date is not None and title.release_date > today:
        return False
    return not (
        title.status is None
        and title.release_date is None
        and (title.year is None or title.year > today.year)
    )


def get_auto_download_status(
    session: Session,
    client: RadarrClient | None = None,
) -> dict[str, Any]:
    """Return auto-downloader configuration, remaining HDD space, weekly quota, and history."""
    if client is None:
        client = client_from_settings(session, timeout=3.0)
    radarr_configured = client is not None
    config = get_auto_download_config(session)
    disk_info = inspect_radarr_disk_space(
        session, client=client, min_free_space_gb=config["min_free_space_gb"]
    )
    history = _load_auto_download_history(session)
    now = utcnow()
    downloads_this_week = _downloads_in_past_week(history, now)
    remaining_quota = max(0, config["weekly_limit"] - downloads_this_week)
    last_run = _load_auto_download_last_run(session)

    return {
        "radarr_configured": radarr_configured,
        "config": config,
        "downloads_this_week": downloads_this_week,
        "remaining_weekly_quota": remaining_quota,
        "root_folders": disk_info["folders"],
        "has_sufficient_space": disk_info["has_sufficient_space"],
        "min_free_space_bytes": disk_info["min_free_space_bytes"],
        "min_free_space_formatted": disk_info["min_free_space_formatted"],
        "last_run": last_run,
        "history": history[:20],
    }


def run_auto_downloader(
    session: Session,
    tmdb: TmdbClient,
    user: User,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Autonomously queue top unstreamable recommendations in Radarr with safety guardrails.

    Safeguards:
    - Configurable minimum match percentage (default >= 85%)
    - Remaining HDD free space check on the target Radarr root folder (default >= 20 GB)
    - Weekly download cap (default 3 movies per rolling 7-day window)
    - Minimum audience vote count floor (default >= 500 votes across IMDb / TMDb)
    - Released-only filter (status == Released, release_date <= today, queued with
      minimumAvailability="released" to avoid CAM/telesync rips)
    """
    config = get_auto_download_config(session)
    if not force and not config["enabled"]:
        status = get_auto_download_status(session)
        return {
            "queued_count": 0,
            "queued_items": [],
            "skipped_low_space": 0,
            "skipped_weekly_cap": 0,
            "skipped_votes": 0,
            "skipped_unreleased": 0,
            "detail": "Auto-downloader is disabled",
            "status": status,
        }

    client = client_from_settings(session)
    if client is None:
        if force:
            raise RadarrError("Radarr is not configured in Settings")
        status = get_auto_download_status(session, client=None)
        return {
            "queued_count": 0,
            "queued_items": [],
            "skipped_low_space": 0,
            "skipped_weekly_cap": 0,
            "skipped_votes": 0,
            "skipped_unreleased": 0,
            "detail": "Radarr is not configured",
            "status": status,
        }

    disk_info = inspect_radarr_disk_space(
        session, client=client, min_free_space_gb=config["min_free_space_gb"]
    )
    folder_free_map: dict[str, int] = {
        str(f["path"]).rstrip("/"): int(f["free_space_bytes"])
        for f in disk_info["folders"]
        if f.get("free_space_bytes") is not None
    }
    default_root_folder = disk_info["default_root_folder"] or ""

    profile_id_str = get_setting(session, QUALITY_PROFILE_SETTING)
    profile_id = int(profile_id_str) if profile_id_str and profile_id_str.isdigit() else None
    if profile_id is None:
        try:
            profiles = client.quality_profiles()
            if profiles:
                profile_id = profiles[0]["id"]
        except RadarrError as err:
            log.warning("Could not fetch Radarr quality profiles for auto-downloader: %s", err)

    min_avail = (
        "released"
        if config["released_only"]
        else (get_setting(session, MIN_AVAILABILITY_SETTING) or DEFAULT_MIN_AVAILABILITY)
    )

    history = _load_auto_download_history(session)
    previously_queued_ids = {int(entry["tmdb_id"]) for entry in history if "tmdb_id" in entry}
    now = utcnow()
    downloads_this_week = _downloads_in_past_week(history, now)
    remaining_quota = max(0, config["weekly_limit"] - downloads_this_week)

    missing = inspect_missing_candidates(
        session=session,
        tmdb=tmdb,
        user=user,
        min_match=config["min_match"],
    )
    candidates = [
        item
        for item in missing["items"]
        if item["radarr_status"] == "to_request"
        and int(item["tmdb_id"]) not in previously_queued_ids
    ]

    candidate_ids = [int(item["tmdb_id"]) for item in candidates]
    titles = (
        {
            t.tmdb_id: t
            for t in session.scalars(select(Title).where(Title.tmdb_id.in_(candidate_ids)))
        }
        if candidate_ids
        else {}
    )

    today = date.today()
    min_free_bytes = max(0, config["min_free_space_gb"]) * BYTES_PER_GB
    min_votes = max(0, config["min_votes"])

    queued_items: list[dict[str, Any]] = []
    skipped_low_space = 0
    skipped_weekly_cap = 0
    skipped_votes = 0
    skipped_unreleased = 0

    for item in candidates:
        tmdb_id = int(item["tmdb_id"])
        t = titles.get(tmdb_id)
        if not t:
            continue

        # 1. Physical/digital release availability filter
        if config["released_only"] and not _is_released_title(t, today):
            skipped_unreleased += 1
            continue

        # 2. Minimum audience vote floor
        effective_votes = max(t.imdb_votes or 0, t.vote_count or 0)
        if min_votes > 0 and effective_votes < min_votes:
            skipped_votes += 1
            continue

        # 3. Weekly download cap
        if len(queued_items) >= remaining_quota:
            skipped_weekly_cap += 1
            continue

        # 4. Remaining HDD space check on target root folder
        target_folder = (
            resolve_root_folder(session, t.original_language, default_root_folder)
            if default_root_folder
            else ""
        )
        norm_target = target_folder.rstrip("/")
        matched_folder_key: str | None = None
        avail_bytes: int | None = None
        if norm_target and norm_target in folder_free_map:
            matched_folder_key = norm_target
            avail_bytes = folder_free_map[norm_target]
        elif folder_free_map:
            matched_folder_key = min(folder_free_map, key=lambda k: folder_free_map[k])
            avail_bytes = folder_free_map[matched_folder_key]

        if min_free_bytes > 0 and avail_bytes is not None and avail_bytes < min_free_bytes:
            skipped_low_space += 1
            continue

        # 5. Queue in Radarr
        try:
            queue_movie(
                session=session,
                tmdb_id=tmdb_id,
                title=t.title,
                year=t.year,
                language=t.original_language,
                client=client,
                profile_id=profile_id,
                default_root_folder=default_root_folder or None,
                min_avail=min_avail,
                search=True,
            )
            entry = {
                "tmdb_id": tmdb_id,
                "title": t.title,
                "year": t.year,
                "match_pct": int(item["match_pct"]),
                "root_folder": target_folder or None,
                "queued_at": now.isoformat(),
            }
            queued_items.append(entry)
            previously_queued_ids.add(tmdb_id)
            if matched_folder_key is not None:
                folder_free_map[matched_folder_key] = max(
                    0, folder_free_map[matched_folder_key] - ESTIMATED_MOVIE_BYTES
                )
        except RadarrError as err:
            log.warning("Auto-downloader failed to queue %s (%s): %s", t.title, tmdb_id, err)

    if queued_items:
        history = queued_items + history
        _save_auto_download_history(session, history)

    parts: list[str] = []
    if queued_items:
        parts.append(f"Queued {len(queued_items)} movie(s)")
    else:
        parts.append("No new movies queued")
    if skipped_low_space:
        parts.append(f"{skipped_low_space} skipped (low disk space)")
    if skipped_weekly_cap:
        parts.append(f"{skipped_weekly_cap} skipped (weekly cap)")
    if skipped_votes:
        parts.append(f"{skipped_votes} skipped (below vote floor)")
    if skipped_unreleased:
        parts.append(f"{skipped_unreleased} skipped (unreleased)")
    detail = " · ".join(parts)

    last_run_summary = {
        "ran_at": now.isoformat(),
        "queued_count": len(queued_items),
        "skipped_low_space": skipped_low_space,
        "skipped_weekly_cap": skipped_weekly_cap,
        "skipped_votes": skipped_votes,
        "skipped_unreleased": skipped_unreleased,
        "detail": detail,
    }
    _save_auto_download_last_run(session, last_run_summary)
    session.commit()

    updated_status = get_auto_download_status(session, client=client)
    return {
        "queued_count": len(queued_items),
        "queued_items": queued_items,
        "skipped_low_space": skipped_low_space,
        "skipped_weekly_cap": skipped_weekly_cap,
        "skipped_votes": skipped_votes,
        "skipped_unreleased": skipped_unreleased,
        "detail": detail,
        "status": updated_status,
    }
