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
from datetime import UTC, date, timedelta
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import Engine, delete, func, or_, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session, defer

from iwanttowatch import imdb
from iwanttowatch.availability import availability, watchable
from iwanttowatch.catalog import ensure_titles, find_by_title
from iwanttowatch.children import allowed_for, family_tagged_films, library_owners, refresh_limit
from iwanttowatch.db import utcnow
from iwanttowatch.llm import LlmError, LlmProvider, llm_order, provider_from_settings
from iwanttowatch.models import (
    AiPick,
    Availability,
    FavoritePerson,
    Feedback,
    FeedBuild,
    LibraryItem,
    OutlierReview,
    Recommendation,
    ScopedFeedBuild,
    ScopedFeedItem,
    ShortlistItem,
    Title,
    User,
    UserTitle,
)
from iwanttowatch.moods import moods_for, tag_moods
from iwanttowatch.recommender import Label, Scored, percentile_of, score, score_rated
from iwanttowatch.taste import (
    REACTION_PERCENTILES,
    clash_model_signals,
    effective_ratings,
    rating_to_reaction,
    review_films,
)
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
CONFIRMED_DISLIKE_WEIGHT = 1.5
SNOOZE = timedelta(days=30)
# Rescore this long after the user's last rating or feedback, so a burst of clicks
# costs one rescore.
RESCORE_AFTER_SECONDS = 15.0


def user_labels(session: Session, user_id: int) -> list[Label]:
    """The user's ratings as percentiles, plus unrated watches as weaker labels.

    Reactions (both in-app and imported) map to discrete percentile weights (Loved: 0.95,
    Liked: 0.70, Disliked: 0.15) so they never collide or distort the scale."""
    effective = effective_ratings(user_id)
    rows = session.execute(
        select(effective.c.tmdb_id, effective.c.rating, effective.c.reaction)
    ).all()
    confirmed_outliers = set(
        session.scalars(select(OutlierReview.tmdb_id).where(OutlierReview.user_id == user_id))
    )
    ratings: set[int] = set()
    labels: list[Label] = []
    for tmdb_id, rating, reaction in rows:
        ratings.add(tmdb_id)
        rx = reaction or (rating_to_reaction(rating) if rating is not None else None)
        if rx in REACTION_PERCENTILES:
            weight = (
                CONFIRMED_DISLIKE_WEIGHT
                if (rx == "disliked" and tmdb_id in confirmed_outliers)
                else 1.0
            )
            labels.append(Label(tmdb_id, REACTION_PERCENTILES[rx], weight=weight, explicit=True))
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
DOCUMENTARY_GENRE = "Documentary"
DOCUMENTARY_GENRE_ID = TMDB_GENRES[DOCUMENTARY_GENRE]

STANDUP_KEYWORDS = {
    "stand-up comedy",
    "stand-up special",
    "stand-up",
    "stand up comedy",
    "comedy special",
    "stand up special",
}

CONCERT_KEYWORDS = {
    "concert film",
    "concert",
    "live concert",
    "music tour",
    "stage performance",
    "live performance",
    "theatre recording",
    "stage production",
    "opera",
    "broadway",
}

BEHIND_THE_SCENES_KEYWORDS = {
    "making of",
    "behind the scenes",
    "featurette",
    "outtakes",
    "bloopers",
    "interview",
}

SPORTS_KEYWORDS = {
    "professional wrestling",
    "wrestling",
    "wwe",
    "mma",
    "ufc",
    "sports event",
}

SHORT_KEYWORDS = {
    "short film",
    "animated short",
    "short",
}

# TMDb keyword IDs to exclude for "movies" using pipe (OR logic in without_keywords):
# 9716 (stand-up comedy), 6078 (concert), 6029 (concert film), 10683 (making of),
# 1595 (short film), 6075 (sport / wrestling)
NON_MOVIE_KEYWORD_IDS = "9716|6078|6029|10683|1595|6075"
STANDUP_KEYWORD_ID = 9716
CONCERT_KEYWORD_IDS = "6078|6029"
MIN_MOVIE_RUNTIME = 40


