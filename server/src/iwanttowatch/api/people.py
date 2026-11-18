"""Person details, filmography, and personal taste affinity."""

import math
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert

from iwanttowatch import imdb
from iwanttowatch.api.deps import CurrentUser, DbSession, Tmdb
from iwanttowatch.api.streaming import Offer
from iwanttowatch.children import library_owners
from iwanttowatch.db import utcnow
from iwanttowatch.feed import clear_user_rated_matches_cache, seen
from iwanttowatch.models import Availability, FavoritePerson, LibraryItem, Recommendation, Title
from iwanttowatch.taste import effective_ratings, rating_to_reaction
from iwanttowatch.tmdb import TmdbClient, TmdbError, TmdbNotFound

router = APIRouter(prefix="/api/v1/people", tags=["people"])
PERSON_CACHE = timedelta(days=7)
EXTERNAL_IDS_CACHE = timedelta(days=30)
IMDB_ENRICH_LIMIT = 20
# IMDb has roughly ~50x more voters than TMDb; scale IMDb votes onto TMDb's range so
# cached IMDb-enriched titles stay comparable to uncached TMDb-only credits while still
# giving regional cinema with sparse TMDb votes a fair lift.
IMDB_TO_TMDB_VOTE_RATIO = 50.0


def _effective_votes(vote_count: int | None, imdb_votes: int | None) -> float:
    tmdb_votes = max(0, vote_count or 0)
    scaled_imdb = max(0, imdb_votes or 0) / IMDB_TO_TMDB_VOTE_RATIO
    return max(float(tmdb_votes), scaled_imdb)


def _popularity_score(
    vote_count: int | None, popularity: float | None, imdb_votes: int | None
) -> float:
    """Blended fame score: cumulative audience votes (IMDb/TMDb) + mild TMDb buzz."""
    eff_votes = _effective_votes(vote_count, imdb_votes)
    pop = max(0.0, float(popularity or 0.0))
    if eff_votes <= 0 and pop <= 0:
        return 0.0
    return round(math.log1p(eff_votes) + 0.35 * math.log1p(pop), 4)


def _fetch_imdb_id(tmdb: TmdbClient, tmdb_id: int) -> tuple[int, str | None]:
    try:
        ext = tmdb.get(f"/movie/{tmdb_id}/external_ids", cache_for=EXTERNAL_IDS_CACHE)
    except TmdbError:
        return tmdb_id, None
    imdb_id = ext.get("imdb_id")
    return tmdb_id, imdb_id if isinstance(imdb_id, str) and imdb_id else None


def _enrich_imdb_credits(
    session: DbSession,
    data_dir: Path,
    tmdb: TmdbClient,
    movies: dict[int, dict[str, Any]],
    imdb_map: dict[int, tuple[float | None, int | None]],
    title_imdb_ids: dict[int, str],
) -> None:
    """Populate IMDb ratings/votes for cached Title IMDb IDs and top uncached credits."""
    if not imdb.enabled(session) or not imdb.ratings_file(data_dir).exists():
        return

    # 1. Resolve Title rows that already have an imdb_id without calling TMDb.
    pending_tmdb_to_imdb = dict(title_imdb_ids)

    # 2. Fetch external_ids for top uncached candidates so regional/uncached hits get IMDb votes.
    candidates = [
        m
        for mid, m in movies.items()
        if mid not in imdb_map
        and mid not in pending_tmdb_to_imdb
        and ((m.get("vote_count") or 0) > 0 or (m.get("popularity") or 0.0) > 0)
    ]
    candidates.sort(
        key=lambda m: _popularity_score(m.get("vote_count"), m.get("popularity"), None),
        reverse=True,
    )
    to_fetch = [int(m["tmdb_id"]) for m in candidates[:IMDB_ENRICH_LIMIT]]
    if to_fetch:
        with ThreadPoolExecutor(max_workers=8) as pool:
            for mid, imdb_id in pool.map(lambda tid: _fetch_imdb_id(tmdb, tid), to_fetch):
                if imdb_id:
                    pending_tmdb_to_imdb[mid] = imdb_id

    if not pending_tmdb_to_imdb:
        return

    found = imdb.lookup_ratings(data_dir, list(pending_tmdb_to_imdb.values()))
    for mid, imdb_id in pending_tmdb_to_imdb.items():
        if imdb_id in found:
            imdb_map[mid] = found[imdb_id]


