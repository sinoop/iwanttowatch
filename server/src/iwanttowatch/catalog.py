"""Movie metadata from TMDb, and matching titles from other sources to TMDb IDs."""

import json
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from difflib import SequenceMatcher
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from iwanttowatch.children import UNRATED, certificate_rank
from iwanttowatch.db import utcnow
from iwanttowatch.llm import LlmError, LlmProvider
from iwanttowatch.models import Title
from iwanttowatch.tmdb import TmdbClient, TmdbNotFound

TITLE_REFRESH_AFTER = timedelta(days=30)
LOOKUP_CACHE = timedelta(days=30)
DETAIL_APPENDS = "credits,keywords,translations,alternative_titles,release_dates"
PARALLEL_REQUESTS = 8


def ensure_title(session: Session, tmdb: TmdbClient, tmdb_id: int) -> Title:
    """Return the title, fetching or refreshing its metadata from TMDb when needed."""
    title = session.get(Title, tmdb_id)
    if title is not None and not _stale(title):
        return title
    title = _store(session, title, tmdb_id, _details(tmdb, tmdb_id))
    session.flush()
    return title


def ensure_titles(session: Session, tmdb: TmdbClient, tmdb_ids: list[int]) -> dict[int, Title]:
    """Like ensure_title for many films at once, fetching in parallel. Films TMDb
    doesn't have are left out."""
    titles = {
        t.tmdb_id: t for t in session.scalars(select(Title).where(Title.tmdb_id.in_(tmdb_ids)))
    }
    due = [i for i in dict.fromkeys(tmdb_ids) if i not in titles or _stale(titles[i])]

    def fetch(tmdb_id: int) -> dict[str, Any] | None:
        try:
            return _details(tmdb, tmdb_id)
        except TmdbNotFound:
            return None

    with ThreadPoolExecutor(PARALLEL_REQUESTS) as pool:
        fetched = list(pool.map(fetch, due))
    # Store only once everything is fetched: the first write holds SQLite's write lock
    # until the caller commits, and fetching a first feed's 800 films takes a while.
    for tmdb_id, details in zip(due, fetched, strict=True):
        if details is not None:
            titles[tmdb_id] = _store(session, titles.get(tmdb_id), tmdb_id, details)
    session.flush()
    return titles


def _stale(title: Title) -> bool:
    return utcnow() - title.fetched_at.replace(tzinfo=UTC) >= TITLE_REFRESH_AFTER


def _details(tmdb: TmdbClient, tmdb_id: int) -> dict[str, Any]:
    return tmdb.get(f"/movie/{tmdb_id}", {"append_to_response": DETAIL_APPENDS})


def _store(session: Session, title: Title | None, tmdb_id: int, details: dict[str, Any]) -> Title:
    fields = {**_title_fields(details), "fetched_at": utcnow()}
    if title is not None:
        for name, value in fields.items():
            setattr(title, name, value)
        return title
    # An upsert, because imports, Jellyfin syncs, and feed builds run on separate
    # threads and may add the same film at the same time.
    session.execute(
        insert(Title)
        .values(tmdb_id=tmdb_id, **fields)
        .on_conflict_do_update(index_elements=[Title.tmdb_id], set_=fields)
    )
    stored = session.get(Title, tmdb_id)
    assert stored is not None
    return stored


