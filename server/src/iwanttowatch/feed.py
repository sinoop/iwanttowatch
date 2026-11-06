"""Building each user's discovery feed in the background.

A build gathers candidates (unwatched films in the user's Jellyfin libraries, the
best-rated films on their streaming services and in their languages, and TMDb's
recommendations for their favourites), fetches their details and where they
stream, scores them with the recommender, and stores the ranked result. The feed
page reads that stored result, so it stays fast on small hardware.

Ratings and feedback on feed cards trigger a rescore instead: the same candidates
scored again with the new labels, with no TMDb requests, a few seconds after the
user's last click.
"""

import logging
import queue
import threading
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, timedelta
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import Engine, delete, func, or_, select
from sqlalchemy.orm import Session

from iwanttowatch import imdb
from iwanttowatch.availability import availability
from iwanttowatch.catalog import ensure_titles, find_by_title
from iwanttowatch.db import utcnow
from iwanttowatch.llm import LlmError, provider_from_settings
from iwanttowatch.models import (
    AiPick,
    Feedback,
    FeedBuild,
    LibraryItem,
    Recommendation,
    Title,
    User,
    UserTitle,
)
from iwanttowatch.recommender import Label, Scored, percentiles, score
from iwanttowatch.taste import effective_ratings, suggest_films
from iwanttowatch.tmdb import TmdbClient, TmdbError, TmdbNotFound, client_from_settings

log = logging.getLogger(__name__)

Job = Literal["build", "rescore"]

MAX_CANDIDATES = 800
# Top-rated films whose TMDb recommendations become candidates.
RECOMMENDATION_SEEDS = 30
DISCOVER_PAGES = 2
# Vote floors keep obscure films out; one language needs fewer votes, so regional
# cinema isn't drowned out by films with global audiences.
MIN_VOTES_ANY_LANGUAGE = 200
MIN_VOTES_ONE_LANGUAGE = 20
DISCOVER_CACHE = timedelta(days=1)
RECOMMENDATIONS_CACHE = timedelta(days=7)
REBUILD_AFTER = timedelta(hours=24)
CHECK_EVERY_SECONDS = 3600
PARALLEL_REQUESTS = 8
# Watched but unrated: a weak positive; also a favourite in Jellyfin: stronger.
WATCHED_LABEL, WATCHED_WEIGHT = 0.6, 0.2
FAVOURITE_LABEL, FAVOURITE_WEIGHT = 0.85, 0.5
# Thumbs on a feed card, for a film the user hasn't seen: "more" or "less like this".
THUMB_LABELS = {"up": 0.8, "down": 0.2}
THUMB_WEIGHT = 0.5
SNOOZE = timedelta(days=30)
# Rescore this long after the user's last rating or feedback, so a burst of clicks
# costs one rescore.
RESCORE_AFTER_SECONDS = 15.0


def user_labels(session: Session, user_id: int) -> list[Label]:
    """The user's ratings as percentiles, plus unrated watches as weaker labels."""
    effective = effective_ratings(user_id)
    ratings = {
        tmdb_id: rating
        for tmdb_id, rating in session.execute(select(effective.c.tmdb_id, effective.c.rating))
    }
    labels = [Label(tmdb_id, value) for tmdb_id, value in percentiles(ratings).items()]
    watched = session.execute(
        select(UserTitle.tmdb_id, func.max(UserTitle.favorite))
        .where(UserTitle.user_id == user_id, UserTitle.watched)
        .group_by(UserTitle.tmdb_id)
    )
    for tmdb_id, favourite in watched:
        if tmdb_id not in ratings:
            labels.append(
                Label(tmdb_id, FAVOURITE_LABEL, FAVOURITE_WEIGHT, explicit=False)
                if favourite
                else Label(tmdb_id, WATCHED_LABEL, WATCHED_WEIGHT, explicit=False)
            )
    known = {label.tmdb_id for label in labels}
    thumbs = session.execute(
        select(Feedback.tmdb_id, Feedback.kind).where(
            Feedback.user_id == user_id, Feedback.kind.in_(THUMB_LABELS)
        )
    )
    for tmdb_id, kind in thumbs:
        if tmdb_id not in known:
            labels.append(Label(tmdb_id, THUMB_LABELS[kind], THUMB_WEIGHT, explicit=False))
    return labels


