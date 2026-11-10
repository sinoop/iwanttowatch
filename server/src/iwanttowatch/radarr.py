"""Radarr integration: movie search, acquisition status, and downloading.

Communicates with Radarr v3 API using an API key to inspect movie status and
queue unstreamable movie downloads.
"""

import logging
from typing import Any

import httpx
from sqlalchemy.orm import Session

from iwanttowatch.models import get_setting, set_setting

log = logging.getLogger(__name__)

URL_SETTING = "radarr_url"
API_KEY_SETTING = "radarr_api_key"
QUALITY_PROFILE_SETTING = "radarr_quality_profile_id"
ROOT_FOLDER_SETTING = "radarr_root_folder_path"
MIN_AVAILABILITY_SETTING = "radarr_minimum_availability"
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


def save_settings(
    session: Session,
    url: str,
    api_key: str | None,
    quality_profile_id: int | None = None,
    root_folder_path: str | None = None,
    minimum_availability: str = DEFAULT_MIN_AVAILABILITY,
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


def clear_settings(session: Session) -> None:
    """Disconnect and clear Radarr configuration."""
    set_setting(session, URL_SETTING, None)
    set_setting(session, API_KEY_SETTING, None)
    set_setting(session, QUALITY_PROFILE_SETTING, None)
    set_setting(session, ROOT_FOLDER_SETTING, None)
    set_setting(session, MIN_AVAILABILITY_SETTING, None)