def _title_fields(d: dict[str, Any]) -> dict[str, Any]:
    release = _parse_date(d.get("release_date"))
    crew = d.get("credits", {}).get("crew", [])
    translations: dict[str, dict[str, str]] = {}
    for t in d.get("translations", {}).get("translations", []):
        data = t.get("data") or {}
        text = {k: data[k] for k in ("title", "overview") if data.get(k)}
        if text and t.get("iso_639_1") not in translations:
            translations[t["iso_639_1"]] = text
    return {
        "imdb_id": d.get("imdb_id") or None,
        "title": d.get("title") or d.get("original_title") or "",
        "original_title": d.get("original_title") or d.get("title") or "",
        "original_language": d.get("original_language") or "",
        "spoken_languages": [lang["iso_639_1"] for lang in d.get("spoken_languages", [])],
        "origin_countries": d.get("origin_country")
        or [c["iso_3166_1"] for c in d.get("production_countries", [])],
        "release_date": release,
        "year": release.year if release else None,
        "runtime": d.get("runtime") or None,
        "overview": d.get("overview") or "",
        "tagline": d.get("tagline") or "",
        "genres": [g["name"] for g in d.get("genres", [])],
        "keywords": [k["name"] for k in d.get("keywords", {}).get("keywords", [])],
        "cast": _people(d.get("credits", {}).get("cast", []), limit=10),
        "directors": _people([c for c in crew if c.get("job") == "Director"]),
        "writers": _people([c for c in crew if c.get("department") == "Writing"], limit=5),
        "alternative_titles": sorted(
            {
                t["title"]
                for t in d.get("alternative_titles", {}).get("titles", [])
                if t.get("title")
            }
        ),
        "translations": translations,
        "certifications": _certifications(d.get("release_dates", {}).get("results", [])),
        "vote_average": d.get("vote_average"),
        "vote_count": d.get("vote_count"),
        "popularity": d.get("popularity"),
        "poster_path": d.get("poster_path"),
    }


def _certifications(results: list[dict[str, Any]]) -> dict[str, str]:
    """The strictest certificate per country, from theatrical and digital releases when
    there are any. Codes we can't rank count as strictest, so age limits leave them out."""
    out: dict[str, str] = {}
    for entry in results:
        country = entry.get("iso_3166_1")
        if not country:
            continue
        certified = [
            (release.get("type"), cert)
            for release in entry.get("release_dates") or []
            if (cert := (release.get("certification") or "").strip())
            and cert.upper() not in UNRATED
        ]
        preferred = [c for kind, c in certified if kind in (3, 4)] or [c for _, c in certified]
        if preferred:
            out[country] = max(preferred, key=lambda c: certificate_rank(country, c) or 99)
    return out


def _people(credits: list[dict[str, Any]], limit: int | None = None) -> list[dict[str, Any]]:
    seen: dict[int, dict[str, Any]] = {}
    for person in credits:
        seen.setdefault(person["id"], {"id": person["id"], "name": person["name"]})
    return list(seen.values())[:limit]


def _parse_date(value: str | None) -> date | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date() if value else None
    except ValueError:
        return None


def candidate(result: dict[str, Any]) -> dict[str, Any]:
    """The fields of a TMDb search result shown when a user picks a match."""
    release = _parse_date(result.get("release_date"))
    return {
        "tmdb_id": result["id"],
        "title": result.get("title") or "",
        "original_title": result.get("original_title") or "",
        "original_language": result.get("original_language") or "",
        "year": release.year if release else None,
        "poster_path": result.get("poster_path"),
        "votes": result.get("vote_count") or 0,
    }


def search_movies(tmdb: TmdbClient, query: str, year: int | None = None) -> list[dict[str, Any]]:
    params = {"query": query, "year": year, "include_adult": "false"}
    results: list[dict[str, Any]] = tmdb.get("/search/movie", params, LOOKUP_CACHE)["results"]
    return [candidate(r) for r in results]


def person_candidate(result: dict[str, Any]) -> dict[str, Any]:
    """The fields of a TMDb person search result, including their known movie titles."""
    known_for_items = result.get("known_for") or []
    known_movies = []
    for item in known_for_items:
        is_movie = item.get("media_type") == "movie" or (
            "title" in item and item.get("media_type") != "tv"
        )
        if is_movie and item.get("id"):
            known_movies.append(candidate(item))
    return {
        "id": result["id"],
        "name": result.get("name") or result.get("original_name") or "",
        "profile_path": result.get("profile_path"),
        "known_for_department": result.get("known_for_department"),
        "known_for": known_movies,
    }


def search_people(tmdb: TmdbClient, query: str) -> list[dict[str, Any]]:
    params = {"query": query, "include_adult": "false"}
    results: list[dict[str, Any]] = tmdb.get("/search/person", params, LOOKUP_CACHE).get(
        "results", []
    )
    return [person_candidate(r) for r in results]


