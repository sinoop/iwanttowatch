"""Jellyfin: linked users' libraries and play history, and signing in with Jellyfin.

A full sync reads every movie each linked user can see, on startup and every 30
minutes. Webhooks from Jellyfin's Webhook plugin only say which item changed for
which user; that item is then re-read from Jellyfin, so a missed or forged webhook
can't record anything Jellyfin doesn't report.
"""

import contextlib
import logging
import queue
import threading
import time
from collections import defaultdict
from collections.abc import Iterator
from datetime import date, timedelta
from typing import Any

import httpx
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from iwanttowatch import __version__
from iwanttowatch.catalog import (
    LOOKUP_CACHE,
    clean_media_title_and_year,
    ensure_title,
    find_by_title,
)
from iwanttowatch.db import utcnow
from iwanttowatch.models import ConnectorStatus, LibraryItem, User, UserTitle, get_setting
from iwanttowatch.tmdb import TmdbClient, TmdbError, TmdbNotFound
from iwanttowatch.tmdb import client_from_settings as tmdb_from_settings

log = logging.getLogger(__name__)

URL_SETTING = "jellyfin_url"
API_KEY_SETTING = "jellyfin_api_key"
WEBHOOK_TOKEN_SETTING = "jellyfin_webhook_token"
STATUS_KEY = "jellyfin"
SOURCE = "jellyfin"
RECONCILE_EVERY = timedelta(minutes=30)
PAGE_SIZE = 500
TIMEOUT_SECONDS = 30
CLIENT_FIELDS = {
    "Client": "iWantToWatch",
    "Device": "iWantToWatch server",
    "DeviceId": "iwanttowatch-server",
    "Version": __version__,
}


class JellyfinError(Exception):
    pass


class JellyfinAuthError(JellyfinError):
    pass


def normalise_id(value: str) -> str:
    """Jellyfin writes GUIDs both with and without dashes."""
    return value.replace("-", "").lower()


class JellyfinClient:
    def __init__(self, base_url: str, api_key: str | None = None) -> None:
        self._http = httpx.Client(base_url=base_url.rstrip("/"), timeout=TIMEOUT_SECONDS)
        self._api_key = api_key

    def _request(
        self, method: str, path: str, token: str | None, **kwargs: Any
    ) -> dict[str, Any] | None:
        # The MediaBrowser Authorization header is the only scheme Jellyfin 10.12+
        # accepts by default; X-Emby-Token and api_key are legacy.
        fields = {**CLIENT_FIELDS, **({"Token": token} if token else {})}
        header = "MediaBrowser " + ", ".join(f'{k}="{v}"' for k, v in fields.items())
        try:
            response = self._http.request(method, path, headers={"Authorization": header}, **kwargs)
        except httpx.HTTPError as error:
            raise JellyfinError(f"Couldn't reach Jellyfin: {error}") from error
        if response.status_code in (401, 403):
            raise JellyfinAuthError("Jellyfin rejected the credentials")
        if response.is_error:
            raise JellyfinError(f"Jellyfin returned HTTP {response.status_code}")
        if not response.content:
            return None
        try:
            body: dict[str, Any] = response.json()
        except ValueError as error:
            raise JellyfinError("That address doesn't answer like a Jellyfin server") from error
        return body

    def server_name(self) -> str:
        info = self._request("GET", "/System/Info", self._api_key) or {}
        return str(info.get("ServerName") or "Jellyfin")

    def authenticate(self, username: str, password: str) -> tuple[str, str] | None:
        """Check a Jellyfin username and password; returns the user's ID and name."""
        try:
            result = self._request(
                "POST",
                "/Users/AuthenticateByName",
                None,
                json={"Username": username, "Pw": password},
            )
        except JellyfinAuthError:
            return None
        if result is None:
            raise JellyfinError("Jellyfin sent an empty sign-in response")
        # Only the identity is needed, so end the session Jellyfin just opened.
        try:
            self._request("POST", "/Sessions/Logout", result["AccessToken"])
        except JellyfinError:
            log.warning("Couldn't end the Jellyfin session opened to check a password")
        user = result["User"]
        return normalise_id(user["Id"]), str(user["Name"])

    def movies(self, user_id: str, item_ids: list[str] | None = None) -> Iterator[dict[str, Any]]:
        """The movies the user can see, with their play state (UserData)."""
        start = 0
        while True:
            params: dict[str, Any] = {
                "userId": user_id,
                "includeItemTypes": "Movie",
                "recursive": "true",
                "fields": "ProviderIds,OriginalTitle",
                "enableUserData": "true",
                "enableImages": "false",
                "startIndex": start,
                "limit": PAGE_SIZE,
            }
            if item_ids:
                params["ids"] = ",".join(item_ids)
            page = self._request("GET", "/Items", self._api_key, params=params) or {}
            items = page.get("Items") or []
            yield from items
            start += len(items)
            if not items or start >= page.get("TotalRecordCount", 0):
                return


