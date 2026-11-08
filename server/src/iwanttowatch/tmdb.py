"""TMDb API client with response caching, a shared rate limit, and retries."""

import json
import threading
import time
from datetime import timedelta
from typing import Any

import httpx
from sqlalchemy import Engine, delete, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from iwanttowatch.db import utcnow
from iwanttowatch.models import ApiCache, get_setting

DEFAULT_BASE_URL = "https://api.themoviedb.org/3"
API_KEY_SETTING = "tmdb_api_key"
# TMDb allows roughly 50 requests per second per IP; stay well below it.
REQUESTS_PER_SECOND = 20
MAX_ATTEMPTS = 5


class TmdbError(Exception):
    pass


class TmdbAuthError(TmdbError):
    pass


class TmdbNotFound(TmdbError):
    pass


class _RateLimiter:
    """Spaces requests evenly across every client in the process."""

    def __init__(self, per_second: float) -> None:
        self._interval = 1 / per_second
        self._next = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delay = self._next - now
            self._next = max(now, self._next) + self._interval
        if delay > 0:
            time.sleep(delay)


_limiter = _RateLimiter(REQUESTS_PER_SECOND)


class TmdbClient:
    def __init__(self, api_key: str, engine: Engine, base_url: str = DEFAULT_BASE_URL) -> None:
        self._engine = engine
        # v4 "API Read Access Tokens" are JWTs sent as a bearer token; v3 keys go in the query.
        bearer = api_key.startswith("eyJ")
        self._http = httpx.Client(
            base_url=base_url,
            timeout=15,
            headers={"Authorization": f"Bearer {api_key}"} if bearer else {},
            params={} if bearer else {"api_key": api_key},
        )

    def get(
        self, path: str, params: dict[str, Any] | None = None, cache_for: timedelta | None = None
    ) -> dict[str, Any]:
        params = {k: v for k, v in (params or {}).items() if v is not None}
        key = path + "?" + "&".join(f"{k}={params[k]}" for k in sorted(params))
        if cache_for:
            cached = self._cached(key)
            if cached is not None:
                return cached
        body = self._request(path, params)
        if cache_for:
            values = {"body": json.dumps(body), "expires_at": utcnow() + cache_for}
            with Session(self._engine) as session:
                # An upsert: parallel requests may cache the same response.
                session.execute(
                    insert(ApiCache)
                    .values(key=key, **values)
                    .on_conflict_do_update(index_elements=[ApiCache.key], set_=values)
                )
                session.commit()
        return body

    def _cached(self, key: str) -> dict[str, Any] | None:
        with Session(self._engine) as session:
            session.execute(delete(ApiCache).where(ApiCache.expires_at <= utcnow()))
            session.commit()
            body = session.scalar(select(ApiCache.body).where(ApiCache.key == key))
        return json.loads(body) if body is not None else None

    def _request(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        for attempt in range(MAX_ATTEMPTS):
            last_attempt = attempt == MAX_ATTEMPTS - 1
            _limiter.wait()
            try:
                response = self._http.get(path, params=params)
            except httpx.TransportError as error:
                if last_attempt:
                    raise TmdbError(f"TMDb is unreachable: {error}") from error
                time.sleep(2**attempt)
                continue
            if response.status_code == 401:
                raise TmdbAuthError("TMDb rejected the API key")
            if response.status_code == 404:
                raise TmdbNotFound(path)
            if response.status_code == 429 or response.status_code >= 500:
                if last_attempt:
                    raise TmdbError(f"TMDb returned HTTP {response.status_code}")
                retry_after = response.headers.get("Retry-After", "")
                time.sleep(float(retry_after) if retry_after.isdigit() else 2**attempt)
                continue
            response.raise_for_status()
            result: dict[str, Any] = response.json()
            return result
        raise AssertionError("unreachable")


def client_from_settings(session: Session, engine: Engine, base_url: str) -> TmdbClient | None:
    """The TMDb client configured by the admin, or None when no key is set yet."""
    api_key = get_setting(session, API_KEY_SETTING)
    return TmdbClient(api_key, engine, base_url) if api_key else None