def search_catalog_all(tmdb: TmdbClient, query: str, year: int | None = None) -> dict[str, Any]:
    with ThreadPoolExecutor(2) as pool:
        movies_future = pool.submit(search_movies, tmdb, query, year)
        people_future = pool.submit(search_people, tmdb, query)
        movies = movies_future.result()
        people = people_future.result()

    seen_ids = {m["tmdb_id"] for m in movies}
    combined_movies = list(movies)
    for p in people:
        for k in p.get("known_for", []):
            if k["tmdb_id"] not in seen_ids:
                seen_ids.add(k["tmdb_id"])
                combined_movies.append(k)

    return {
        "movies": combined_movies,
        "people": people,
    }


AI_SEARCH_SYSTEM = """You help a movie lover search a film catalog using natural language.
Given a user query (which might be an actor in a role, a vague plot description,
a genre/mood request, a quote, or a theme), identify:
1. "movies": Specific real films that fit the request, best matches first (up to 8).
   Include title, approximate release year, and a brief 1-sentence explanation of how it fits
   (e.g. character name, role, or relevance).
2. "people": Relevant real actors, directors, or crew members directly asked for or key
   to the query (up to 4). Include their full name and a brief 1-sentence role/relevance.

Answer with ONLY valid JSON, no markdown formatting:
{
  "movies": [
    {"title": "...", "year": 2019, "why": "..."}
  ],
  "people": [
    {"name": "...", "why": "..."}
  ]
}"""


def search_catalog_ai(llm: LlmProvider, tmdb: TmdbClient, query: str) -> dict[str, Any]:
    """Search films and people using natural language via LLM, resolving against TMDb."""
    text = llm.generate(AI_SEARCH_SYSTEM, f"Query: {query.strip()}", json_reply=True)
    try:
        data = json.loads(text[text.index("{") : text.rindex("}") + 1])
    except (ValueError, IndexError) as error:
        raise LlmError("The LLM's answer wasn't JSON") from error

    raw_movies = data.get("movies") if isinstance(data, dict) else []
    raw_people = data.get("people") if isinstance(data, dict) else []

    def lookup_person(p: dict[str, Any]) -> dict[str, Any] | None:
        if not isinstance(p, dict) or not p.get("name"):
            return None
        name = str(p["name"]).strip()
        why = str(p.get("why") or "").strip()
        candidates = search_people(tmdb, name)
        if candidates:
            top = dict(candidates[0])
            top["why"] = why
            return top
        return None

    def lookup_movie(m: dict[str, Any]) -> dict[str, Any] | None:
        if not isinstance(m, dict) or not m.get("title"):
            return None
        title = str(m["title"]).strip()
        year = m.get("year")
        if not isinstance(year, int) or year < 1880 or year > 2100:
            year = None
        why = str(m.get("why") or "").strip()
        candidates = search_movies(tmdb, title, year=year) if year else []
        if not candidates:
            candidates = search_movies(tmdb, title)
        if candidates:
            top = dict(candidates[0])
            top["why"] = why
            return top
        return None

    with ThreadPoolExecutor(PARALLEL_REQUESTS) as pool:
        people_futures = [
            pool.submit(lookup_person, p)
            for p in (raw_people[:4] if isinstance(raw_people, list) else [])
        ]
        movie_futures = [
            pool.submit(lookup_movie, m)
            for m in (raw_movies[:8] if isinstance(raw_movies, list) else [])
        ]
        resolved_people: list[dict[str, Any]] = []
        seen_p: set[int] = set()
        for f in people_futures:
            res = f.result()
            if res and res["id"] not in seen_p:
                seen_p.add(res["id"])
                resolved_people.append(res)

        resolved_movies: list[dict[str, Any]] = []
        seen_m: set[int] = set()
        for f in movie_futures:
            res = f.result()
            if res and res["tmdb_id"] not in seen_m:
                seen_m.add(res["tmdb_id"])
                resolved_movies.append(res)

    if not resolved_movies:
        for p in resolved_people:
            for k in p.get("known_for", []):
                if k["tmdb_id"] not in seen_m:
                    seen_m.add(k["tmdb_id"])
                    resolved_movies.append(dict(k))

    return {
        "movies": resolved_movies,
        "people": resolved_people,
    }