def is_documentary(title: Title) -> bool:
    """Whether a film is a documentary. Documentaries are omitted from feed recommendations."""
    return any(g.strip().lower() == "documentary" for g in title.genres)


def is_standup(title: Title) -> bool:
    """Whether a title is a stand-up comedy special."""
    return any(k.strip().lower() in STANDUP_KEYWORDS for k in title.keywords)


def is_concert(title: Title) -> bool:
    """Whether a title is a concert film, live music performance, or stage recording."""
    return any(k.strip().lower() in CONCERT_KEYWORDS for k in title.keywords)


def is_behind_the_scenes(title: Title) -> bool:
    """Whether a title is a making-of or featurette."""
    return any(k.strip().lower() in BEHIND_THE_SCENES_KEYWORDS for k in title.keywords)


def is_sports(title: Title) -> bool:
    """Whether a title is a sports event, wrestling, or combat sports broadcast."""
    return any(k.strip().lower() in SPORTS_KEYWORDS for k in title.keywords)


def is_short(title: Title) -> bool:
    """Whether a title is a short film (< 40 min runtime or tagged as short film)."""
    if title.runtime is not None and title.runtime < MIN_MOVIE_RUNTIME:
        return True
    return any(k.strip().lower() in SHORT_KEYWORDS for k in title.keywords)


def is_non_movie(title: Title) -> bool:
    """Whether a title is a documentary, stand-up special, concert, behind-the-scenes,
    sports event, or short film."""
    return (
        is_documentary(title)
        or is_standup(title)
        or is_concert(title)
        or is_behind_the_scenes(title)
        or is_sports(title)
        or is_short(title)
    )


