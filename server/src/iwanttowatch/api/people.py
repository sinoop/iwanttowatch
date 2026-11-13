"""Person details, filmography, and personal taste affinity."""

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert

from iwanttowatch.api.deps import CurrentUser, DbSession, Tmdb
from iwanttowatch.children import library_owners
from iwanttowatch.db import utcnow
from iwanttowatch.feed import seen
from iwanttowatch.models import Availability, FavoritePerson, LibraryItem, Title
from iwanttowatch.taste import effective_ratings, rating_to_reaction
from iwanttowatch.tmdb import TmdbNotFound

router = APIRouter(prefix="/api/v1/people", tags=["people"])
PERSON_CACHE = timedelta(days=7)


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
    popularity: float = 0.0
    user_rating: float | None = None
    user_reaction: str | None = None
    watched: bool = False
    in_library: bool = False
    streaming_services: list[str] = Field(default_factory=list)


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
    if movie_ids and user.subscriptions:
        subs = set(user.subscriptions)
        for av in session.scalars(
            select(Availability).where(
                Availability.tmdb_id.in_(movie_ids), Availability.region == user.region
            )
        ):
            active_names = [
                o["name"]
                for o in av.offers
                if o.get("provider_id") in subs and o.get("kind") in ("flatrate", "free", "ads")
            ]
            if active_names:
                avail_map[av.tmdb_id] = list(dict.fromkeys(active_names))

    filmography: list[PersonCredit] = []
    for mid, m in movies.items():
        rating, reaction = ratings_map.get(mid, (None, None))
        if reaction is None and rating is not None:
            reaction = rating_to_reaction(rating)
        is_watched = mid in ratings_map or mid in watched_set
        is_in_library = mid in library_set
        services = avail_map.get(mid, [])
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
                popularity=m["popularity"],
                user_rating=rating,
                user_reaction=reaction,
                watched=is_watched,
                in_library=is_in_library,
                streaming_services=services,
            )
        )

    # Sort filmography by popularity descending, then vote count, then year descending.
    filmography.sort(
        key=lambda c: (
            c.popularity or 0.0,
            c.vote_count or 0,
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
    return {"ok": True, "is_favorite": False}
