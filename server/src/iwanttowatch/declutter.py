"""Declutter Assistant: taste-driven library pruning and storage reclamation.

Analyzes Jellyfin library items and Radarr tracked movies to surface candidates for
safe deletion based on:
1. Watched & Disliked: explicit ratings <= 4.0, disliked reactions, or thumbs down.
2. Abandoned Play: playback started but abandoned < 20% completion over 30 days ago.
3. Cold Hoard / Low Taste Match: unwatched in library with predicted match < 35%.
4. Streaming Redundancy: watched and currently streamable on active subscriptions.
5. Unplayable in Jellyfin: present in Radarr with non-zero disk occupied, but missing from
   Jellyfin library.

Includes Household Protection Guardrails to avoid pruning films shortlisted, favorited,
or highly matched for other household members.
"""

import json
import logging
import re
from collections import defaultdict
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from iwanttowatch.availability import availability, watchable
from iwanttowatch.catalog import clean_media_title_and_year, normalise_title
from iwanttowatch.children import library_owners
from iwanttowatch.jellyfin import (
    STATUS_KEY as JELLYFIN_STATUS,
)
from iwanttowatch.jellyfin import (
    _merge_history,
)
from iwanttowatch.jellyfin import (
    client_from_settings as jellyfin_client_from_settings,
)
from iwanttowatch.models import (
    ConnectorStatus,
    Feedback,
    GroupShortlistItem,
    LibraryItem,
    Recommendation,
    ShortlistItem,
    Title,
    User,
    UserTitle,
    get_setting,
    set_setting,
)
from iwanttowatch.radarr import RadarrError, client_from_settings

log = logging.getLogger(__name__)

DECLUTTER_IGNORED_SETTING = "declutter_ignored_tmdb_ids"
DECLUTTER_CATEGORIES = (
    "low_quality",
    "disliked",
    "abandoned",
    "redundant_streamable",
    "low_match",
    "low_interest",
    "unplayable",
)


def format_bytes(bytes_count: int) -> str:
    """Format byte count into human-readable string (e.g. '14.2 GB', '450 MB')."""
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


def is_low_quality_movie(radarr_movie: dict[str, Any] | None) -> tuple[bool, list[str]]:
    """Detect if a Radarr movie is low quality (CAM/telesync print or sub-720p resolution)."""
    if not radarr_movie:
        return False, []

    movie_file = radarr_movie.get("movieFile")
    quality_wrapper = (
        (movie_file.get("quality") if isinstance(movie_file, dict) else None)
        or radarr_movie.get("quality")
        or {}
    )
    quality_dict = quality_wrapper.get("quality") or {} if isinstance(quality_wrapper, dict) else {}
    quality_name = str(quality_dict.get("name", "")).strip()
    quality_source = str(quality_dict.get("source", "")).lower().strip()
    resolution_val = quality_dict.get("resolution")

    media_info = movie_file.get("mediaInfo") if isinstance(movie_file, dict) else None
    height = media_info.get("height") if isinstance(media_info, dict) else None

    path_str = ""
    if isinstance(movie_file, dict):
        path_str += (
            " "
            + str(movie_file.get("relativePath", ""))
            + " "
            + str(movie_file.get("sceneName", ""))
        )
    path_str += " " + str(radarr_movie.get("path", "")) + " " + str(radarr_movie.get("title", ""))
    path_upper = path_str.upper()

    reasons: list[str] = []

    # 1. CAM / Telesync / Screener prints
    cam_sources = {"cam", "telesync", "telecine", "workprint", "screener"}
    is_cam = False
    if (
        quality_source in cam_sources
        or any(
            tok in quality_name.upper()
            for tok in ("CAM", "TELESYNC", "TELECINE", "WORKPRINT", "SCREENER", "SCR")
        )
        or re.search(
            r"\b(HDCAM|CAMRIP|CAM-RIP|TELESYNC|TELE-SYNC|\.TS\.|-TS\b|TELECINE|DVDSCR|DVD-SCR|SCREENER|WORKPRINT)\b",
            path_upper,
        )
    ):
        is_cam = True

    if is_cam:
        tag = quality_name or "CAM"
        reasons.append(f"Low quality CAM release: {tag} print")

    # 2. Sub-720p resolution (<720p)
    is_sub_720 = False
    sub_res_str = ""
    if isinstance(resolution_val, (int, float)) and 0 < resolution_val < 720:
        is_sub_720 = True
        sub_res_str = f"{int(resolution_val)}p"
    elif isinstance(height, (int, float)) and 0 < height < 700:
        is_sub_720 = True
        sub_res_str = f"{int(height)}p"
    elif any(sd in quality_name.upper() for sd in ("SDTV", "DVD", "480P", "576P", "360P")):
        is_sub_720 = True
        sub_res_str = quality_name or "SD"
    elif re.search(r"\b(480P|576P|360P|DVDRIP|DVD-RIP|WEBDL-480P)\b", path_upper):
        is_sub_720 = True
        sub_res_str = "Sub-720p"

    if is_sub_720 and not is_cam:
        reasons.append(f"Sub-HD resolution: {sub_res_str} (<720p)")
    elif is_sub_720 and is_cam:
        reasons.append(f"Sub-HD resolution: {sub_res_str}")

    return (is_cam or is_sub_720), reasons