class PersonCredit(BaseModel):
    tmdb_id: int
    title: str
    original_title: str
    year: int | None = None
    poster_path: str | None = None
    character: str | None = None
    job: str | None = None
    department: str | None = None
    vote_average: float | None = None
    vote_count: int | None = None
    imdb_rating: float | None = None
    imdb_votes: int | None = None
    match: int | None = None
    popularity: float = 0.0
    popularity_score: float = 0.0
    user_rating: float | None = None
    user_reaction: str | None = None
    watched: bool = False
    in_library: bool = False
    streaming_services: list[str] = Field(default_factory=list)
    streaming_offers: list[Offer] = Field(default_factory=list)


class PersonAffinity(BaseModel):
    rated_count: int = 0
    average_rating: float | None = None
    loved_count: int = 0
    liked_count: int = 0
    disliked_count: int = 0
    rated_films: list[PersonCredit] = Field(default_factory=list)


class PersonDetail(BaseModel):
    id: int
    name: str
    biography: str | None = None
    profile_path: str | None = None
    birthday: str | None = None
    deathday: str | None = None
    place_of_birth: str | None = None
    known_for_department: str | None = None
    is_favorite: bool = False
    affinity: PersonAffinity
    filmography: list[PersonCredit] = Field(default_factory=list)


class FavoriteToggleRequest(BaseModel):
    name: str | None = None
    role: str | None = None
    profile_path: str | None = None


class FavoritePersonItem(BaseModel):
    person_id: int
    name: str
    role: str | None = None
    profile_path: str | None = None
    created_at: datetime


class LearnedPerson(BaseModel):
    id: int
    name: str
    role: str
    rated_count: int
    average_rating: float
    loved_count: int = 0
    liked_count: int = 0
    disliked_count: int = 0
    is_favorite: bool = False
    profile_path: str | None = None


class PeopleTasteOverview(BaseModel):
    favorites: list[FavoritePersonItem] = Field(default_factory=list)
    top_directors: list[LearnedPerson] = Field(default_factory=list)
    top_actors: list[LearnedPerson] = Field(default_factory=list)