def find_by_title(
    tmdb: TmdbClient, name: str, year: int | None, latest_year: int | None = None
) -> tuple[int | None, list[dict[str, Any]]]:
    """Match a title and year (as in Letterboxd exports) to a TMDb movie.

    `latest_year` rules out films released after it, such as remakes of a film watched
    before they came out. Returns the TMDb ID when the match is unambiguous, plus the
    candidates to show the user otherwise.
    """
    results = search_movies(tmdb, name, year) if year else []
    if len(results) == 1 and results[0]["year"] == year:
        # TMDb also searches alternative and translated titles, so a single hit for the
        # exact year is a match even when its display title is spelled differently.
        return results[0]["tmdb_id"], results
    if not results:
        results = search_movies(tmdb, name)
    close = [c for c in results[:10] if _title_similarity(name, c) >= 0.9]
    if year:
        close = [c for c in close if c["year"] and abs(c["year"] - year) <= 1]
        close = [c for c in close if c["year"] == year] or close
    if latest_year:
        close = [c for c in close if c["year"] and c["year"] <= latest_year]
    if year is None and len(close) > 1:
        # With no year to go on (Netflix history), take a film far better known than its
        # namesakes, such as Joker (2019); leave closer calls, such as Leo, to the user.
        close.sort(key=lambda c: c["votes"], reverse=True)
        if close[0]["votes"] >= 20 and close[0]["votes"] >= 10 * close[1]["votes"]:
            close = close[:1]
    if len(close) == 1:
        return close[0]["tmdb_id"], results[:5]
    return None, results[:5]


def is_tv_show(tmdb: TmdbClient, name: str) -> bool:
    """Whether TMDb has a TV series by this name."""
    results = tmdb.get("/search/tv", {"query": name}, LOOKUP_CACHE)["results"]
    return any(
        _title_similarity(
            name, {"title": r.get("name") or "", "original_title": r.get("original_name") or ""}
        )
        >= 0.9
        for r in results[:10]
    )


def _title_similarity(name: str, c: dict[str, Any]) -> float:
    wanted = normalise_title(name)
    return max(
        SequenceMatcher(None, wanted, normalise_title(c[field])).ratio()
        for field in ("title", "original_title")
    )


def normalise_title(title: str) -> str:
    text = unicodedata.normalize("NFKD", title.casefold())
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).replace("&", " and ")
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"^(the|a|an)\s+", "", text.strip())
    return " ".join(text.split())


_normalise = normalise_title


def clean_media_title_and_year(raw: str) -> tuple[str, int | None]:
    """Extract a clean title and release year from media filenames or Jellyfin names.

    Handles scene tags (.1080p, [4K], WEBRip), bracketed years like (2020) or [2020],
    and dot/underscore separated names.
    """
    text = raw.strip()
    is_scene_or_dot = bool(
        re.search(r"\.(1080p|720p|2160p|4k|bluray|webrip|web-dl|x264|x265|dvdrip)\b", text, re.I)
        or ("." in text and " " not in text)
    )
    if is_scene_or_dot:
        text = text.replace(".", " ").replace("_", " ")

    year: int | None = None
    m_year = re.search(r"[\(\[]\s*(19\d\d|20\d\d)\s*[\)\]]", text)
    if m_year:
        year = int(m_year.group(1))
        text = text[: m_year.start()] + " " + text[m_year.end() :]

    text = re.sub(r"\[[^\]]*\]", " ", text)
    text = re.sub(r"\([^\)]*\)", " ", text)

    scene_match = re.search(
        r"\b(1080p|720p|2160p|4k|uhd|bluray|webrip|web-dl|remux|h264|x264|h265|x265|hevc|dvdrip|aac|ac3|dts|flux|yify|rarbg)\b.*$",
        text,
        re.I,
    )
    if scene_match:
        before_scene = text[: scene_match.start()].strip()
        m_trailing_year = re.search(r"\b(19\d\d|20\d\d)$", before_scene)
        if m_trailing_year:
            if not year:
                year = int(m_trailing_year.group(1))
            before_scene = before_scene[: m_trailing_year.start()].strip()
        text = before_scene
    elif is_scene_or_dot:
        words = text.split()
        if len(words) > 1 and re.match(r"^(19\d\d|20\d\d)$", words[-1]):
            if not year:
                year = int(words[-1])
            text = " ".join(words[:-1])

    text = re.sub(r"\s+", " ", text).strip(" -_.:")
    return text, year