def seen(session: Session, user_id: int) -> set[int]:
    """Films the user has watched or rated anywhere; they never appear in the feed."""
    return set(
        session.scalars(
            select(UserTitle.tmdb_id).where(
                UserTitle.user_id == user_id,
                or_(UserTitle.watched, UserTitle.rating.is_not(None)),
            )
        )
    )


def hidden(session: Session, user_id: int) -> set[int]:
    """Films the user turned down, said they're not interested in, or snoozed."""
    return set(
        session.scalars(
            select(Feedback.tmdb_id).where(
                Feedback.user_id == user_id,
                or_(
                    Feedback.kind.in_(["down", "dismissed"]),
                    (Feedback.kind == "snoozed") & (Feedback.until > utcnow()),
                ),
            )
        )
    )


def _discover(region: str, language: str | None, providers: list[int]) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "sort_by": "vote_average.desc",
        "vote_count.gte": MIN_VOTES_ONE_LANGUAGE if language else MIN_VOTES_ANY_LANGUAGE,
        "with_original_language": language,
        "include_adult": "false",
    }
    if providers:
        params |= {
            "watch_region": region,
            "with_watch_providers": "|".join(str(p) for p in providers),
            "with_watch_monetization_types": "flatrate|free|ads",
        }
    return [{**params, "page": page} for page in range(1, DISCOVER_PAGES + 1)]


def candidates(session: Session, tmdb: TmdbClient, user: User, labels: list[Label]) -> list[int]:
    """Films to score, most trustworthy sources first, without anything already seen."""
    library = [
        i
        for i in session.scalars(select(LibraryItem.tmdb_id).where(LibraryItem.user_id == user.id))
        if i is not None
    ]
    rated = {label.tmdb_id for label in labels if label.explicit}
    languages = list(
        dict.fromkeys(
            [
                *user.languages,
                *session.scalars(
                    select(Title.original_language)
                    .where(Title.tmdb_id.in_(rated))
                    .group_by(Title.original_language)
                    .order_by(func.count().desc())
                    .limit(3)
                ),
            ]
        )
    )[:5]
    seeds = sorted((label for label in labels if label.explicit), key=lambda label: -label.value)
    requests: list[tuple[str, dict[str, Any] | None, timedelta]] = []
    if user.subscriptions:
        for language in [*languages, None]:
            for params in _discover(user.region, language, user.subscriptions):
                requests.append(("/discover/movie", params, DISCOVER_CACHE))
    for label in seeds[:RECOMMENDATION_SEEDS]:
        requests.append((f"/movie/{label.tmdb_id}/recommendations", None, RECOMMENDATIONS_CACHE))
    for language in languages:
        for params in _discover(user.region, language, []):
            requests.append(("/discover/movie", params, DISCOVER_CACHE))

    def fetch(request: tuple[str, dict[str, Any] | None, timedelta]) -> list[int]:
        path, params, cache = request
        try:
            return [r["id"] for r in tmdb.get(path, params, cache)["results"]]
        except TmdbNotFound:
            return []

    with ThreadPoolExecutor(PARALLEL_REQUESTS) as pool:
        found = [i for ids in pool.map(fetch, requests) for i in ids]
    exclude = seen(session, user.id)
    ordered = dict.fromkeys(i for i in [*library, *found] if i not in exclude)
    return list(ordered)[:MAX_CANDIDATES]