def get_ignored_tmdb_ids(session: Session) -> set[int]:
    """TMDb IDs the admin marked to ignore/keep in library."""
    raw = get_setting(session, DECLUTTER_IGNORED_SETTING)
    if not raw:
        return set()
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return {int(x) for x in data if isinstance(x, (int, str)) and str(x).isdigit()}
    except Exception:
        pass
    return set()


def set_ignored_tmdb_id(session: Session, tmdb_id: int, ignored: bool = True) -> set[int]:
    """Add or remove a TMDb ID from the declutter ignore list."""
    current = get_ignored_tmdb_ids(session)
    if ignored:
        current.add(tmdb_id)
    else:
        current.discard(tmdb_id)
    set_setting(session, DECLUTTER_IGNORED_SETTING, json.dumps(sorted(current)))
    session.commit()
    return current


def inspect_declutter_candidates(
    session: Session,
    tmdb: Any,
    user: User,
    category_filter: str | None = None,
    categories_mode: str = "any",
    include_ignored: bool = False,
    whitelist_filter: str | None = None,
) -> dict[str, Any]:
    """Inspect library and Radarr to identify prune candidates with household safety guards."""
    client = client_from_settings(session, timeout=3.0)
    radarr_configured = client is not None
    radarr_movies: dict[int, dict[str, Any]] = {}

    if client is not None:
        try:
            for m in client.get_all_movies():
                if isinstance(m, dict) and "tmdbId" in m:
                    radarr_movies[m["tmdbId"]] = m
        except RadarrError as err:
            log.warning("Could not list Radarr movies during declutter inspection: %s", err)

    if user.is_admin or user.is_child:
        owners = list(session.scalars(select(User.id).where(User.is_child.is_(False))))
    else:
        owners = library_owners(session, user)
    lib_items = list(
        session.scalars(select(LibraryItem).where(LibraryItem.user_id.in_(owners))).all()
    )
    lib_by_tmdb: dict[int, list[LibraryItem]] = defaultdict(list)
    unmatched_lib_items: list[LibraryItem] = []
    for li in lib_items:
        if li.tmdb_id:
            lib_by_tmdb[li.tmdb_id].append(li)
        else:
            unmatched_lib_items.append(li)

    db_updated = False
    if unmatched_lib_items and radarr_movies:
        radarr_by_title_year: dict[tuple[str, int], int] = {}
        radarr_by_title: dict[str, list[tuple[int, int | None]]] = defaultdict(list)
        for tid, rm in radarr_movies.items():
            rm_year = rm.get("year")
            titles_to_index = {rm.get("title"), rm.get("cleanTitle"), rm.get("originalTitle")}
            for t_raw in titles_to_index:
                if not t_raw:
                    continue
                c_title, _ = clean_media_title_and_year(str(t_raw))
                norm_t = normalise_title(c_title)
                if not norm_t:
                    continue
                if rm_year:
                    radarr_by_title_year[(norm_t, rm_year)] = tid
                radarr_by_title[norm_t].append((tid, rm_year))

        still_unmatched: list[LibraryItem] = []
        for li in unmatched_lib_items:
            clean_name, extracted_year = clean_media_title_and_year(li.name)
            norm_name = normalise_title(clean_name)
            li_year = li.year or extracted_year
            matched_tid: int | None = None

            if norm_name:
                if li_year:
                    for y in (li_year, li_year - 1, li_year + 1):
                        if (norm_name, y) in radarr_by_title_year:
                            matched_tid = radarr_by_title_year[(norm_name, y)]
                            break
                if matched_tid is None and norm_name in radarr_by_title:
                    candidates = radarr_by_title[norm_name]
                    if li_year:
                        year_matches = [
                            cid
                            for cid, cy in candidates
                            if cy is not None and abs(cy - li_year) <= 1
                        ]
                        if len(year_matches) == 1:
                            matched_tid = year_matches[0]
                    elif len(candidates) == 1:
                        matched_tid = candidates[0][0]

            if matched_tid is not None:
                li.tmdb_id = matched_tid
                lib_by_tmdb[matched_tid].append(li)
                db_updated = True
                if li.played or li.favorite:
                    _merge_history(session, tmdb, li.user_id, matched_tid)
            else:
                still_unmatched.append(li)
        unmatched_lib_items = still_unmatched

    jellyfin_client = jellyfin_client_from_settings(session)
    jellyfin_configured = jellyfin_client is not None
    jellyfin_synced = False
    status_row = session.get(ConnectorStatus, JELLYFIN_STATUS)
    if status_row and status_row.synced_at is not None:
        jellyfin_synced = True
    has_jellyfin_data = jellyfin_configured and (len(lib_items) > 0 or jellyfin_synced)

    all_candidate_ids = set(lib_by_tmdb.keys())
    for tmdb_id, rm in radarr_movies.items():
        if rm.get("hasFile") or rm.get("monitored"):
            all_candidate_ids.add(tmdb_id)

    ignored_ids = get_ignored_tmdb_ids(session)
    ignored_candidates = all_candidate_ids & ignored_ids

    def _size_of(tid: int) -> int:
        rm = radarr_movies.get(tid)
        if rm and rm.get("sizeOnDisk"):
            return int(rm["sizeOnDisk"])
        items = lib_by_tmdb.get(tid, [])
        return sum(getattr(li, "size_bytes", 0) or 0 for li in items)

    ignored_bytes = sum(_size_of(tid) for tid in ignored_candidates)

    effective_whitelist = whitelist_filter
    if category_filter == "whitelisted":
        effective_whitelist = "only"
        category_filter = "all"
    elif effective_whitelist is None:
        effective_whitelist = "all" if include_ignored else "hide"

    target_categories: set[str] = set()
    if category_filter and category_filter not in ("all", "whitelisted"):
        target_categories = {c.strip() for c in category_filter.split(",") if c.strip()}

    if effective_whitelist == "only":
        candidate_ids = set(ignored_candidates)
    elif effective_whitelist == "all":
        candidate_ids = set(all_candidate_ids)
    else:
        candidate_ids = all_candidate_ids - ignored_ids

    if not candidate_ids:
        summary = {
            cat: {"count": 0, "bytes": 0, "formatted": "0 B"} for cat in DECLUTTER_CATEGORIES
        }
        summary["whitelisted"] = {
            "count": len(ignored_candidates),
            "bytes": ignored_bytes,
            "formatted": format_bytes(ignored_bytes),
        }
        return {
            "radarr_configured": radarr_configured,
            "jellyfin_configured": jellyfin_configured,
            "total_candidates": 0,
            "reclaimable_bytes": 0,
            "reclaimable_formatted": "0 B",
            "protected_count": 0,
            "categories_summary": summary,
            "items": [],
        }

    titles = {
        t.tmdb_id: t for t in session.scalars(select(Title).where(Title.tmdb_id.in_(candidate_ids)))
    }
    all_users = session.scalars(select(User)).all()
    user_map = {u.id: u for u in all_users}

    user_titles = session.scalars(
        select(UserTitle).where(UserTitle.tmdb_id.in_(candidate_ids))
    ).all()
    ut_by_tmdb_and_user: dict[tuple[int, int], list[UserTitle]] = defaultdict(list)
    for ut in user_titles:
        ut_by_tmdb_and_user[(ut.tmdb_id, ut.user_id)].append(ut)

    feedbacks = session.scalars(select(Feedback).where(Feedback.tmdb_id.in_(candidate_ids))).all()
    fb_by_tmdb_and_user: dict[tuple[int, int], Feedback] = {
        (f.tmdb_id, f.user_id): f for f in feedbacks
    }

    shortlists = session.scalars(
        select(ShortlistItem).where(ShortlistItem.tmdb_id.in_(candidate_ids))
    ).all()
    sl_by_tmdb_and_user: dict[tuple[int, int], ShortlistItem] = {
        (s.tmdb_id, s.user_id): s for s in shortlists
    }

    group_shortlists = session.scalars(
        select(GroupShortlistItem).where(GroupShortlistItem.tmdb_id.in_(candidate_ids))
    ).all()
    group_sl_by_tmdb: dict[int, GroupShortlistItem] = {g.tmdb_id: g for g in group_shortlists}

    recommendations = session.scalars(
        select(Recommendation).where(Recommendation.tmdb_id.in_(candidate_ids))
    ).all()
    rec_by_tmdb_and_user: dict[tuple[int, int], Recommendation] = {
        (r.tmdb_id, r.user_id): r for r in recommendations
    }

    avail_rows = availability(session, tmdb, list(candidate_ids), user.region)

    candidate_results: list[dict[str, Any]] = []
    category_counts: dict[str, int] = defaultdict(int)
    category_bytes: dict[str, int] = defaultdict(int)
    total_reclaimable_bytes = 0
    protected_count = 0

    for tmdb_id in candidate_ids:
        radarr_movie = radarr_movies.get(tmdb_id)
        size_bytes = int(radarr_movie.get("sizeOnDisk", 0)) if radarr_movie else 0
        radarr_movie_id = radarr_movie.get("id") if radarr_movie else None
        has_file = bool(radarr_movie.get("hasFile")) if radarr_movie else False
        monitored = bool(radarr_movie.get("monitored")) if radarr_movie else False

        title_obj = titles.get(tmdb_id)
        title_name = (
            title_obj.title
            if title_obj
            else (
                radarr_movie.get("title")
                if radarr_movie and radarr_movie.get("title")
                else f"Movie {tmdb_id}"
            )
        )
        year = title_obj.year if title_obj else (radarr_movie.get("year") if radarr_movie else None)
        poster_path = title_obj.poster_path if title_obj else None
        original_language = title_obj.original_language if title_obj else None
        imdb_rating = title_obj.imdb_rating if title_obj else None

        # Skip 0B or unfiled movies when Radarr is configured: movies deleted from Radarr
        # or lacking physical files on disk have no storage to reclaim.
        if radarr_configured and (size_bytes <= 0 or not has_file):
            continue

        # --- 0. Low Quality / CAM (<720p) ---
        low_quality, low_quality_reasons = is_low_quality_movie(radarr_movie)

        # --- 1. Disliked ---
        disliked = False
        dislike_reasons: list[str] = []
        for u in all_users:
            uts = ut_by_tmdb_and_user.get((tmdb_id, u.id), [])
            fb = fb_by_tmdb_and_user.get((tmdb_id, u.id))
            for ut in uts:
                if ut.rating is not None and ut.rating <= 4.0:
                    disliked = True
                    dislike_reasons.append(f"Rated {ut.rating:g}/10 by {u.display_name}")
                if ut.reaction == "disliked":
                    disliked = True
                    dislike_reasons.append(f"Marked disliked by {u.display_name}")
            if fb and fb.kind == "down":
                disliked = True
                dislike_reasons.append(f"Thumbs down by {u.display_name}")

        # --- 2. Abandoned ---
        abandoned = False
        abandon_reasons: list[str] = []
        lis = lib_by_tmdb.get(tmdb_id, [])
        for li in lis:
            if not li.played and li.last_played is not None:
                days_ago = (date.today() - li.last_played).days
                if days_ago >= 30:
                    abandoned = True
                    abandon_reasons.append(f"Started playback {days_ago}d ago but abandoned")
        fb = fb_by_tmdb_and_user.get((tmdb_id, user.id))
        if fb and fb.kind in ("dismiss", "snooze"):
            abandoned = True
            abandon_reasons.append("Dismissed from recommendations")

        # --- 3. Redundant Streamable ---
        redundant_streamable = False
        stream_reasons: list[str] = []
        any_watched = any(
            any(ut.watched for ut in ut_by_tmdb_and_user.get((tmdb_id, u.id), []))
            or any(li.played for li in lib_by_tmdb.get(tmdb_id, []))
            for u in all_users
        )
        any_favorited = any(
            any(ut.favorite for ut in ut_by_tmdb_and_user.get((tmdb_id, u.id), []))
            or any(li.favorite for li in lib_by_tmdb.get(tmdb_id, []))
            for u in all_users
        )
        streaming_offers: list[str] = []
        if any_watched and not any_favorited:
            row = avail_rows.get(tmdb_id)
            offers = watchable(row.offers, user.subscriptions) if row else []
            if offers:
                streaming_offers = sorted(
                    list({str(o.get("name")) for o in offers if o.get("name")})
                )
                redundant_streamable = True
                stream_reasons.append(f"Watched · Available on {', '.join(streaming_offers[:2])}")

        # --- 4. Cold Hoard / Low Match ---
        low_match = False
        low_match_reasons: list[str] = []
        user_rec = rec_by_tmdb_and_user.get((tmdb_id, user.id))
        user_match_pct = round(user_rec.score * 100) if user_rec else None

        if not any_watched and not any_favorited and user_rec and user_rec.score < 0.35:
            low_match = True
            low_match_reasons.append(f"Predicted match only {user_match_pct}% · Unwatched on disk")

        # --- 4b. Low Interest ---
        low_interest = False
        low_interest_reasons: list[str] = []
        if (
            not any_watched
            and not any_favorited
            and not low_match
            and user_rec
            and user_rec.score < 0.50
        ):
            low_interest = True
            low_interest_reasons.append(f"Low predicted interest ({user_match_pct}%) · Unwatched")
        if not disliked and not any_favorited:
            for u in all_users:
                for ut in ut_by_tmdb_and_user.get((tmdb_id, u.id), []):
                    if ut.rating is not None and 4.0 < ut.rating <= 6.0:
                        low_interest = True
                        low_interest_reasons.append(
                            f"Mediocre rating ({ut.rating:g}/10 by {u.display_name})"
                        )
            user_fb = fb_by_tmdb_and_user.get((tmdb_id, user.id))
            if user_fb and user_fb.kind == "snooze":
                low_interest = True
                low_interest_reasons.append("Snoozed from recommendations")

        # --- 5. Unplayable in Jellyfin ---
        on_jellyfin = tmdb_id in lib_by_tmdb
        if not on_jellyfin and unmatched_lib_items:
            cand_year = (
                title_obj.year
                if title_obj
                else (radarr_movie.get("year") if radarr_movie else None)
            )
            cand_titles: set[str] = set()
            if title_obj:
                if title_obj.title:
                    cand_titles.add(title_obj.title)
                if title_obj.original_title:
                    cand_titles.add(title_obj.original_title)
                for alt in getattr(title_obj, "alternative_titles", []) or []:
                    if alt:
                        cand_titles.add(alt)
            if radarr_movie:
                if radarr_movie.get("title"):
                    cand_titles.add(radarr_movie["title"])
                if radarr_movie.get("originalTitle"):
                    cand_titles.add(radarr_movie["originalTitle"])

            matched_lis: list[LibraryItem] = []
            for li in unmatched_lib_items:
                c_name, ext_y = clean_media_title_and_year(li.name)
                norm_li = normalise_title(c_name)
                eff_li_year = li.year or ext_y
                if not norm_li:
                    continue
                for ct in cand_titles:
                    clean_ct, _ = clean_media_title_and_year(ct)
                    norm_ct = normalise_title(clean_ct)
                    if norm_li == norm_ct and (
                        cand_year is None
                        or eff_li_year is None
                        or abs(eff_li_year - cand_year) <= 1
                    ):
                        matched_lis.append(li)
                        break
            if matched_lis:
                for li in matched_lis:
                    li.tmdb_id = tmdb_id
                    lib_by_tmdb[tmdb_id].append(li)
                    if li in unmatched_lib_items:
                        unmatched_lib_items.remove(li)
                    if li.played or li.favorite:
                        _merge_history(session, tmdb, li.user_id, tmdb_id)
                on_jellyfin = True
                db_updated = True

        unplayable = False
        unplayable_reasons: list[str] = []
        if has_jellyfin_data and radarr_movie is not None and size_bytes > 0 and not on_jellyfin:
            unplayable = True
            unplayable_reasons.append(
                f"Present in Radarr ({format_bytes(size_bytes)}) but not found in Jellyfin "
                "(unindexed or non-playable)"
            )

        matching_categories: list[str] = []
        all_reasons: list[str] = []

        if unplayable:
            matching_categories.append("unplayable")
            all_reasons.extend(unplayable_reasons)
        if low_quality:
            matching_categories.append("low_quality")
            all_reasons.extend(low_quality_reasons)
        if disliked:
            matching_categories.append("disliked")
            all_reasons.extend(dislike_reasons)
        if abandoned:
            matching_categories.append("abandoned")
            all_reasons.extend(abandon_reasons)
        if redundant_streamable:
            matching_categories.append("redundant_streamable")
            all_reasons.extend(stream_reasons)
        if low_match:
            matching_categories.append("low_match")
            all_reasons.extend(low_match_reasons)
        if low_interest:
            matching_categories.append("low_interest")
            all_reasons.extend(low_interest_reasons)

        # Skip if not qualifying under any category
        if not matching_categories:
            continue

        primary_cat = matching_categories[0]
        reasons = all_reasons

        # Household Protection Check
        is_protected = False
        protection_reasons: list[str] = []

        if tmdb_id in group_sl_by_tmdb:
            is_protected = True
            adder_id = group_sl_by_tmdb[tmdb_id].added_by
            adder_name = user_map[adder_id].display_name if adder_id in user_map else "Household"
            protection_reasons.append(f"On Group shortlist (added by {adder_name})")

        for u in all_users:
            if u.id == user.id:
                if (tmdb_id, u.id) in sl_by_tmdb_and_user:
                    is_protected = True
                    protection_reasons.append("On your shortlist")
                if any(ut.favorite for ut in ut_by_tmdb_and_user.get((tmdb_id, u.id), [])) or any(
                    li.favorite for li in lib_by_tmdb.get(tmdb_id, [])
                ):
                    is_protected = True
                    protection_reasons.append("Marked as your favorite")
                continue

            if (tmdb_id, u.id) in sl_by_tmdb_and_user:
                is_protected = True
                protection_reasons.append(f"Shortlisted by {u.display_name}")
            if any(ut.favorite for ut in ut_by_tmdb_and_user.get((tmdb_id, u.id), [])) or any(
                li.favorite for li in lib_by_tmdb.get(tmdb_id, [])
            ):
                is_protected = True
                protection_reasons.append(f"Favorited by {u.display_name}")

            for ut in ut_by_tmdb_and_user.get((tmdb_id, u.id), []):
                if ut.rating is not None and ut.rating >= 7.0:
                    is_protected = True
                    protection_reasons.append(f"Rated {ut.rating:g}/10 by {u.display_name}")
                elif ut.reaction in ("liked", "loved"):
                    is_protected = True
                    protection_reasons.append(f"Loved by {u.display_name}")

            other_watched = any(ut.watched for ut in ut_by_tmdb_and_user.get((tmdb_id, u.id), []))
            if not other_watched:
                other_rec = rec_by_tmdb_and_user.get((tmdb_id, u.id))
                if other_rec and other_rec.score >= 0.70:
                    is_protected = True
                    protection_reasons.append(
                        f"{round(other_rec.score * 100)}% match for {u.display_name}"
                    )

        is_ignored = tmdb_id in ignored_ids
        if effective_whitelist == "only" and not is_ignored:
            continue
        if effective_whitelist == "hide" and is_ignored:
            continue

        # Tally counts across matching categories for candidates in current whitelist scope
        for cat in matching_categories:
            category_counts[cat] += 1
            category_bytes[cat] += size_bytes

        if target_categories:
            if categories_mode == "all":
                if not target_categories.issubset(matching_categories):
                    continue
            else:
                if not any(cat in target_categories for cat in matching_categories):
                    continue

        if is_protected:
            protected_count += 1

        total_reclaimable_bytes += size_bytes

        candidate_results.append(
            {
                "tmdb_id": tmdb_id,
                "radarr_movie_id": radarr_movie_id,
                "title": title_name,
                "year": year,
                "poster_path": poster_path,
                "original_language": original_language,
                "imdb_rating": imdb_rating,
                "category": primary_cat,
                "categories": matching_categories,
                "reasons": reasons,
                "size_bytes": size_bytes,
                "size_formatted": format_bytes(size_bytes),
                "has_file": has_file,
                "monitored": monitored,
                "match_pct": user_match_pct,
                "is_protected": is_protected,
                "protection_reasons": protection_reasons,
                "streaming_offers": streaming_offers,
                "is_ignored": is_ignored,
            }
        )

    # Sort candidates by size descending (largest space reclaim first)
    candidate_results.sort(key=lambda c: (not c["is_protected"], c["size_bytes"]), reverse=True)

    summary = {
        cat: {
            "count": category_counts[cat],
            "bytes": category_bytes[cat],
            "formatted": format_bytes(category_bytes[cat]),
        }
        for cat in DECLUTTER_CATEGORIES
    }
    summary["whitelisted"] = {
        "count": len(ignored_candidates),
        "bytes": ignored_bytes,
        "formatted": format_bytes(ignored_bytes),
    }

    if db_updated:
        try:
            session.commit()
        except Exception as err:
            log.warning("Could not persist declutter Jellyfin item matches: %s", err)
            session.rollback()

    return {
        "radarr_configured": radarr_configured,
        "jellyfin_configured": jellyfin_configured,
        "total_candidates": len(candidate_results),
        "reclaimable_bytes": total_reclaimable_bytes,
        "reclaimable_formatted": format_bytes(total_reclaimable_bytes),
        "protected_count": protected_count,
        "categories_summary": summary,
        "items": candidate_results,
    }


