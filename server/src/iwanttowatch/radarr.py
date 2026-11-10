"""Radarr integration: movie search, acquisition status, and downloading.

Communicates with Radarr v3 API using an API key to inspect movie status and
queue unstreamable movie downloads.
"""

import json
import logging
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from iwanttowatch.availability import availability, watchable
from iwanttowatch.children import library_owners
from iwanttowatch.models import (
    GroupShortlistItem,
    LibraryItem,
    ShortlistItem,
    Title,
    User,
    get_setting,
    set_setting,
)

log = logging.getLogger(__name__)

URL_SETTING = "radarr_url"
API_KEY_SETTING = "radarr_api_key"
QUALITY_PROFILE_SETTING = "radarr_quality_profile_id"
ROOT_FOLDER_SETTING = "radarr_root_folder_path"
LANGUAGE_ROOT_FOLDERS_SETTING = "radarr_language_root_folders"
MIN_AVAILABILITY_SETTING = "radarr_minimum_availability"
AUTO_SYNC_SHORTLIST_SETTING = "radarr_auto_sync_shortlist"
DEFAULT_MIN_AVAILABILITY = "announced"
TIMEOUT_SECONDS = 5.0


class RadarrError(Exception):
    pass


class RadarrAuthError(RadarrError):
    pass


class RadarrNotFoundError(RadarrError):
    pass


class RadarrClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = TIMEOUT_SECONDS) -> None:
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._http = httpx.Client(
            base_url=self.base_url,
            headers={
                "X-Api-Key": api_key,
                "Accept": "application/json",
            },
            timeout=timeout,
        )

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = self._http.request(method, path, **kwargs)
        except httpx.HTTPError as error:
            raise RadarrError(f"Couldn't reach Radarr: {error}") from error
        if response.status_code in (401, 403):
            raise RadarrAuthError("Radarr rejected the API key")
        if response.status_code == 404:
            raise RadarrNotFoundError(f"Radarr route not found: {path}")
        if response.is_error:
            detail = ""
            try:
                err_data = response.json()
                if isinstance(err_data, list) and err_data and "errorMessage" in err_data[0]:
                    detail = f": {err_data[0]['errorMessage']}"
                elif isinstance(err_data, dict) and "message" in err_data:
                    detail = f": {err_data['message']}"
            except Exception:
                pass
            raise RadarrError(f"Radarr returned HTTP {response.status_code}{detail}")
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as error:
            raise RadarrError("Radarr response wasn't valid JSON") from error

    def system_status(self) -> dict[str, Any]:
        """Check Radarr connection and fetch version details."""
        res = self._request("GET", "/api/v3/system/status")
        return res if isinstance(res, dict) else {}

    def quality_profiles(self) -> list[dict[str, Any]]:
        """Available quality profiles in Radarr."""
        res = self._request("GET", "/api/v3/qualityprofile")
        return res if isinstance(res, list) else []

    def root_folders(self) -> list[dict[str, Any]]:
        """Available root storage folders in Radarr."""
        res = self._request("GET", "/api/v3/rootfolder")
        return res if isinstance(res, list) else []

    def get_movie_by_tmdb(self, tmdb_id: int) -> dict[str, Any] | None:
        """Check if a movie with this TMDb ID exists in Radarr."""
        res = self._request("GET", "/api/v3/movie", params={"tmdbId": tmdb_id})
        if isinstance(res, list) and res and isinstance(res[0], dict):
            return res[0]
        return None

    def get_all_movies(self) -> list[dict[str, Any]]:
        """Return all movies currently tracked in Radarr."""
        res = self._request("GET", "/api/v3/movie")
        return res if isinstance(res, list) else []

    def lookup_movie(self, tmdb_id: int) -> dict[str, Any] | None:
        """Search Radarr's metadata lookup for a TMDb ID."""
        try:
            res = self._request("GET", "/api/v3/movie/lookup/tmdb", params={"tmdbId": tmdb_id})
            if isinstance(res, dict):
                return res
        except RadarrError:
            pass
        # Fallback to general lookup endpoint
        try:
            res = self._request("GET", "/api/v3/movie/lookup", params={"term": f"tmdb:{tmdb_id}"})
            if isinstance(res, list) and res and isinstance(res[0], dict):
                return res[0]
        except RadarrError:
            pass
        return None

    def search_movies(self, movie_ids: list[int]) -> dict[str, Any]:
        """Trigger an interactive or automatic search command for movie IDs."""
        res = self._request(
            "POST", "/api/v3/command", json={"name": "MoviesSearch", "movieIds": movie_ids}
        )
        return res if isinstance(res, dict) else {}

    def add_movie(
        self,
        tmdb_id: int,
        quality_profile_id: int,
        root_folder_path: str,
        minimum_availability: str = DEFAULT_MIN_AVAILABILITY,
        search: bool = True,
        title: str | None = None,
        year: int | None = None,
    ) -> dict[str, Any]:
        """Add a movie to Radarr and start monitoring/searching."""
        item = self.lookup_movie(tmdb_id)
        if not item:
            item = {
                "title": title or f"Movie {tmdb_id}",
                "tmdbId": tmdb_id,
                "year": year or 0,
                "titleSlug": str(tmdb_id),
                "images": [],
            }
        item["qualityProfileId"] = quality_profile_id
        item["rootFolderPath"] = root_folder_path
        item["monitored"] = True
        item["minimumAvailability"] = minimum_availability
        item["addOptions"] = {"searchForMovie": search}
        res = self._request("POST", "/api/v3/movie", json=item)
        return res if isinstance(res, dict) else {}

    def add_or_search(
        self,
        tmdb_id: int,
        quality_profile_id: int,
        root_folder_path: str,
        minimum_availability: str = DEFAULT_MIN_AVAILABILITY,
        search: bool = True,
        title: str | None = None,
        year: int | None = None,
    ) -> dict[str, Any]:
        """Add a movie to Radarr, or if already added, make sure it's monitored and searched."""
        existing = self.get_movie_by_tmdb(tmdb_id)
        if existing:
            movie_id = existing.get("id")
            if not existing.get("monitored") and movie_id:
                existing["monitored"] = True
                try:
                    self._request("PUT", f"/api/v3/movie/{movie_id}", json=existing)
                except RadarrError:
                    log.warning("Couldn't update Radarr movie monitoring for %s", tmdb_id)
            if search and movie_id:
                try:
                    self.search_movies([movie_id])
                except RadarrError:
                    log.warning("Couldn't trigger Radarr search for %s", tmdb_id)
            return existing
        return self.add_movie(
            tmdb_id=tmdb_id,
            quality_profile_id=quality_profile_id,
            root_folder_path=root_folder_path,
            minimum_availability=minimum_availability,
            search=search,
            title=title,
            year=year,
        )

    def delete_movie(
        self,
        movie_id: int,
        delete_files: bool = True,
        add_import_exclusion: bool = False,
    ) -> bool:
        """Delete a movie from Radarr, optionally deleting movie files from disk."""
        params = {
            "deleteFiles": "true" if delete_files else "false",
            "addImportExclusion": "true" if add_import_exclusion else "false",
        }
        self._request("DELETE", f"/api/v3/movie/{movie_id}", params=params)
        return True