def ai_picks(session: Session, tmdb: TmdbClient, user_id: int) -> dict[int, str]:
    """Ask the configured LLM for films, matched to TMDb, with its reason for each.

    Without an LLM there are none. When it fails, the last build's picks are kept.
    """
    stored = select(AiPick).where(AiPick.user_id == user_id)
    llm = provider_from_settings(session)
    if llm is None:
        session.execute(delete(AiPick).where(AiPick.user_id == user_id))
        return {}
    try:
        suggestions = suggest_films(session, user_id, llm)
    except LlmError:
        log.warning("Couldn't get film suggestions for user %s", user_id, exc_info=True)
        return {p.tmdb_id: p.why for p in session.scalars(stored)}

    def match(title: str, year: int | None) -> int | None:
        try:
            return find_by_title(tmdb, title, year)[0]
        except TmdbNotFound:
            return None

    with ThreadPoolExecutor(PARALLEL_REQUESTS) as pool:
        ids = list(pool.map(match, [s.title for s in suggestions], [s.year for s in suggestions]))
    picks = {i: s.why for i, s in zip(ids, suggestions, strict=True) if i is not None}
    ensure_titles(session, tmdb, list(picks))
    session.execute(delete(AiPick).where(AiPick.user_id == user_id))
    session.add_all(AiPick(user_id=user_id, tmdb_id=i, why=why) for i, why in picks.items())
    return picks


def build_feed(engine: Engine, tmdb_base_url: str, data_dir: Path, user_id: int) -> None:
    with Session(engine) as session:
        user = session.get(User, user_id)
        if user is None:
            return
        state = session.get(FeedBuild, user_id) or FeedBuild(user_id=user_id, status="queued")
        session.add(state)

        def step(text: str) -> None:
            state.status, state.step, state.error = "building", text, None
            session.commit()

        tmdb = client_from_settings(session, engine, tmdb_base_url)
        if tmdb is None:
            state.status, state.step = "failed", None
            state.error = "Add a TMDb API key in Settings first"
            session.commit()
            return
        try:
            step("Finding films")
            labels = user_labels(session, user_id)
            ids = candidates(session, tmdb, user, labels)
            if provider_from_settings(session) is not None:
                step("Asking the AI for ideas")
            picks = ai_picks(session, tmdb, user_id)
            exclude = seen(session, user_id)
            ids = list(dict.fromkeys([*(i for i in picks if i not in exclude), *ids]))
            step(f"Reading details of {len(ids)} films")
            titles = ensure_titles(session, tmdb, [*(label.tmdb_id for label in labels), *ids])
            session.commit()
            ids = [i for i in ids if i in titles]
            if imdb.enabled(session):
                step("Reading IMDb ratings")
                imdb.update_ratings(session, data_dir)
            step("Checking where they stream")
            availability(session, tmdb, ids, user.region)
            step("Matching them to your taste")
            scored = score(titles, labels, ids, user.birth_year, picks)
        except TmdbError as error:
            session.rollback()
            state.status, state.step = "failed", None
            state.error = f"{error}. Try again in a few minutes."
            session.commit()
            return
        _store(session, user_id, scored, picks)
        state.status, state.step, state.error, state.built_at = "ready", None, None, utcnow()
        session.commit()


def rescore_feed(engine: Engine, user_id: int) -> None:
    """Score the feed's films again with the user's latest ratings and feedback."""
    with Session(engine) as session:
        ids = list(
            session.scalars(select(Recommendation.tmdb_id).where(Recommendation.user_id == user_id))
        )
        if not ids:
            return
        user = session.get(User, user_id)
        if user is None:
            return
        labels = user_labels(session, user_id)
        exclude = seen(session, user_id)
        ids = [i for i in ids if i not in exclude]
        wanted = {*ids, *(label.tmdb_id for label in labels)}
        titles = {
            t.tmdb_id: t for t in session.scalars(select(Title).where(Title.tmdb_id.in_(wanted)))
        }
        picks = {
            p.tmdb_id: p.why
            for p in session.scalars(select(AiPick).where(AiPick.user_id == user_id))
        }
        _store(session, user_id, score(titles, labels, ids, user.birth_year, picks), picks)
        session.commit()


def _store(session: Session, user_id: int, scored: Sequence[Scored], picks: dict[int, str]) -> None:
    session.execute(delete(Recommendation).where(Recommendation.user_id == user_id))
    session.add_all(
        Recommendation(
            user_id=user_id,
            tmdb_id=s.tmdb_id,
            score=s.score,
            rank=rank,
            # The LLM's reason first: it speaks to what the user said about films.
            reasons=[f"AI pick: {picks[s.tmdb_id]}", *s.reasons][:2]
            if picks.get(s.tmdb_id)
            else s.reasons,
        )
        for rank, s in enumerate(scored)
    )


