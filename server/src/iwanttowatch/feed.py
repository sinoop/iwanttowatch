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

import json
import logging
import queue
import threading
from collections.abc import Collection, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, timedelta
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import Engine, delete, func, or_, select
from sqlalchemy.orm import Session

from iwanttowatch import imdb
from iwanttowatch.availability import availability, watchable
from iwanttowatch.catalog import ensure_titles, find_by_title
from iwanttowatch.children import allowed_for, family_tagged_films, library_owners, refresh_limit
from iwanttowatch.db import utcnow
from iwanttowatch.llm import LlmError, LlmProvider, llm_order, provider_from_settings
from iwanttowatch.models import (
    AiPick,
    Availability,
    Feedback,
    FeedBuild,
    LibraryItem,
    Recommendation,
    ShortlistItem,
    Title,
    User,
    UserTitle,
)
from iwanttowatch.moods import moods_for, tag_moods
from iwanttowatch.recommender import Label, Scored, percentile_of, percentiles, score
from iwanttowatch.taste import effective_ratings, review_films
from iwanttowatch.tmdb import TmdbClient, TmdbError, TmdbNotFound, client_from_settings

log = logging.getLogger(__name__)

Job = Literal["build", "rescore"]

MAX_CANDIDATES = 800
# Films from the top of the feed the LLM is asked to rate.
REVIEW_FILMS = 40
# Films tagged with moods in one LLM call after the review, which tags its own films.
MOOD_BATCH = 60
# Top-rated films whose TMDb recommendations become candidates.
RECOMMENDATION_SEEDS = 30
# Each discover search (per language, on the user's services or anywhere) reads pages
# until it has this many films the user hasn't seen, so a language whose best films
# they've mostly watched is searched deeper.
UNSEEN_PER_DISCOVER = 40
MAX_DISCOVER_PAGES = 10
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
    """The user's ratings as percentiles, plus unrated watches as weaker labels.

    Imported ratings are placed among each other. An in-app reaction is placed as an
    imported rating with the same score would be, but isn't added to the pool, so films
    sharing a reaction don't pile up as ties and reshape the scale."""
    effective = effective_ratings(user_id)
    rows = session.execute(
        select(effective.c.tmdb_id, effective.c.rating, effective.c.reaction)
    ).all()
    ratings = {tmdb_id: rating for tmdb_id, rating, _ in rows}
    numeric = {tmdb_id: rating for tmdb_id, rating, reaction in rows if reaction is None}
    labels = [Label(tmdb_id, value) for tmdb_id, value in percentiles(numeric).items()]
    pool = list(numeric.values())
    labels += [
        Label(tmdb_id, percentile_of(pool, rating))
        for tmdb_id, rating, reaction in rows
        if reaction is not None
    ]
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
            known.add(tmdb_id)
    user = session.get(User, user_id)
    if user is not None and user.is_child:
        for tmdb_id in sorted(family_tagged_films(session)):
            if tmdb_id not in known:
                labels.append(Label(tmdb_id, FAVOURITE_LABEL, FAVOURITE_WEIGHT, explicit=False))
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