def delete_declutter_candidates(
    session: Session,
    tmdb_ids: list[int],
    delete_files: bool = True,
    add_import_exclusion: bool = False,
) -> dict[str, Any]:
    """Delete selected candidate movies and files from Radarr."""
    client = client_from_settings(session)
    if client is None:
        raise RadarrError("Radarr is not configured in Settings")

    all_movies = client.get_all_movies()
    radarr_by_tmdb = {m["tmdbId"]: m for m in all_movies if isinstance(m, dict) and "tmdbId" in m}

    deleted_count = 0
    freed_bytes = 0
    failed_count = 0
    errors: list[str] = []

    for tmdb_id in tmdb_ids:
        rm = radarr_by_tmdb.get(tmdb_id)
        if not rm:
            continue
        movie_id = rm.get("id")
        if not movie_id:
            continue
        size = int(rm.get("sizeOnDisk", 0))
        try:
            client.delete_movie(
                movie_id=movie_id,
                delete_files=delete_files,
                add_import_exclusion=add_import_exclusion,
            )
            deleted_count += 1
            freed_bytes += size
        except RadarrError as err:
            failed_count += 1
            errors.append(f"Failed deleting TMDb {tmdb_id}: {err}")
            log.warning("Radarr delete failed for tmdb %s: %s", tmdb_id, err)

    return {
        "success": True,
        "deleted_count": deleted_count,
        "freed_bytes": freed_bytes,
        "freed_formatted": format_bytes(freed_bytes),
        "failed_count": failed_count,
        "errors": errors,
    }