@router.get("/favorites", response_model=list[FavoritePersonItem])
def get_favorites(session: DbSession, user: CurrentUser) -> list[FavoritePersonItem]:
    """List all people favorited by the current user."""
    rows = session.scalars(
        select(FavoritePerson)
        .where(FavoritePerson.user_id == user.id)
        .order_by(FavoritePerson.created_at.desc())
    ).all()
    return [
        FavoritePersonItem(
            person_id=r.person_id,
            name=r.name,
            role=r.role,
            profile_path=r.profile_path,
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.get("/taste", response_model=PeopleTasteOverview)
def get_people_taste(session: DbSession, user: CurrentUser) -> PeopleTasteOverview:
    """The user's favorite people and top learned directors and actors from rating history."""
    fav_rows = session.scalars(
        select(FavoritePerson)
        .where(FavoritePerson.user_id == user.id)
        .order_by(FavoritePerson.created_at.desc())
    ).all()
    fav_map = {f.person_id: f for f in fav_rows}
    fav_list = [
        FavoritePersonItem(
            person_id=r.person_id,
            name=r.name,
            role=r.role,
            profile_path=r.profile_path,
            created_at=r.created_at,
        )
        for r in fav_rows
    ]

    effective = effective_ratings(user.id)
    rated_titles = session.execute(
        select(effective.c.rating, effective.c.reaction, Title)
        .join(Title, Title.tmdb_id == effective.c.tmdb_id)
        .where(effective.c.rating.is_not(None))
    ).all()

    directors_stats: dict[int, dict[str, Any]] = {}
    actors_stats: dict[int, dict[str, Any]] = {}

    for row in rated_titles:
        r_val = float(row.rating)
        reaction = row.reaction
        t: Title = row.Title

        for p in t.directors:
            if not isinstance(p, dict) or not p.get("id") or not p.get("name"):
                continue
            pid = p["id"]
            if pid not in directors_stats:
                directors_stats[pid] = {
                    "id": pid,
                    "name": p["name"],
                    "ratings": [],
                    "loved": 0,
                    "liked": 0,
                    "disliked": 0,
                }
            directors_stats[pid]["ratings"].append(r_val)
            if reaction == "loved" or (reaction is None and r_val >= 8.5):
                directors_stats[pid]["loved"] += 1
            elif reaction == "liked" or (reaction is None and 6.0 <= r_val < 8.5):
                directors_stats[pid]["liked"] += 1
            elif reaction == "disliked" or (reaction is None and r_val < 6.0):
                directors_stats[pid]["disliked"] += 1

        for p in t.cast[:5]:
            if not isinstance(p, dict) or not p.get("id") or not p.get("name"):
                continue
            pid = p["id"]
            if pid not in actors_stats:
                actors_stats[pid] = {
                    "id": pid,
                    "name": p["name"],
                    "ratings": [],
                    "loved": 0,
                    "liked": 0,
                    "disliked": 0,
                }
            actors_stats[pid]["ratings"].append(r_val)
            if reaction == "loved" or (reaction is None and r_val >= 8.5):
                actors_stats[pid]["loved"] += 1
            elif reaction == "liked" or (reaction is None and 6.0 <= r_val < 8.5):
                actors_stats[pid]["liked"] += 1
            elif reaction == "disliked" or (reaction is None and r_val < 6.0):
                actors_stats[pid]["disliked"] += 1

    def build_learned(
        stats_dict: dict[int, dict[str, Any]], min_count: int, role: str
    ) -> list[LearnedPerson]:
        qualifying = [s for s in stats_dict.values() if len(s["ratings"]) >= min_count]
        qualifying.sort(
            key=lambda s: (
                sum(s["ratings"]) / len(s["ratings"]),
                len(s["ratings"]),
            ),
            reverse=True,
        )
        out = []
        for s in qualifying[:10]:
            pid = s["id"]
            avg = round(sum(s["ratings"]) / len(s["ratings"]), 1)
            fav = fav_map.get(pid)
            out.append(
                LearnedPerson(
                    id=pid,
                    name=s["name"],
                    role=role,
                    rated_count=len(s["ratings"]),
                    average_rating=avg,
                    loved_count=s["loved"],
                    liked_count=s["liked"],
                    disliked_count=s["disliked"],
                    is_favorite=fav is not None,
                    profile_path=fav.profile_path if fav else None,
                )
            )
        return out

    top_dirs = build_learned(directors_stats, min_count=2, role="Director")
    top_acts = build_learned(actors_stats, min_count=3, role="Actor")

    return PeopleTasteOverview(
        favorites=fav_list,
        top_directors=top_dirs,
        top_actors=top_acts,
    )


@router.get("/{person_id}", response_model=PersonDetail)
def get_person(
    request: Request,
    person_id: int,
    session: DbSession,
    user: CurrentUser,
    tmdb: Tmdb,
) -> PersonDetail:
    """Person biography, credits, and the user's personal taste affinity."""
    try:
        data = tmdb.get(
            f"/person/{person_id}",
            {"append_to_response": "movie_credits"},
            cache_for=PERSON_CACHE,
        )
    except TmdbNotFound as err:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Person not found") from err

    is_fav = (
        session.scalar(
            select(FavoritePerson.id).where(
                FavoritePerson.user_id == user.id, FavoritePerson.person_id == person_id
            )
        )
        is not None
    )

    credits = data.get("movie_credits") or {}
    cast_entries = credits.get("cast") or []
    crew_entries = credits.get("crew") or []

    # De-duplicate movie credits by movie ID while preserving roles.
    movies: dict[int, dict[str, Any]] = {}

    def extract_year(date_str: str | None) -> int | None:
        if not date_str or len(date_str) < 4:
            return None
        try:
            return int(date_str[:4])
        except ValueError:
            return None

    # Directors and key crew first.
    for entry in crew_entries:
        mid = entry.get("id")
        if not mid or not isinstance(mid, int):
            continue
        job = entry.get("job")
        dept = entry.get("department")
        if mid not in movies:
            movies[mid] = {
                "tmdb_id": mid,
                "title": entry.get("title") or entry.get("original_title") or "",
                "original_title": entry.get("original_title") or entry.get("title") or "",
                "year": extract_year(entry.get("release_date")),
                "poster_path": entry.get("poster_path"),
                "job": job,
                "department": dept,
                "character": None,
                "vote_average": entry.get("vote_average"),
                "vote_count": entry.get("vote_count"),
                "popularity": entry.get("popularity") or 0.0,
            }
        elif job == "Director":
            movies[mid]["job"] = "Director"
            movies[mid]["department"] = dept or movies[mid].get("department")

    for entry in cast_entries:
        mid = entry.get("id")
        if not mid or not isinstance(mid, int):
            continue
        char = entry.get("character")
        if mid not in movies:
            movies[mid] = {
                "tmdb_id": mid,
                "title": entry.get("title") or entry.get("original_title") or "",
                "original_title": entry.get("original_title") or entry.get("title") or "",
                "year": extract_year(entry.get("release_date")),
                "poster_path": entry.get("poster_path"),
                "job": None,
                "department": None,
                "character": char,
                "vote_average": entry.get("vote_average"),
                "vote_count": entry.get("vote_count"),
                "popularity": entry.get("popularity") or 0.0,
            }
        else:
            if char and not movies[mid]["character"]:
                movies[mid]["character"] = char

    movie_ids = list(movies.keys())

    # User ratings & reactions
    effective = effective_ratings(user.id)
    ratings_map: dict[int, tuple[float | None, str | None]] = {}
    if movie_ids:
        for row in session.execute(
            select(effective.c.tmdb_id, effective.c.rating, effective.c.reaction).where(
                effective.c.tmdb_id.in_(movie_ids)
            )
        ):
            ratings_map[row.tmdb_id] = (row.rating, row.reaction)

    watched_set = seen(session, user.id)
    owners = library_owners(session, user)
    library_set = (
        set(
            session.scalars(
                select(LibraryItem.tmdb_id).where(
                    LibraryItem.user_id.in_(owners), LibraryItem.tmdb_id.in_(movie_ids)
                )
            )
        )
        if movie_ids
        else set()
    )

    avail_map: dict[int, list[str]] = {}
    offers_map: dict[int, list[Offer]] = {}
    if movie_ids and user.subscriptions:
        subs = set(user.subscriptions)
        for av in session.scalars(
            select(Availability).where(
                Availability.tmdb_id.in_(movie_ids), Availability.region == user.region
            )
        ):
            by_provider: dict[int, Offer] = {}
            for o in av.offers:
                pid = o.get("provider_id")
                if (
                    isinstance(pid, int)
                    and pid in subs
                    and o.get("kind") in ("flatrate", "free", "ads")
                    and pid not in by_provider
                ):
                    by_provider[pid] = Offer(
                        provider_id=pid,
                        name=o["name"],
                        logo_path=o.get("logo_path"),
                        kind=o["kind"],
                    )
            if by_provider:
                offers_list = list(by_provider.values())
                offers_map[av.tmdb_id] = offers_list
                avail_map[av.tmdb_id] = list(dict.fromkeys(o.name for o in offers_list))

    imdb_map: dict[int, tuple[float | None, int | None]] = {}
    title_imdb_ids: dict[int, str] = {}
    match_map: dict[int, int] = {}
    if movie_ids:
        for title_row in session.execute(
            select(Title.tmdb_id, Title.imdb_id, Title.imdb_rating, Title.imdb_votes).where(
                Title.tmdb_id.in_(movie_ids)
            )
        ):
            if title_row.imdb_rating is not None:
                imdb_map[title_row.tmdb_id] = (title_row.imdb_rating, title_row.imdb_votes)
            elif title_row.imdb_id and title_row.imdb_votes is None:
                title_imdb_ids[title_row.tmdb_id] = title_row.imdb_id
        _enrich_imdb_credits(
            session, request.app.state.data_dir, tmdb, movies, imdb_map, title_imdb_ids
        )
        for tmdb_id, score in session.execute(
            select(Recommendation.tmdb_id, Recommendation.score).where(
                Recommendation.user_id == user.id, Recommendation.tmdb_id.in_(movie_ids)
            )
        ):
            match_map[tmdb_id] = round(score * 100)

    filmography: list[PersonCredit] = []
    for mid, m in movies.items():
        rating, reaction = ratings_map.get(mid, (None, None))
        if reaction is None and rating is not None:
            reaction = rating_to_reaction(rating)
        is_watched = mid in ratings_map or mid in watched_set
        is_in_library = mid in library_set
        services = avail_map.get(mid, [])
        imdb_r, imdb_v = imdb_map.get(mid, (None, None))
        pop_score = _popularity_score(m["vote_count"], m["popularity"], imdb_v)
        filmography.append(
            PersonCredit(
                tmdb_id=mid,
                title=m["title"],
                original_title=m["original_title"],
                year=m["year"],
                poster_path=m["poster_path"],
                character=m["character"],
                job=m["job"],
                department=m["department"],
                vote_average=m["vote_average"],
                vote_count=m["vote_count"],
                imdb_rating=imdb_r,
                imdb_votes=imdb_v,
                match=match_map.get(mid),
                popularity=m["popularity"],
                popularity_score=pop_score,
                user_rating=rating,
                user_reaction=reaction,
                watched=is_watched,
                in_library=is_in_library,
                streaming_services=services,
                streaming_offers=offers_map.get(mid, []),
            )
        )

    # Sort filmography by established audience votes + TMDb buzz so classics lead over
    # unreleased or low-vote hype, while still keeping current hits near the top.
    filmography.sort(
        key=lambda c: (
            _effective_votes(c.vote_count, c.imdb_votes) >= 5,
            _effective_votes(c.vote_count, c.imdb_votes) > 0,
            c.popularity_score,
            c.popularity or 0.0,
            c.year or 0,
        ),
        reverse=True,
    )

    # Affinity calculation
    rated_films = [
        c for c in filmography if c.user_rating is not None or c.user_reaction is not None
    ]
    rated_films.sort(
        key=lambda c: (
            c.user_rating if c.user_rating is not None else 0.0,
            c.year or 0,
        ),
        reverse=True,
    )

    numeric_vals = [c.user_rating for c in rated_films if c.user_rating is not None]
    avg_rating = round(sum(numeric_vals) / len(numeric_vals), 1) if numeric_vals else None

    loved_count = sum(
        1
        for c in rated_films
        if c.user_reaction == "loved"
        or (c.user_reaction is None and c.user_rating is not None and c.user_rating >= 8.5)
    )
    liked_count = sum(
        1
        for c in rated_films
        if c.user_reaction == "liked"
        or (c.user_reaction is None and c.user_rating is not None and 6.0 <= c.user_rating < 8.5)
    )
    disliked_count = sum(
        1
        for c in rated_films
        if c.user_reaction == "disliked"
        or (c.user_reaction is None and c.user_rating is not None and c.user_rating < 6.0)
    )

    affinity = PersonAffinity(
        rated_count=len(rated_films),
        average_rating=avg_rating,
        loved_count=loved_count,
        liked_count=liked_count,
        disliked_count=disliked_count,
        rated_films=rated_films,
    )

    return PersonDetail(
        id=person_id,
        name=data.get("name") or "",
        biography=data.get("biography"),
        profile_path=data.get("profile_path"),
        birthday=data.get("birthday"),
        deathday=data.get("deathday"),
        place_of_birth=data.get("place_of_birth"),
        known_for_department=data.get("known_for_department"),
        is_favorite=is_fav,
        affinity=affinity,
        filmography=filmography,
    )


@router.put("/{person_id}/favorite")
def add_favorite(
    person_id: int,
    body: FavoriteToggleRequest,
    session: DbSession,
    user: CurrentUser,
    tmdb: Tmdb,
) -> dict[str, Any]:
    """Add a person to the user's favorites."""
    name = body.name
    role = body.role
    profile = body.profile_path

    if not name:
        try:
            p = tmdb.get(f"/person/{person_id}", cache_for=PERSON_CACHE)
            name = p.get("name") or f"Person {person_id}"
            role = role or p.get("known_for_department")
            profile = profile or p.get("profile_path")
        except TmdbNotFound as err:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Person not found") from err

    values = {
        "name": name,
        "role": role,
        "profile_path": profile,
    }
    session.execute(
        insert(FavoritePerson)
        .values(
            user_id=user.id,
            person_id=person_id,
            created_at=utcnow(),
            **values,
        )
        .on_conflict_do_update(
            index_elements=[FavoritePerson.user_id, FavoritePerson.person_id],
            set_=values,
        )
    )
    session.commit()
    clear_user_rated_matches_cache(user.id)
    return {"ok": True, "is_favorite": True}


@router.delete("/{person_id}/favorite")
def remove_favorite(
    person_id: int,
    session: DbSession,
    user: CurrentUser,
) -> dict[str, Any]:
    """Remove a person from the user's favorites."""
    session.execute(
        delete(FavoritePerson).where(
            FavoritePerson.user_id == user.id, FavoritePerson.person_id == person_id
        )
    )
    session.commit()
    clear_user_rated_matches_cache(user.id)
    return {"ok": True, "is_favorite": False}