def client_from_settings(session: Session, timeout: float = TIMEOUT_SECONDS) -> RadarrClient | None:
    """Instantiate a RadarrClient if URL and API key are configured."""
    url = get_setting(session, URL_SETTING)
    api_key = get_setting(session, API_KEY_SETTING)
    if not url or not api_key:
        return None
    return RadarrClient(url, api_key, timeout=timeout)


def movie_status(session: Session, tmdb_id: int) -> dict[str, Any]:
    """Query Radarr for this movie's current status, or return configured=False."""
    client = client_from_settings(session, timeout=2.5)
    if client is None:
        return {"configured": False}
    try:
        movie = client.get_movie_by_tmdb(tmdb_id)
    except RadarrError as err:
        log.warning("Radarr error for tmdb %s: %s", tmdb_id, err)
        return {"configured": True, "error": str(err)}

    if not movie:
        return {"configured": True, "status": "not_added"}

    has_file = bool(movie.get("hasFile"))
    monitored = bool(movie.get("monitored"))
    is_available = bool(movie.get("isAvailable"))
    slug = movie.get("titleSlug")
    radarr_url = f"{client.base_url}/movie/{slug}" if slug else None

    if has_file:
        status = "downloaded"
    elif monitored:
        status = "downloading"
    else:
        status = "unmonitored"

    return {
        "configured": True,
        "movie_id": movie.get("id"),
        "title": movie.get("title"),
        "has_file": has_file,
        "monitored": monitored,
        "is_available": is_available,
        "status": status,
        "radarr_url": radarr_url,
    }