class FeedWorker:
    """Builds and rescores feeds one at a time on a background thread, and rebuilds
    each user's feed once it is a day old."""

    def __init__(self, engine: Engine, tmdb_base_url: str, data_dir: Path) -> None:
        self._engine = engine
        self._tmdb_base_url = tmdb_base_url
        self._data_dir = data_dir
        self._queue: queue.Queue[tuple[Job, int]] = queue.Queue()
        self._lock = threading.Lock()
        # Users waiting for a rescore, and the timer that will queue it.
        self._timers: dict[int, threading.Timer] = {}
        self._rescoring: set[int] = set()

    def start(self) -> None:
        with Session(self._engine) as session:
            unfinished = session.scalars(
                select(FeedBuild.user_id).where(FeedBuild.status.in_(["queued", "building"]))
            ).all()
        for user_id in unfinished:
            self._queue.put(("build", user_id))
        threading.Thread(target=self._loop, name="feed", daemon=True).start()

    def request(self, user_id: int) -> None:
        """Rebuild the user's feed from scratch, fetching fresh candidates."""
        with Session(self._engine) as session:
            state = session.get(FeedBuild, user_id) or FeedBuild(user_id=user_id, status="")
            if state.status == "queued":
                return
            # A build already running started from older data, so queue another.
            if state.status != "building":
                state.status, state.error = "queued", None
                session.add(state)
                session.commit()
        self._queue.put(("build", user_id))

    def rescore_soon(self, user_id: int) -> None:
        """Rescore the user's feed once they stop rating and giving feedback for a moment."""
        with self._lock:
            if (pending := self._timers.get(user_id)) is not None:
                pending.cancel()
            timer = threading.Timer(RESCORE_AFTER_SECONDS, self._queue_rescore, [user_id])
            timer.daemon = True
            self._timers[user_id] = timer
            self._rescoring.add(user_id)
            timer.start()

    def rescoring(self, user_id: int) -> bool:
        """Whether a rescore is waiting or running, so the feed's order will change."""
        with self._lock:
            return user_id in self._rescoring

    def wait_until_idle(self) -> None:
        """Run waiting rescores now, then wait for all queued work (for tests)."""
        with self._lock:
            waiting = list(self._timers.items())
        for user_id, timer in waiting:
            timer.cancel()
            self._queue_rescore(user_id, timer)
        self._queue.join()

    def _queue_rescore(self, user_id: int, timer: threading.Timer | None = None) -> None:
        with self._lock:
            # A newer request replaced this timer; that one will queue the rescore.
            if self._timers.get(user_id) is not (timer or threading.current_thread()):
                return
            del self._timers[user_id]
        self._queue.put(("rescore", user_id))

    def _loop(self) -> None:
        while True:
            try:
                job, user_id = self._queue.get(timeout=CHECK_EVERY_SECONDS)
            except queue.Empty:
                self._queue_old_feeds()
                continue
            try:
                if job == "build":
                    build_feed(self._engine, self._tmdb_base_url, self._data_dir, user_id)
                else:
                    self._rescore(user_id)
            except Exception:
                log.exception("Updating the feed of user %s crashed", user_id)
                with Session(self._engine) as session:
                    state = session.get(FeedBuild, user_id)
                    if state is not None:
                        state.status, state.step = "failed", None
                        state.error = "Unexpected error; see the server log"
                        session.commit()
            finally:
                if job == "rescore":
                    with self._lock:
                        if user_id not in self._timers:
                            self._rescoring.discard(user_id)
                self._queue.task_done()

    def _rescore(self, user_id: int) -> None:
        with Session(self._engine) as session:
            state = session.get(FeedBuild, user_id)
            # A queued build reads the latest labels anyway.
            if state is not None and state.status == "queued":
                return
        rescore_feed(self._engine, user_id)

    def _queue_old_feeds(self) -> None:
        with Session(self._engine) as session:
            ready = session.execute(
                select(FeedBuild.user_id, FeedBuild.built_at).where(FeedBuild.status == "ready")
            ).all()
        for user_id, built_at in ready:
            if built_at is None or utcnow() - built_at.replace(tzinfo=UTC) >= REBUILD_AFTER:
                self.request(user_id)