def matches_content_type(title: Title, content_type: str = "movies") -> bool:
    """Whether a title matches the selected content type."""
    if content_type == "movies":
        return not is_non_movie(title)
    if content_type == "standup":
        return is_standup(title)
    if content_type == "concerts":
        return is_concert(title)
    if content_type == "all":
        return True
    return not is_non_movie(title)


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
    content_type: str = "movies",
    with_people: int | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "sort_by": sort_by,
        "vote_count.gte": MIN_VOTES_ONE_LANGUAGE if language else MIN_VOTES_ANY_LANGUAGE,
        "with_original_language": language,
        "include_adult": "false",
    }
    if content_type == "movies":
        params["without_genres"] = str(DOCUMENTARY_GENRE_ID)
        params["without_keywords"] = NON_MOVIE_KEYWORD_IDS
        params["with_runtime.gte"] = MIN_MOVIE_RUNTIME
    elif content_type == "standup":
        params["with_keywords"] = str(STANDUP_KEYWORD_ID)
    elif content_type == "concerts":
        params["with_keywords"] = CONCERT_KEYWORD_IDS

    if with_people is not None:
        params["with_people"] = str(with_people)
        params["vote_count.gte"] = 10
    if genre_id is not None:
        params["with_genres"] = str(genre_id)
        if genre_id == DOCUMENTARY_GENRE_ID:
            params.pop("without_genres", None)
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
    target_content_type: str | None = None,
) -> list[int]:
    """Films to score, most trustworthy sources first, without anything already seen."""
    exclude = seen(session, user.id)
    content_type = (
        target_content_type or getattr(user, "default_content_type", "movies") or "movies"
    )

    # When refreshing for a specific language, genre, or content type, discover films.
    if target_language or target_genre or target_content_type:
        if (
            target_genre
            and target_genre.strip().lower() == "documentary"
            and content_type == "movies"
        ):
            return []
        gid = genre_id(tmdb, target_genre) if target_genre else None
        target_requests: list[dict[str, Any]] = []
        if user.subscriptions:
            target_requests += [
                _discover(
                    user.region,
                    target_language,
                    user.subscriptions,
                    gid,
                    "vote_average.desc",
                    content_type,
                ),
                _discover(
                    user.region,
                    target_language,
                    user.subscriptions,
                    gid,
                    "popularity.desc",
                    content_type,
                ),
            ]
        target_requests += [
            _discover(user.region, target_language, [], gid, "vote_average.desc", content_type),
            _discover(user.region, target_language, [], gid, "popularity.desc", content_type),
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
    languages = preferred_languages(session, user, labels)
    seeds = sorted((label for label in labels if label.explicit), key=lambda label: -label.value)
    seed_ids = [*(label.tmdb_id for label in seeds), *family][:RECOMMENDATION_SEEDS]
    # A discover search's parameters, or a film whose recommendations to read.
    requests: list[dict[str, Any] | int] = []
    if user.subscriptions:
        services = user.subscriptions
        requests += [
            _discover(user.region, lang, services, content_type=content_type)
            for lang in [*languages, None]
        ]
    requests += seed_ids
    lang_filters: list[str | None] = list(languages) or [None]
    requests += [
        _discover(user.region, lang, [], content_type=content_type) for lang in lang_filters
    ]
    fav_people = list(
        session.scalars(select(FavoritePerson.person_id).where(FavoritePerson.user_id == user.id))
    )
    for pid in fav_people[:5]:
        if user.subscriptions:
            requests.append(
                _discover(
                    user.region,
                    None,
                    user.subscriptions,
                    with_people=pid,
                    content_type=content_type,
                )
            )
        requests.append(
            _discover(user.region, None, [], with_people=pid, content_type=content_type)
        )

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


SCOPED_DISCOVER_CACHE = timedelta(hours=6)
SCOPED_DISCOVER_PAGES = 2


def preferred_languages(
    session: Session, user: User, labels: Sequence[Label] | None = None
) -> list[str]:
    """Return the user's configured languages (in preference order) plus top rated languages."""
    if labels is None:
        labels = user_labels(session, user.id)
    rated = {label.tmdb_id for label in labels if label.explicit}
    inferred = (
        list(
            session.scalars(
                select(Title.original_language)
                .where(Title.tmdb_id.in_(rated))
                .group_by(Title.original_language)
                .order_by(func.count().desc())
                .limit(3)
            )
        )
        if rated
        else []
    )
    return list(dict.fromkeys([*(user.languages or []), *inferred]))


def theatrical_candidates(
    session: Session, tmdb: TmdbClient, user: User, *, force_refresh: bool = False
) -> list[int]:
    """Gather unseen, non-library theatrical releases in the user's region."""
    target_region = (user.region or "US").upper()
    cache_ttl = timedelta(0) if force_refresh else SCOPED_DISCOVER_CACHE
    owners = library_owners(session, user)
    in_library = set(
        session.scalars(select(LibraryItem.tmdb_id).where(LibraryItem.user_id.in_(owners)))
    )
    user_seen = seen(session, user.id)
    found: list[int] = []

    for page in range(1, SCOPED_DISCOVER_PAGES + 1):
        try:
            now_playing = tmdb.get(
                "/movie/now_playing",
                {"region": target_region, "page": page},
                cache_for=cache_ttl,
            )
            for item in now_playing.get("results", []):
                if "id" in item:
                    found.append(int(item["id"]))
            if not now_playing.get("results") or page >= now_playing.get("total_pages", page):
                break
        except TmdbError as err:
            log.warning("Could not fetch TMDb now_playing for %s: %s", target_region, err)
            break

    doc_id = str(genre_id(tmdb, DOCUMENTARY_GENRE) or 99)
    today = date.today()
    start_date = (today - timedelta(days=90)).isoformat()
    end_date = (today + timedelta(days=21)).isoformat()
    base_discover_params: dict[str, Any] = {
        "region": target_region,
        "with_release_type": "2|3",
        "primary_release_date.gte": start_date,
        "primary_release_date.lte": end_date,
        "sort_by": "popularity.desc",
        "without_genres": doc_id,
        "include_adult": "false",
    }
    languages = preferred_languages(session, user)
    discover_queries: list[dict[str, Any]] = [
        base_discover_params,
        *({**base_discover_params, "with_original_language": lang} for lang in languages),
    ]
    for params in discover_queries:
        for page in range(1, SCOPED_DISCOVER_PAGES + 1):
            try:
                discover_data = tmdb.get(
                    "/discover/movie",
                    {**params, "page": page},
                    cache_for=cache_ttl,
                )
                for item in discover_data.get("results", []):
                    if "id" in item:
                        found.append(int(item["id"]))
                if not discover_data.get("results") or page >= discover_data.get(
                    "total_pages", page
                ):
                    break
            except TmdbError as err:
                log.warning(
                    "Could not fetch TMDb theatrical discover for %s: %s", target_region, err
                )
                break

    unique = [tid for tid in dict.fromkeys(found) if tid not in user_seen and tid not in in_library]
    return unique[:MAX_CANDIDATES]


def recently_added_candidates(
    session: Session, tmdb: TmdbClient, user: User, *, force_refresh: bool = False
) -> list[int]:
    """Gather unseen films recently released to streaming in the user's region."""
    days = max(1, min(30, getattr(user, "recently_added_days", 7) or 7))
    today = date.today()
    start_date = (today - timedelta(days=days)).isoformat()
    end_date = today.isoformat()
    target_region = (user.region or "US").upper()
    cache_ttl = timedelta(0) if force_refresh else SCOPED_DISCOVER_CACHE
    providers = user.subscriptions

    doc_id = str(genre_id(tmdb, DOCUMENTARY_GENRE) or 99)
    base_params: dict[str, Any] = {
        "region": target_region,
        "watch_region": target_region,
        "with_watch_monetization_types": "flatrate|free|ads",
        "sort_by": "popularity.desc",
        "without_genres": doc_id,
        "include_adult": "false",
    }
    if providers:
        base_params["with_watch_providers"] = "|".join(str(p) for p in providers)

    found: list[int] = []
    for page in range(1, SCOPED_DISCOVER_PAGES + 1):
        try:
            data = tmdb.get(
                "/discover/movie",
                {
                    **base_params,
                    "with_release_type": "4|5|6",
                    "release_date.gte": start_date,
                    "release_date.lte": end_date,
                    "page": page,
                },
                cache_for=cache_ttl,
            )
            for item in data.get("results", []):
                if "id" in item:
                    found.append(int(item["id"]))
            if not data.get("results") or page >= data.get("total_pages", page):
                break
        except TmdbError as err:
            log.warning("Could not fetch TMDb recently added streaming discover: %s", err)
            break

    if len(found) < 5:
        for page in range(1, SCOPED_DISCOVER_PAGES + 1):
            try:
                alt_data = tmdb.get(
                    "/discover/movie",
                    {
                        **base_params,
                        "primary_release_date.gte": start_date,
                        "primary_release_date.lte": end_date,
                        "page": page,
                    },
                    cache_for=cache_ttl,
                )
                for item in alt_data.get("results", []):
                    if "id" in item:
                        found.append(int(item["id"]))
                if not alt_data.get("results") or page >= alt_data.get("total_pages", page):
                    break
            except TmdbError as err:
                log.warning("Could not fetch TMDb primary_release_date discover: %s", err)
                break

    user_seen = seen(session, user.id)
    unique = [tid for tid in dict.fromkeys(found) if tid not in user_seen]
    return unique[:MAX_CANDIDATES]


def ai_review(
    session: Session,
    tmdb: TmdbClient,
    user: User,
    scored: Sequence[Scored],
    titles: dict[int, Title],
    *,
    add_suggestions: bool = True,
    replace_all: bool = True,
) -> None:
    """Ask the configured LLM to predict the user's rating for the top of their feed,
    playable films first, and optionally add a few films of its own; store what it says.

    Without an LLM nothing is stored. When it fails, the last build's review is kept.
    """
    llm = provider_from_settings(session, "suggestions", user.id)
    if llm is None:
        if replace_all:
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
        if replace_all:
            session.execute(delete(AiPick).where(AiPick.user_id == user.id))
        return

    added: dict[int, Any] = {}
    if add_suggestions and review.additions:

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
        if film.moods is not None and tmdb_id in titles:
            titles[tmdb_id].ai_moods = film.moods
    if replace_all:
        session.execute(delete(AiPick).where(AiPick.user_id == user.id))
        session.add_all(picks.values())
    else:
        for pick in picks.values():
            session.execute(
                insert(AiPick)
                .values(
                    user_id=pick.user_id,
                    tmdb_id=pick.tmdb_id,
                    why=pick.why,
                    rating=pick.rating,
                    added=False,
                )
                .on_conflict_do_update(
                    index_elements=[AiPick.user_id, AiPick.tmdb_id],
                    set_={"why": pick.why, "rating": pick.rating},
                )
            )


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
        session.scalars(select(effective.c.rating).where(effective.c.rating.is_not(None)))
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
    content_type: str | None = None,
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
            active_content_type = (
                content_type or getattr(user, "default_content_type", "movies") or "movies"
            )
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
                content_type,
            )
            if language or genre or content_type:
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
            saved_ids = set(shortlisted(session, user_id))
            ids = [
                i
                for i in ids
                if i in titles
                and (i in saved_ids or matches_content_type(titles[i], active_content_type))
            ]
            if imdb.enabled(session):
                step("Reading IMDb ratings")
                imdb.update_ratings(session, data_dir)
            step("Checking where they stream")
            availability(session, tmdb, ids, user.region)
            step("Matching them to your taste")
            family = family_tagged_films(session) if user.is_child else set()

            def rank(ids: list[int]) -> Sequence[Scored]:
                picks = stored_picks(session, user_id)
                fav_people = set(
                    session.scalars(
                        select(FavoritePerson.person_id).where(FavoritePerson.user_id == user_id)
                    )
                )
                dampened_outliers, feature_adjustments, rated_tags = clash_model_signals(
                    session, user_id
                )
                scored = score(
                    titles,
                    labels,
                    ids,
                    user.birth_year,
                    ai_percentiles(session, user_id, picks),
                    child=user.is_child,
                    family_picks=family,
                    favorite_people=fav_people,
                    dampened_outliers=dampened_outliers,
                    feature_adjustments=feature_adjustments,
                    rated_tags=rated_tags,
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
                    if i not in ids
                    and i not in exclude
                    and i in titles
                    and matches_content_type(titles[i], active_content_type)
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
        if not user.is_child:
            _maybe_run_auto_downloader(session, tmdb, user)


def _maybe_run_auto_downloader(session: Session, tmdb: TmdbClient, user: User) -> None:
    """Run the background Radarr auto-downloader after a feed build when enabled."""
    from iwanttowatch.radar import is_auto_download_enabled, run_auto_downloader

    try:
        if is_auto_download_enabled(session):
            run_auto_downloader(session, tmdb, user)
    except Exception as err:
        log.warning("Background auto-downloader failed for user %s: %s", user.id, err)


def build_scoped_feed(
    engine: Engine,
    tmdb_base_url: str,
    data_dir: Path,
    user_id: int,
    scope: str,
    *,
    force_refresh: bool = False,
) -> None:
    """Build a scoped discovery feed ("theatrical" or "recently_added") with taste scoring
    and AI review/ordering, without modifying the user's main Recommendation feed."""
    with Session(engine) as session:
        user = session.get(User, user_id)
        if user is None:
            return
        state = session.get(ScopedFeedBuild, (user_id, scope)) or ScopedFeedBuild(
            user_id=user_id, scope=scope, status="queued"
        )
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
            if scope == "theatrical":
                ids = theatrical_candidates(session, tmdb, user, force_refresh=force_refresh)
            else:
                ids = recently_added_candidates(session, tmdb, user, force_refresh=force_refresh)

            step(f"Reading details of {len(ids)} films")
            titles = ensure_titles(session, tmdb, [*(label.tmdb_id for label in labels), *ids])
            session.commit()
            ids = [i for i in ids if i in titles and not is_non_movie(titles[i])]
            if imdb.enabled(session):
                step("Reading IMDb ratings")
                imdb.update_ratings(session, data_dir)

            if scope == "recently_added":
                step("Checking where they stream")
                places = availability(session, tmdb, ids, user.region)
                streamable: list[int] = []
                for tid in ids:
                    row = places.get(tid)
                    if row is None:
                        continue
                    if user.subscriptions:
                        if watchable(row.offers, user.subscriptions):
                            streamable.append(tid)
                    elif any(o["kind"] in ("flatrate", "free", "ads") for o in row.offers):
                        streamable.append(tid)
                ids = streamable

            step("Matching them to your taste")
            family = family_tagged_films(session) if user.is_child else set()

            def rank(rank_ids: list[int]) -> Sequence[Scored]:
                picks = stored_picks(session, user_id)
                fav_people = set(
                    session.scalars(
                        select(FavoritePerson.person_id).where(FavoritePerson.user_id == user_id)
                    )
                )
                dampened_outliers, feature_adjustments, rated_tags = clash_model_signals(
                    session, user_id
                )
                scored = score(
                    titles,
                    labels,
                    rank_ids,
                    user.birth_year,
                    ai_percentiles(session, user_id, picks),
                    child=user.is_child,
                    family_picks=family,
                    favorite_people=fav_people,
                    dampened_outliers=dampened_outliers,
                    feature_adjustments=feature_adjustments,
                    rated_tags=rated_tags,
                )
                _store_scoped(session, user_id, scope, scored, picks)
                return scored

            scored = rank(ids)
            if llm_order(session) and scored:
                step("Asking the AI to review your picks")
                ai_review(
                    session, tmdb, user, scored, titles, add_suggestions=False, replace_all=False
                )
                session.commit()
                step("Asking the AI for mood tags")
                tag_feed_moods(session, user, scored, titles)
                session.commit()
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


_DEFERRED_TITLE_COLS = (
    defer(Title.translations),
    defer(Title.alternative_titles),
    defer(Title.overview),
    defer(Title.tagline),
    defer(Title.certifications),
    defer(Title.spoken_languages),
    defer(Title.origin_countries),
    defer(Title.themes_note),
    defer(Title.ai_moods),
)


def score_films(
    session: Session,
    user: User,
    ids: list[int],
    only_candidates: list[int] | None = None,
) -> list[Scored]:
    """Score films the user hasn't seen as a rescore does. Scores depend on the films
    scored together, so score feed_films to match the feed."""
    family = family_tagged_films(session) if user.is_child else set()
    labels = user_labels(session, user.id)
    exclude = seen(session, user.id)
    ids = [i for i in ids if i not in exclude]
    wanted = {*ids, *(label.tmdb_id for label in labels)}
    titles = {
        t.tmdb_id: t
        for t in session.scalars(
            select(Title).where(Title.tmdb_id.in_(wanted)).options(*_DEFERRED_TITLE_COLS)
        )
    }
    active_content_type = getattr(user, "default_content_type", "movies") or "movies"
    keep = set(only_candidates or ()) | set(shortlisted(session, user.id))
    ids = [
        i
        for i in ids
        if i in titles and (i in keep or matches_content_type(titles[i], active_content_type))
    ]
    fav_people = set(
        session.scalars(select(FavoritePerson.person_id).where(FavoritePerson.user_id == user.id))
    )
    dampened_outliers, feature_adjustments, rated_tags = clash_model_signals(session, user.id)
    return score(
        titles,
        labels,
        ids,
        user.birth_year,
        ai_percentiles(session, user.id, stored_picks(session, user.id)),
        child=user.is_child,
        family_picks=family,
        favorite_people=fav_people,
        only_candidates=only_candidates,
        dampened_outliers=dampened_outliers,
        feature_adjustments=feature_adjustments,
        rated_tags=rated_tags,
    )


_RATED_MATCHES_CACHE: dict[int, tuple[int, Any, dict[int, int]]] = {}
_SINGLE_SCORE_CACHE: dict[tuple[int, int, int], tuple[float, list[str]]] = {}


def _clear_single_score_cache(user_id: int) -> None:
    stale = [key for key in list(_SINGLE_SCORE_CACHE) if key[1] == user_id]
    for key in stale:
        _SINGLE_SCORE_CACHE.pop(key, None)


def clear_user_rated_matches_cache(user_id: int) -> None:
    _RATED_MATCHES_CACHE.pop(user_id, None)
    _clear_single_score_cache(user_id)


def cached_single_scores(
    session: Session,
    user_id: int,
    tmdb_ids: Sequence[int],
) -> dict[int, tuple[float, list[str]]]:
    """Return in-memory cached (score, reasons) pairs for already-scored non-feed titles."""
    bind_id = id(session.get_bind())
    out: dict[int, tuple[float, list[str]]] = {}
    for tid in tmdb_ids:
        cached = _SINGLE_SCORE_CACHE.get((bind_id, user_id, tid))
        if cached is not None:
            out[tid] = cached
    return out


def score_candidate_films(
    session: Session,
    user: User,
    tmdb_ids: Sequence[int],
) -> dict[int, tuple[float, list[str]]]:
    """Score multiple unseen films in one pass against the user's feed pool, caching
    individual results in _SINGLE_SCORE_CACHE."""
    unique_ids = list(dict.fromkeys(tmdb_ids))
    if not unique_ids:
        return {}
    bind_id = id(session.get_bind())
    out = cached_single_scores(session, user.id, unique_ids)
    missing = [tid for tid in unique_ids if tid not in out]
    if missing:
        picks = stored_picks(session, user.id)
        scored_list = score_films(
            session,
            user,
            [*feed_films(session, user), *missing],
            only_candidates=missing,
        )
        if len(_SINGLE_SCORE_CACHE) + len(scored_list) > 2048:
            _SINGLE_SCORE_CACHE.clear()
        for scored in scored_list:
            reasons = feed_reasons(scored, picks)
            result = (scored.score, reasons)
            _SINGLE_SCORE_CACHE[(bind_id, user.id, scored.tmdb_id)] = result
            out[scored.tmdb_id] = result
    return out


def score_single_film(
    session: Session,
    user: User,
    tmdb_id: int,
) -> tuple[float, list[str]] | None:
    """Return (score, reasons) for a single unseen film against the user's feed pool,
    using an in-memory cache so opening a title and shortlisting it only scores once."""
    return score_candidate_films(session, user, [tmdb_id]).get(tmdb_id)


def ensure_shortlist_recommendation(session: Session, user: User, tmdb_id: int) -> bool:
    """Ensure a shortlisted film has a Recommendation row immediately so it appears in the
    shortlist and feed right away without waiting for a delayed background rescore."""
    if session.get(Recommendation, (user.id, tmdb_id)) is not None:
        return True
    if tmdb_id in seen(session, user.id):
        return False
    res = score_single_film(session, user, tmdb_id)
    if res is None:
        return False
    score_val, reasons = res
    higher_rank = session.scalar(
        select(func.min(Recommendation.rank)).where(
            Recommendation.user_id == user.id,
            Recommendation.score <= score_val,
        )
    )
    if higher_rank is not None:
        rank = int(higher_rank)
    else:
        max_rank = session.scalar(
            select(func.max(Recommendation.rank)).where(Recommendation.user_id == user.id)
        )
        rank = int(max_rank) + 1 if max_rank is not None else 0
    session.execute(
        insert(Recommendation)
        .values(
            user_id=user.id,
            tmdb_id=tmdb_id,
            score=score_val,
            rank=rank,
            reasons=reasons,
        )
        .on_conflict_do_nothing(index_elements=[Recommendation.user_id, Recommendation.tmdb_id])
    )
    session.commit()
    return True


def user_rated_matches(session: Session, user: User) -> dict[int, int]:
    """Calculate predicted match percentages (0–100) for films rated by the user."""
    stats = session.execute(
        select(func.count(UserTitle.id), func.max(UserTitle.updated_at)).where(
            UserTitle.user_id == user.id, UserTitle.rating.is_not(None)
        )
    ).one()
    count, last_updated = stats[0], stats[1]
    cached = _RATED_MATCHES_CACHE.get(user.id)
    if cached is not None and cached[0] == count and cached[1] == last_updated:
        return cached[2]

    labels = user_labels(session, user.id)
    explicit_ids = {label.tmdb_id for label in labels if label.explicit}
    if not explicit_ids:
        _RATED_MATCHES_CACHE[user.id] = (count, last_updated, {})
        return {}

    all_ids = {label.tmdb_id for label in labels}
    titles = {
        t.tmdb_id: t
        for t in session.scalars(
            select(Title).where(Title.tmdb_id.in_(all_ids)).options(*_DEFERRED_TITLE_COLS)
        )
    }
    fav_people = set(
        session.scalars(select(FavoritePerson.person_id).where(FavoritePerson.user_id == user.id))
    )
    scores = score_rated(
        titles,
        labels,
        birth_year=user.birth_year,
        favorite_people=fav_people,
    )
    matches = {tmdb_id: round(s * 100) for tmdb_id, s in scores.items()}
    _RATED_MATCHES_CACHE[user.id] = (count, last_updated, matches)
    return matches


def _store(
    session: Session, user_id: int, scored: Sequence[Scored], picks: dict[int, AiPick]
) -> None:
    _clear_single_score_cache(user_id)
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


def _store_scoped(
    session: Session,
    user_id: int,
    scope: str,
    scored: Sequence[Scored],
    picks: dict[int, AiPick],
) -> None:
    session.execute(
        delete(ScopedFeedItem).where(
            ScopedFeedItem.user_id == user_id, ScopedFeedItem.scope == scope
        )
    )
    session.add_all(
        ScopedFeedItem(
            user_id=user_id,
            scope=scope,
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
            unfinished_scoped = session.execute(
                select(ScopedFeedBuild.user_id, ScopedFeedBuild.scope).where(
                    ScopedFeedBuild.status.in_(["queued", "building"])
                )
            ).all()
        for user_id in unfinished:
            self._queue.put(("build", user_id, None, None, None, "main", False))
        for user_id, scope in unfinished_scoped:
            self._queue.put(("build", user_id, None, None, None, scope, False))
        threading.Thread(target=self._loop, name="feed", daemon=True).start()

    def request(
        self,
        user_id: int,
        language: str | None = None,
        genre: str | None = None,
        content_type: str | None = None,
        scope: str = "main",
        force_refresh: bool = False,
    ) -> None:
        """Rebuild the user's feed (or scoped filter) from scratch, fetching fresh candidates."""
        _clear_single_score_cache(user_id)
        with Session(self._engine) as session:
            if scope == "main":
                state: FeedBuild | ScopedFeedBuild = session.get(FeedBuild, user_id) or FeedBuild(
                    user_id=user_id, status=""
                )
            else:
                state = session.get(ScopedFeedBuild, (user_id, scope)) or ScopedFeedBuild(
                    user_id=user_id, scope=scope, status=""
                )
            if state.status == "queued":
                return
            # A build already running started from older data, so queue another.
            if state.status != "building":
                state.status, state.error = "queued", None
                session.add(state)
                session.commit()
        self._queue.put(("build", user_id, language, genre, content_type, scope, force_refresh))

    def rescore_soon(self, user_id: int) -> None:
        """Rescore the user's feed once they stop rating and giving feedback for a moment."""
        _clear_single_score_cache(user_id)
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
            scope = item[5] if len(item) > 5 else "main"
            try:
                if job == "build":
                    language = item[2] if len(item) > 2 else None
                    genre = item[3] if len(item) > 3 else None
                    content_type = item[4] if len(item) > 4 else None
                    force_refresh = bool(item[6]) if len(item) > 6 else False
                    if scope == "main":
                        build_feed(
                            self._engine,
                            self._tmdb_base_url,
                            self._data_dir,
                            user_id,
                            language=language,
                            genre=genre,
                            content_type=content_type,
                        )
                    else:
                        build_scoped_feed(
                            self._engine,
                            self._tmdb_base_url,
                            self._data_dir,
                            user_id,
                            scope,
                            force_refresh=force_refresh,
                        )
                else:
                    self._rescore(user_id)
            except Exception:
                log.exception("Updating the feed of user %s crashed", user_id)
                with Session(self._engine) as session:
                    state: FeedBuild | ScopedFeedBuild | None = (
                        session.get(FeedBuild, user_id)
                        if scope == "main"
                        else session.get(ScopedFeedBuild, (user_id, scope))
                    )
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