def get_language_root_folders(session: Session) -> dict[str, str]:
    """Stored mapping from ISO 639-1 language code to Radarr root folder path."""
    raw = get_setting(session, LANGUAGE_ROOT_FOLDERS_SETTING)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return {str(k).lower().strip(): str(v).strip() for k, v in data.items() if k and v}
    except Exception:
        pass
    return {}


def resolve_root_folder(session: Session, language: str | None, default_folder: str) -> str:
    """Resolve the Radarr root folder for a given movie language, falling back to default."""
    if language:
        mapping = get_language_root_folders(session)
        folder = mapping.get(language.lower().strip())
        if folder:
            return folder
    return default_folder


def save_settings(
    session: Session,
    url: str,
    api_key: str | None,
    quality_profile_id: int | None = None,
    root_folder_path: str | None = None,
    minimum_availability: str = DEFAULT_MIN_AVAILABILITY,
    language_root_folders: dict[str, str] | None = None,
    auto_sync_shortlist: bool | None = None,
) -> None:
    """Store Radarr settings in the database."""
    set_setting(session, URL_SETTING, url.rstrip("/"))
    if api_key:
        set_setting(session, API_KEY_SETTING, api_key)
    if quality_profile_id is not None:
        set_setting(session, QUALITY_PROFILE_SETTING, str(quality_profile_id))
    if root_folder_path is not None:
        set_setting(session, ROOT_FOLDER_SETTING, root_folder_path)
    set_setting(session, MIN_AVAILABILITY_SETTING, minimum_availability)
    if language_root_folders is not None:
        cleaned = {
            str(k).lower().strip(): str(v).strip()
            for k, v in language_root_folders.items()
            if k and v
        }
        set_setting(session, LANGUAGE_ROOT_FOLDERS_SETTING, json.dumps(cleaned))
    if auto_sync_shortlist is not None:
        set_setting(
            session, AUTO_SYNC_SHORTLIST_SETTING, "true" if auto_sync_shortlist else "false"
        )


def clear_settings(session: Session) -> None:
    """Disconnect and clear Radarr configuration."""
    set_setting(session, URL_SETTING, None)
    set_setting(session, API_KEY_SETTING, None)
    set_setting(session, QUALITY_PROFILE_SETTING, None)
    set_setting(session, ROOT_FOLDER_SETTING, None)
    set_setting(session, LANGUAGE_ROOT_FOLDERS_SETTING, None)
    set_setting(session, MIN_AVAILABILITY_SETTING, None)
    set_setting(session, AUTO_SYNC_SHORTLIST_SETTING, None)


def is_auto_sync_enabled(session: Session) -> bool:
    """Whether unstreamable shortlisted movies are automatically requested in Radarr."""
    return get_setting(session, AUTO_SYNC_SHORTLIST_SETTING) == "true"


def queue_movie(
    session: Session,
    tmdb_id: int,
    title: str | None = None,
    year: int | None = None,
    language: str | None = None,
    client: RadarrClient | None = None,
    profile_id: int | None = None,
    default_root_folder: str | None = None,
    min_avail: str | None = None,
    search: bool = True,
) -> dict[str, Any]:
    """Ensure a movie is added and queued in Radarr with quality profile and root folder."""
    if client is None:
        client = client_from_settings(session)
        if client is None:
            raise RadarrError("Radarr is not configured in Settings")

    if profile_id is None:
        profile_id_str = get_setting(session, QUALITY_PROFILE_SETTING)
        profile_id = int(profile_id_str) if profile_id_str and profile_id_str.isdigit() else None
        if profile_id is None:
            profiles = client.quality_profiles()
            if not profiles:
                raise RadarrError("No quality profiles found in Radarr")
            profile_id = profiles[0]["id"]

    if default_root_folder is None:
        default_root_folder = get_setting(session, ROOT_FOLDER_SETTING)
        if not default_root_folder:
            root_folders = client.root_folders()
            if not root_folders:
                raise RadarrError("No root folders found in Radarr")
            default_root_folder = root_folders[0]["path"]

    if min_avail is None:
        min_avail = get_setting(session, MIN_AVAILABILITY_SETTING) or DEFAULT_MIN_AVAILABILITY

    target_root_folder = resolve_root_folder(session, language, default_root_folder)
    return client.add_or_search(
        tmdb_id=tmdb_id,
        quality_profile_id=profile_id,
        root_folder_path=target_root_folder,
        minimum_availability=min_avail,
        search=search,
        title=title,
        year=year,
    )