def client_from_settings(session: Session) -> JellyfinClient | None:
    url = get_setting(session, URL_SETTING)
    api_key = get_setting(session, API_KEY_SETTING)
    return JellyfinClient(url, api_key) if url and api_key else None


def sync_user(
    session: Session,
    jellyfin: JellyfinClient,
    tmdb: TmdbClient,
    user: User,
    item_ids: list[str] | None = None,
) -> None:
    """Update the user's library items and their merged "jellyfin" watch history.

    Without item_ids the whole library is read and items the user can no longer see
    are dropped; their watch history stays, since it outlives the file.
    """
    assert user.jellyfin_user_id is not None
    query = select(LibraryItem).where(LibraryItem.user_id == user.id)
    if item_ids:
        query = query.where(LibraryItem.item_id.in_(item_ids))
    known = {item.item_id: item for item in session.scalars(query)}
    # Matches made before, for any user, so titles without provider IDs are searched once.
    matches = {
        item_id: tmdb_id
        for item_id, tmdb_id in session.execute(
            select(LibraryItem.item_id, LibraryItem.tmdb_id).where(LibraryItem.tmdb_id.is_not(None))
        )
    }
    touched: set[int] = set()
    seen: set[str] = set()
    for data in jellyfin.movies(user.jellyfin_user_id, item_ids):
        item_id = normalise_id(data["Id"])
        seen.add(item_id)
        item = known.get(item_id)
        if item is None:
            item = known[item_id] = LibraryItem(user_id=user.id, item_id=item_id)
            session.add(item)
        if item.tmdb_id is not None:
            touched.add(item.tmdb_id)
        item.tmdb_id = _match(tmdb, data, matches.get(item_id, -1))
        matches[item_id] = item.tmdb_id
        item.name = str(data.get("Name") or "")
        item.year = data.get("ProductionYear")
        user_data = data.get("UserData") or {}
        item.played = bool(user_data.get("Played"))
        item.favorite = bool(user_data.get("IsFavorite"))
        last_played = user_data.get("LastPlayedDate")
        item.last_played = date.fromisoformat(last_played[:10]) if last_played else None
        if item.tmdb_id is not None:
            touched.add(item.tmdb_id)
    if item_ids is None:
        for item_id, item in known.items():
            if item_id not in seen:
                session.delete(item)
    session.flush()
    for tmdb_id in touched:
        _merge_history(session, tmdb, user.id, tmdb_id)


def _match(tmdb: TmdbClient, data: dict[str, Any], previous: int | None) -> int | None:
    """The item's TMDb ID: from its provider IDs, an earlier match, IMDb, or its title.

    previous is -1 for an item never seen before, or None if previously unmatched.
    """
    ids = {k.lower(): v for k, v in (data.get("ProviderIds") or {}).items() if v}
    tmdb_val = ids.get("tmdb") or ids.get("themoviedb")
    if tmdb_val is not None and str(tmdb_val).isdigit():
        return int(tmdb_val)
    if previous is not None and previous != -1:
        return previous
    if imdb_id := ids.get("imdb"):
        found = tmdb.get(f"/find/{imdb_id}", {"external_source": "imdb_id"}, LOOKUP_CACHE)
        if found["movie_results"]:
            return int(found["movie_results"][0]["id"])
    # Without online metadata Jellyfin names items after their folder, e.g. "Premam (2015)".
    raw_name = str(data.get("Name") or "")
    clean_name, extracted_year = clean_media_title_and_year(raw_name)
    year = data.get("ProductionYear") or extracted_year
    if not clean_name:
        return None
    tmdb_id, _candidates = find_by_title(tmdb, clean_name, year)
    return tmdb_id