def shortlisted(session: Session, user_id: int) -> list[int]:
    """The user's shortlist, oldest first. Its films stay candidates so they keep a match."""
    return list(
        session.scalars(
            select(ShortlistItem.tmdb_id)
            .where(ShortlistItem.user_id == user_id)
            .order_by(ShortlistItem.added_at)
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


TMDB_GENRES: dict[str, int] = {
    "Action": 28,
    "Adventure": 12,
    "Animation": 16,
    "Comedy": 35,
    "Crime": 80,
    "Documentary": 99,
    "Drama": 18,
    "Family": 10751,
    "Fantasy": 14,
    "History": 36,
    "Horror": 27,
    "Music": 10402,
    "Mystery": 9648,
    "Romance": 10749,
    "Science Fiction": 878,
    "TV Movie": 10770,
    "Thriller": 53,
    "War": 10752,
    "Western": 37,
}
GENRES_CACHE = timedelta(days=30)


def genre_id(tmdb: TmdbClient, name: str) -> int | None:
    """The TMDb genre ID for a genre name, such as 35 for "Comedy"."""
    lowered = name.strip().lower()
    for genre_name, gid in TMDB_GENRES.items():
        if genre_name.lower() == lowered:
            return gid
    try:
        data = tmdb.get("/genre/movie/list", None, GENRES_CACHE)
        for item in data.get("genres", []):
            if item.get("name", "").strip().lower() == lowered:
                return int(item["id"])
    except TmdbError:
        pass
    return None


def _discover(
    region: str,
    language: str | None,
    providers: list[int],
    genre_id: int | None = None,
    sort_by: str = "vote_average.desc",
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "sort_by": sort_by,
        "vote_count.gte": MIN_VOTES_ONE_LANGUAGE if language else MIN_VOTES_ANY_LANGUAGE,
        "with_original_language": language,
        "include_adult": "false",
    }
    if genre_id is not None:
        params["with_genres"] = str(genre_id)
    if providers:
        params |= {
            "watch_region": region,
            "with_watch_providers": "|".join(str(p) for p in providers),
            # Included in a subscription; free services don't count unless picked.
            "with_watch_monetization_types": "flatrate",
        }
    return params


def candidates(
    session: Session,
    tmdb: TmdbClient,
    user: User,
    labels: list[Label],
    target_language: str | None = None,
    target_genre: str | None = None,
    existing_ids: Collection[int] = (),
) -> list[int]:
    """Films to score, most trustworthy sources first, without anything already seen."""
    exclude = seen(session, user.id)

    # When refreshing for a specific language or genre, discover films with those filters.
    if target_language or target_genre:
        gid = genre_id(tmdb, target_genre) if target_genre else None
        target_requests: list[dict[str, Any]] = []
        if user.subscriptions:
            target_requests += [
                _discover(
                    user.region, target_language, user.subscriptions, gid, "vote_average.desc"
                ),
                _discover(user.region, target_language, user.subscriptions, gid, "popularity.desc"),
            ]
        target_requests += [
            _discover(user.region, target_language, [], gid, "vote_average.desc"),
            _discover(user.region, target_language, [], gid, "popularity.desc"),
        ]
        target_exclude = exclude | set(existing_ids)

        def fetch_target(request: dict[str, Any]) -> list[int]:
            ids: list[int] = []
            for page in range(1, MAX_DISCOVER_PAGES + 1):
                found = tmdb.get("/discover/movie", {**request, "page": page}, DISCOVER_CACHE)
                ids += [r["id"] for r in found["results"]]
                if (
                    not found["results"]
                    or page >= found.get("total_pages", page)
                    or sum(i not in target_exclude for i in ids) >= UNSEEN_PER_DISCOVER
                ):
                    break
            return ids

        with ThreadPoolExecutor(PARALLEL_REQUESTS) as pool:
            found = [i for ids in pool.map(fetch_target, target_requests) for i in ids]
        ordered = dict.fromkeys(i for i in found if i not in exclude)
        return list(ordered)[:MAX_CANDIDATES]

    owners = library_owners(session, user)
    library = [
        i
        for i in session.scalars(select(LibraryItem.tmdb_id).where(LibraryItem.user_id.in_(owners)))
        if i is not None
    ]
    family = sorted(family_tagged_films(session)) if user.is_child else []
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
    seed_ids = [*(label.tmdb_id for label in seeds), *family][:RECOMMENDATION_SEEDS]
    # A discover search's parameters, or a film whose recommendations to read.
    requests: list[dict[str, Any] | int] = []
    if user.subscriptions:
        services = user.subscriptions
        requests += [_discover(user.region, lang, services) for lang in [*languages, None]]
    requests += seed_ids
    requests += [_discover(user.region, lang, []) for lang in languages or [None]]

    def fetch(request: dict[str, Any] | int) -> list[int]:
        if isinstance(request, int):
            try:
                found = tmdb.get(f"/movie/{request}/recommendations", None, RECOMMENDATIONS_CACHE)
            except TmdbNotFound:
                return []
            return [r["id"] for r in found["results"]]
        ids: list[int] = []
        for page in range(1, MAX_DISCOVER_PAGES + 1):
            found = tmdb.get("/discover/movie", {**request, "page": page}, DISCOVER_CACHE)
            ids += [r["id"] for r in found["results"]]
            if (
                not found["results"]
                or page >= found.get("total_pages", page)
                or sum(i not in exclude for i in ids) >= UNSEEN_PER_DISCOVER
            ):
                break
        return ids

    with ThreadPoolExecutor(PARALLEL_REQUESTS) as pool:
        found = [i for ids in pool.map(fetch, requests) for i in ids]
    ordered = dict.fromkeys(i for i in [*library, *family, *found] if i not in exclude)
    return list(ordered)[:MAX_CANDIDATES]


def ai_review(
    session: Session,
    tmdb: TmdbClient,
    user: User,
    scored: Sequence[Scored],
    titles: dict[int, Title],
) -> None:
    """Ask the configured LLM to predict the user's rating for the top of their feed,
    playable films first, and to add a few films of its own; store what it says.

    Without an LLM nothing is stored. When it fails, the last build's review is kept.
    """
    llm = provider_from_settings(session, "suggestions", user.id)
    if llm is None:
        session.execute(delete(AiPick).where(AiPick.user_id == user.id))
        return
    playable = _playable(session, user, [s.tmdb_id for s in scored])
    top = sorted(
        scored,
        key=lambda s: (
            not allowed_for(titles[s.tmdb_id], user.region, user.allowed_certificates),
            s.tmdb_id not in playable,
        ),
    )[:REVIEW_FILMS]
    try:
        review = review_films(session, user.id, llm, [titles[s.tmdb_id] for s in top])
    except LlmError:
        log.warning("Couldn't get the AI's review for user %s", user.id, exc_info=True)
        return
    if review is None:
        session.execute(delete(AiPick).where(AiPick.user_id == user.id))
        return

    def match(title: str, year: int | None) -> int | None:
        try:
            return find_by_title(tmdb, title, year)[0]
        except TmdbNotFound:
            return None

    with ThreadPoolExecutor(PARALLEL_REQUESTS) as pool:
        found = pool.map(
            match, [a.title for a in review.additions], [a.year for a in review.additions]
        )
        added = {i: a for i, a in zip(found, review.additions, strict=True) if i is not None}
    picks = {i: AiPick(user_id=user.id, tmdb_id=i, why=r.why, rating=r.rating, added=False)
             for i, r in review.ratings.items()}  # fmt: skip
    for tmdb_id, addition in added.items():
        picks.setdefault(
            tmdb_id,
            AiPick(user_id=user.id, tmdb_id=tmdb_id, why=addition.why, rating=addition.rating),
        )
    # TMDb lookups write its cache on another connection, so write here only after them.
    ensure_titles(session, tmdb, list(picks))
    for tmdb_id, film in review.ratings.items():
        if film.moods is not None:
            titles[tmdb_id].ai_moods = film.moods
    session.execute(delete(AiPick).where(AiPick.user_id == user.id))
    session.add_all(picks.values())


def tag_feed_moods(
    session: Session, user: User, scored: Sequence[Scored], titles: dict[int, Title]
) -> None:
    """Have the LLM pick moods for the untagged films nearest the top of the feed,
    playable films first, in one call. Moods are kept per film, so each is tagged once."""
    playable = _playable(session, user, [s.tmdb_id for s in scored])
    order = sorted(
        scored,
        key=lambda s: (
            not allowed_for(titles[s.tmdb_id], user.region, user.allowed_certificates),
            s.tmdb_id not in playable,
        ),
    )
    untagged = [titles[s.tmdb_id] for s in order if titles[s.tmdb_id].ai_moods is None]
    llm = provider_from_settings(session, "moods")
    if not untagged or llm is None:
        return
    try:
        tag_moods(llm, untagged[:MOOD_BATCH])
    except LlmError:
        log.warning("Couldn't get mood tags from the AI", exc_info=True)


# Films from the top of the (filtered) feed the LLM chooses from for one request, and
# how many it may pick.
ASK_FILMS = 150
ASK_PICKS = 12
MAX_ASK_WHY_LENGTH = 160

ASK_SYSTEM = f"""You help one person choose a film for a request in their own words, such
as "a light Malayalam comedy under 2 hours". You get the request and a numbered list of
films from their recommendations, with year, original language (ISO 639-1 code), length,
genres, moods, director, and stars. Choose up to {ASK_PICKS} films that clearly fit the
request, best fit first, using these details and what you know about each film. Respect
every limit the request sets, such as language, length, era, or mood, and leave out films
that only partly fit; an empty list is fine. For each, write one short sentence on how it
fits the request, without repeating its title. Answer with only JSON, no markdown, in
this form:
{{"picks": [{{"n": 3, "why": "..."}}]}}"""


def films_for_request(llm: LlmProvider, request: str, films: Sequence[Title]) -> dict[int, str]:
    """The films that fit a request in the user's words, by TMDb ID, with why. The
    prompt holds the request and film details only, nothing about the user's taste."""

    def line(n: int, t: Title) -> str:
        original = f" / {t.original_title}" if t.original_title != t.title else ""
        about = [str(t.year or "?"), t.original_language]
        if t.runtime:
            about.append(f"{t.runtime} min")
        if t.genres:
            about.append(", ".join(t.genres[:3]))
        if moods := moods_for(t):
            about.append(f"feels {', '.join(moods).lower()}")
        if t.directors:
            about.append("dir. " + t.directors[0]["name"])
        if t.cast:
            about.append("with " + ", ".join(p["name"] for p in t.cast[:2]))
        return f"{n}. {t.title}{original} ({'; '.join(about)})"

    prompt = "\n".join(
        [f"Request: {request}", "Films:", *(line(n, t) for n, t in enumerate(films, 1))]
    )
    text = llm.generate(ASK_SYSTEM, prompt, json_reply=True)
    try:
        answer = json.loads(text[text.index("{") : text.rindex("}") + 1])
    except ValueError as error:
        raise LlmError("The LLM's answer wasn't JSON") from error
    picks = answer.get("picks") if isinstance(answer, dict) else None
    if not isinstance(picks, list):
        raise LlmError("The LLM's answer had no list of picks")
    fits: dict[int, str] = {}
    for item in picks:
        n = item.get("n") if isinstance(item, dict) else None
        if isinstance(n, int) and not isinstance(n, bool) and 1 <= n <= len(films):
            why = item.get("why")
            reason = why.strip()[:MAX_ASK_WHY_LENGTH] if isinstance(why, str) else ""
            fits.setdefault(films[n - 1].tmdb_id, reason)
    return dict(list(fits.items())[:ASK_PICKS])


def _playable(session: Session, user: User, ids: list[int]) -> set[int]:
    """The films the user can play now: on their Jellyfin server or their services."""
    owners = library_owners(session, user)
    library = set(
        session.scalars(
            select(LibraryItem.tmdb_id).where(
                LibraryItem.user_id.in_(owners), LibraryItem.tmdb_id.in_(ids)
            )
        )
    )
    rows = session.scalars(
        select(Availability).where(
            Availability.region == user.region, Availability.tmdb_id.in_(ids)
        )
    )
    offers = {
        row.tmdb_id
        for row in rows
        if any(o["kind"] == "flatrate" for o in watchable(row.offers, user.subscriptions))
    }
    return {i for i in library if i is not None} | offers


def ai_percentiles(session: Session, user_id: int, picks: dict[int, AiPick]) -> dict[int, float]:
    """The LLM's predicted ratings as percentiles of the user's own imported ratings, the
    same scale `user_labels` reads reactions against."""
    effective = effective_ratings(user_id)
    ratings = list(
        session.scalars(select(effective.c.rating).where(effective.c.reaction.is_(None)))
    )
    return {i: percentile_of(ratings, p.rating) for i, p in picks.items() if p.rating is not None}


def stored_picks(session: Session, user_id: int) -> dict[int, AiPick]:
    return {p.tmdb_id: p for p in session.scalars(select(AiPick).where(AiPick.user_id == user_id))}


def build_feed(
    engine: Engine,
    tmdb_base_url: str,
    data_dir: Path,
    user_id: int,
    language: str | None = None,
    genre: str | None = None,
) -> None:
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
            if user.is_child and refresh_limit(user, tmdb):
                session.commit()
            step("Finding films")
            labels = user_labels(session, user_id)
            exclude = seen(session, user_id)
            # The LLM's additions from the last build stay candidates until it's asked again.
            added = [p.tmdb_id for p in stored_picks(session, user_id).values() if p.added]
            existing = [
                i
                for i in session.scalars(
                    select(Recommendation.tmdb_id).where(Recommendation.user_id == user_id)
                )
            ]
            new_candidates = candidates(
                session,
                tmdb,
                user,
                labels,
                language,
                genre,
                existing,
            )
            if language or genre:
                candidate_pool = [
                    *new_candidates,
                    *existing,
                    *added,
                    *shortlisted(session, user_id),
                ]
            else:
                candidate_pool = [
                    *new_candidates,
                    *added,
                    *shortlisted(session, user_id),
                ]
            ids = list(dict.fromkeys(candidate_pool))
            ids = [i for i in ids if i not in exclude]
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
            family = family_tagged_films(session) if user.is_child else set()

            def rank(ids: list[int]) -> Sequence[Scored]:
                picks = stored_picks(session, user_id)
                scored = score(
                    titles,
                    labels,
                    ids,
                    user.birth_year,
                    ai_percentiles(session, user_id, picks),
                    child=user.is_child,
                    family_picks=family,
                )
                _store(session, user_id, scored, picks)
                return scored

            # Show the recommender's order at once; the LLM's review can take a while.
            scored = rank(ids)
            if llm_order(session):
                step("Asking the AI to review your picks")
                ai_review(session, tmdb, user, scored, titles)
                session.commit()
                step("Asking the AI for mood tags")
                tag_feed_moods(session, user, scored, titles)
                session.commit()
                new = [i for i in stored_picks(session, user_id) if i not in titles]
                titles |= ensure_titles(session, tmdb, new)
                new = [
                    i
                    for i in stored_picks(session, user_id)
                    if i not in ids and i not in exclude and i in titles
                ]
                availability(session, tmdb, new, user.region)
                ids = [*ids, *new]
            else:
                session.execute(delete(AiPick).where(AiPick.user_id == user_id))
            rank(ids)
        except TmdbError as error:
            session.rollback()
            state.status, state.step = "failed", None
            state.error = f"{error}. Try again in a few minutes."
            session.commit()
            return
        state.status, state.step, state.error, state.built_at = "ready", None, None, utcnow()
        session.commit()


def rescore_feed(engine: Engine, user_id: int) -> None:
    """Score the feed's films again with the user's latest ratings and feedback."""
    with Session(engine) as session:
        user = session.get(User, user_id)
        if user is None:
            return
        ids = feed_films(session, user)
        if not ids:
            return
        _store(session, user_id, score_films(session, user, ids), stored_picks(session, user_id))
        session.commit()


def feed_films(session: Session, user: User) -> list[int]:
    """The films a rescore scores: the feed's, a child's family picks, and the shortlist."""
    family = family_tagged_films(session) if user.is_child else set()
    return list(
        dict.fromkeys(
            [
                *session.scalars(
                    select(Recommendation.tmdb_id).where(Recommendation.user_id == user.id)
                ),
                *sorted(family),
                *shortlisted(session, user.id),
            ]
        )
    )


def score_films(session: Session, user: User, ids: list[int]) -> list[Scored]:
    """Score films the user hasn't seen as a rescore does. Scores depend on the films
    scored together, so score feed_films to match the feed."""
    family = family_tagged_films(session) if user.is_child else set()
    labels = user_labels(session, user.id)
    exclude = seen(session, user.id)
    ids = [i for i in ids if i not in exclude]
    wanted = {*ids, *(label.tmdb_id for label in labels)}
    titles = {t.tmdb_id: t for t in session.scalars(select(Title).where(Title.tmdb_id.in_(wanted)))}
    ids = [i for i in ids if i in titles]
    return score(
        titles,
        labels,
        ids,
        user.birth_year,
        ai_percentiles(session, user.id, stored_picks(session, user.id)),
        child=user.is_child,
        family_picks=family,
    )


def _store(
    session: Session, user_id: int, scored: Sequence[Scored], picks: dict[int, AiPick]
) -> None:
    session.execute(delete(Recommendation).where(Recommendation.user_id == user_id))
    session.add_all(
        Recommendation(
            user_id=user_id,
            tmdb_id=s.tmdb_id,
            score=s.score,
            rank=rank,
            reasons=feed_reasons(s, picks),
        )
        for rank, s in enumerate(scored)
    )


def feed_reasons(scored: Scored, picks: dict[int, AiPick]) -> list[str]:
    """Why a film suits the user: the LLM's reason first, as it speaks to what the user
    said about films."""
    if (pick := picks.get(scored.tmdb_id)) and pick.why:
        return [_ai_reason(pick), *scored.reasons][:2]
    return scored.reasons


def _ai_reason(pick: AiPick) -> str:
    label = "AI pick" if pick.added else "AI"
    if pick.rating is None:
        return f"{label}: {pick.why}"
    return f"{label}, expects {pick.rating:g}/10: {pick.why}"


class FeedWorker:
    """Builds and rescores feeds one at a time on a background thread, and rebuilds
    each user's feed once it is a day old."""

    def __init__(self, engine: Engine, tmdb_base_url: str, data_dir: Path) -> None:
        self._engine = engine
        self._tmdb_base_url = tmdb_base_url
        self._data_dir = data_dir
        self._queue: queue.Queue[tuple[Any, ...]] = queue.Queue()
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
            self._queue.put(("build", user_id, None, None))
        threading.Thread(target=self._loop, name="feed", daemon=True).start()

    def request(self, user_id: int, language: str | None = None, genre: str | None = None) -> None:
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
        self._queue.put(("build", user_id, language, genre))

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
                item = self._queue.get(timeout=CHECK_EVERY_SECONDS)
            except queue.Empty:
                self._queue_old_feeds()
                continue
            job, user_id = item[0], item[1]
            try:
                if job == "build":
                    language = item[2] if len(item) > 2 else None
                    genre = item[3] if len(item) > 3 else None
                    build_feed(
                        self._engine,
                        self._tmdb_base_url,
                        self._data_dir,
                        user_id,
                        language=language,
                        genre=genre,
                    )
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