def auto_sync_if_unstreamable(
    session: Session,
    tmdb: Any,
    user: User,
    tmdb_id: int,
    title: Title | None = None,
) -> bool:
    """If auto-sync is enabled and title is unstreamable on streaming/Jellyfin, queue in Radarr."""
    if user.is_child or not is_auto_sync_enabled(session):
        return False
    client = client_from_settings(session)
    if client is None:
        return False

    owners = library_owners(session, user)
    in_library = (
        session.scalar(
            select(LibraryItem.tmdb_id).where(
                LibraryItem.user_id.in_(owners), LibraryItem.tmdb_id == tmdb_id
            )
        )
        is not None
    )
    if in_library:
        return False

    avail_rows = availability(session, tmdb, [tmdb_id], user.region)
    row = avail_rows.get(tmdb_id)
    offers = watchable(row.offers, user.subscriptions) if row else []
    if len(offers) > 0:
        return False

    if title is None:
        title = session.get(Title, tmdb_id)

    title_name = title.title if title else f"Movie {tmdb_id}"
    year = title.year if title else None
    lang = title.original_language if title else None

    try:
        queue_movie(
            session=session,
            tmdb_id=tmdb_id,
            title=title_name,
            year=year,
            language=lang,
            client=client,
            search=True,
        )
        log.info("Auto-synced shortlisted movie %s (%s) to Radarr", title_name, tmdb_id)
        return True
    except RadarrError as err:
        log.warning("Auto-sync to Radarr failed for %s (%s): %s", title_name, tmdb_id, err)
        return False


def inspect_shortlist_sync(
    session: Session,
    tmdb: Any,
    user: User,
    scope: str = "user",
    tmdb_ids: list[int] | None = None,
) -> dict[str, Any]:
    """Inspect shortlisted films and determine streaming availability and Radarr status."""
    if tmdb_ids is not None:
        ids = list(dict.fromkeys(tmdb_ids))
    elif scope == "group":
        ids = list(
            session.scalars(
                select(GroupShortlistItem.tmdb_id).order_by(GroupShortlistItem.added_at.desc())
            )
        )
    elif scope == "all":
        user_ids = list(
            session.scalars(select(ShortlistItem.tmdb_id).where(ShortlistItem.user_id == user.id))
        )
        group_ids = list(session.scalars(select(GroupShortlistItem.tmdb_id)))
        ids = list(dict.fromkeys(user_ids + group_ids))
    else:
        ids = list(
            session.scalars(
                select(ShortlistItem.tmdb_id)
                .where(ShortlistItem.user_id == user.id)
                .order_by(ShortlistItem.added_at.desc())
            )
        )

    client = client_from_settings(session, timeout=3.0)
    configured = client is not None
    auto_sync = is_auto_sync_enabled(session)

    if not ids:
        return {
            "configured": configured,
            "auto_sync": auto_sync,
            "scope": scope,
            "total_shortlisted": 0,
            "unstreamable_count": 0,
            "to_request_count": 0,
            "downloading_count": 0,
            "downloaded_count": 0,
            "available_count": 0,
            "failed_count": 0,
            "items": [],
        }

    owners = library_owners(session, user)
    in_library = set(
        session.scalars(
            select(LibraryItem.tmdb_id).where(
                LibraryItem.user_id.in_(owners), LibraryItem.tmdb_id.in_(ids)
            )
        )
    )
    avail_rows = availability(session, tmdb, ids, user.region)
    titles = {t.tmdb_id: t for t in session.scalars(select(Title).where(Title.tmdb_id.in_(ids)))}

    radarr_movies: dict[int, dict[str, Any]] = {}
    if client is not None:
        try:
            radarr_movies = {
                m["tmdbId"]: m
                for m in client.get_all_movies()
                if isinstance(m, dict) and "tmdbId" in m
            }
        except RadarrError as err:
            log.warning("Could not list Radarr movies during shortlist inspection: %s", err)

    items: list[dict[str, Any]] = []
    unstreamable_count = 0
    to_request_count = 0
    downloading_count = 0
    downloaded_count = 0
    available_count = 0

    for tmdb_id in ids:
        title_obj = titles.get(tmdb_id)
        title_name = title_obj.title if title_obj else f"Movie {tmdb_id}"
        year = title_obj.year if title_obj else None

        on_jellyfin = tmdb_id in in_library
        row = avail_rows.get(tmdb_id)
        offers = watchable(row.offers, user.subscriptions) if row else []
        is_streamable = on_jellyfin or len(offers) > 0

        if is_streamable:
            available_count += 1
            detail = "Available on Jellyfin" if on_jellyfin else "Available on streaming"
            items.append(
                {
                    "tmdb_id": tmdb_id,
                    "title": title_name,
                    "year": year,
                    "status": "available",
                    "detail": detail,
                }
            )
            continue

        unstreamable_count += 1
        rm = radarr_movies.get(tmdb_id)
        if rm:
            if rm.get("hasFile"):
                downloaded_count += 1
                items.append(
                    {
                        "tmdb_id": tmdb_id,
                        "title": title_name,
                        "year": year,
                        "status": "downloaded",
                        "detail": "Downloaded in Radarr",
                    }
                )
            elif rm.get("monitored"):
                downloading_count += 1
                items.append(
                    {
                        "tmdb_id": tmdb_id,
                        "title": title_name,
                        "year": year,
                        "status": "downloading",
                        "detail": "Downloading in Radarr",
                    }
                )
            else:
                to_request_count += 1
                items.append(
                    {
                        "tmdb_id": tmdb_id,
                        "title": title_name,
                        "year": year,
                        "status": "to_request",
                        "detail": "In Radarr but unmonitored",
                    }
                )
        else:
            to_request_count += 1
            items.append(
                {
                    "tmdb_id": tmdb_id,
                    "title": title_name,
                    "year": year,
                    "status": "to_request",
                    "detail": "Not in Radarr",
                }
            )

    return {
        "configured": configured,
        "auto_sync": auto_sync,
        "scope": scope,
        "total_shortlisted": len(ids),
        "unstreamable_count": unstreamable_count,
        "to_request_count": to_request_count,
        "downloading_count": downloading_count,
        "downloaded_count": downloaded_count,
        "available_count": available_count,
        "failed_count": 0,
        "items": items,
    }