def _merge_history(session: Session, tmdb: TmdbClient, user_id: int, tmdb_id: int) -> None:
    """Set the user's "jellyfin" UserTitle for a film from all its library items."""
    items = session.scalars(
        select(LibraryItem).where(LibraryItem.user_id == user_id, LibraryItem.tmdb_id == tmdb_id)
    ).all()
    played = [item for item in items if item.played]
    favorite = any(item.favorite for item in items)
    entry = session.scalar(
        select(UserTitle).where(
            UserTitle.user_id == user_id, UserTitle.tmdb_id == tmdb_id, UserTitle.source == SOURCE
        )
    )
    if not played and not favorite:
        if entry is not None:
            session.delete(entry)
        return
    if entry is None:
        try:
            ensure_title(session, tmdb, tmdb_id)
        except TmdbNotFound:
            for item in items:
                item.tmdb_id = None
            return
        entry = UserTitle(user_id=user_id, tmdb_id=tmdb_id, source=SOURCE)
        session.add(entry)
    entry.watched = bool(played)
    entry.watched_at = max((i.last_played for i in played if i.last_played), default=None)
    entry.favorite = favorite


def sync(engine: Engine, tmdb_base_url: str, items: dict[int, set[str]] | None = None) -> None:
    """Sync every linked user's whole library, or only the given items of the given users."""
    with Session(engine) as session:
        jellyfin = client_from_settings(session)
        if jellyfin is None:
            return
        tmdb = tmdb_from_settings(session, engine, tmdb_base_url)
        if tmdb is None:
            _set_status(session, error="Add a TMDb API key so Jellyfin movies can be matched")
            return
        query = select(User).where(User.jellyfin_user_id.is_not(None))
        if items is not None:
            query = query.where(User.id.in_(items))
        errors = []
        for user in session.scalars(query).all():
            try:
                ids = sorted(items[user.id]) if items is not None else None
                sync_user(session, jellyfin, tmdb, user, ids)
                session.commit()
            except JellyfinAuthError:
                session.rollback()
                _set_status(session, error="Jellyfin rejected the API key; update it in Settings")
                return
            except (JellyfinError, TmdbError) as error:
                session.rollback()
                errors.append(f"{user.display_name}: {error}")
        if errors:
            _set_status(session, error="; ".join(errors))
        elif items is None:
            _set_status(session, error=None, synced_at=utcnow())


def _set_status(session: Session, **fields: Any) -> None:
    status = session.get(ConnectorStatus, STATUS_KEY) or ConnectorStatus(connector=STATUS_KEY)
    for name, value in fields.items():
        setattr(status, name, value)
    session.add(status)
    session.commit()


def record_webhook(session: Session) -> None:
    _set_status(session, webhook_at=utcnow())


class JellyfinWorker:
    """Runs syncs on a background thread: a full sync at startup and every 30 minutes,
    and single-item syncs as webhooks report changes."""

    def __init__(self, engine: Engine, tmdb_base_url: str) -> None:
        self._engine = engine
        self._tmdb_base_url = tmdb_base_url
        # None asks for a full sync; (user ID, item ID) for one item.
        self._queue: queue.Queue[tuple[int, str] | None] = queue.Queue()

    def start(self) -> None:
        self.request_full_sync()
        threading.Thread(target=self._loop, name="jellyfin", daemon=True).start()

    def request_full_sync(self) -> None:
        self._queue.put(None)

    def request_item_sync(self, user_id: int, item_id: str) -> None:
        self._queue.put((user_id, item_id))

    def wait_until_idle(self) -> None:
        self._queue.join()

    def _loop(self) -> None:
        every = RECONCILE_EVERY.total_seconds()
        next_full = time.monotonic() + every
        while True:
            jobs: list[tuple[int, str] | None] = []
            with contextlib.suppress(queue.Empty):
                jobs.append(self._queue.get(timeout=max(0.0, next_full - time.monotonic())))
            # Jellyfin sends a burst on playback stop (stop, then user data saved): take
            # everything queued so far as one sync.
            while True:
                try:
                    jobs.append(self._queue.get_nowait())
                except queue.Empty:
                    break
            try:
                if not jobs or None in jobs:
                    next_full = time.monotonic() + every
                    sync(self._engine, self._tmdb_base_url)
                else:
                    items: dict[int, set[str]] = defaultdict(set)
                    for job in jobs:
                        assert job is not None
                        items[job[0]].add(job[1])
                    sync(self._engine, self._tmdb_base_url, items)
            except Exception:
                log.exception("Jellyfin sync crashed")
                with Session(self._engine) as session:
                    _set_status(session, error="Unexpected error; see the server log")
            finally:
                for _ in jobs:
                    self._queue.task_done()