def batch_sync_shortlist(
    session: Session,
    tmdb: Any,
    user: User,
    scope: str = "user",
    tmdb_ids: list[int] | None = None,
) -> dict[str, Any]:
    """Batch queue unstreamable shortlisted movies into Radarr."""
    inspection = inspect_shortlist_sync(session, tmdb, user, scope=scope, tmdb_ids=tmdb_ids)
    client = client_from_settings(session)
    if client is None:
        raise RadarrError("Radarr is not configured in Settings")

    titles = {
        t.tmdb_id: t
        for t in session.scalars(
            select(Title).where(Title.tmdb_id.in_([i["tmdb_id"] for i in inspection["items"]]))
        )
    }

    requested_count = 0
    failed_count = 0
    updated_items: list[dict[str, Any]] = []

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

    min_avail = get_setting(session, MIN_AVAILABILITY_SETTING) or DEFAULT_MIN_AVAILABILITY

    for item in inspection["items"]:
        if item["status"] != "to_request":
            updated_items.append(item)
            continue

        tmdb_id = item["tmdb_id"]
        title_obj = titles.get(tmdb_id)
        title_name = title_obj.title if title_obj else item["title"]
        year = title_obj.year if title_obj else item["year"]
        lang = title_obj.original_language if title_obj else None

        try:
            queue_movie(
                session=session,
                tmdb_id=tmdb_id,
                title=title_name,
                year=year,
                language=lang,
                client=client,
                profile_id=profile_id,
                default_root_folder=default_root_folder,
                min_avail=min_avail,
                search=True,
            )
            requested_count += 1
            updated_items.append(
                {
                    "tmdb_id": tmdb_id,
                    "title": title_name,
                    "year": year,
                    "status": "requested",
                    "detail": "Queued in Radarr",
                }
            )
        except RadarrError as err:
            failed_count += 1
            log.warning("Batch sync failed for tmdb %s (%s): %s", tmdb_id, title_name, err)
            updated_items.append(
                {
                    "tmdb_id": tmdb_id,
                    "title": title_name,
                    "year": year,
                    "status": "failed",
                    "detail": str(err),
                }
            )

    return {
        "configured": True,
        "scope": scope,
        "total_shortlisted": inspection["total_shortlisted"],
        "unstreamable_count": inspection["unstreamable_count"],
        "requested_count": requested_count,
        "downloading_count": inspection["downloading_count"],
        "downloaded_count": inspection["downloaded_count"],
        "available_count": inspection["available_count"],
        "failed_count": failed_count,
        "items": updated_items,
    }
