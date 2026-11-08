import io
import sqlite3
import time
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from iwanttowatch.catalog import ensure_titles
from iwanttowatch.config import Settings
from iwanttowatch.main import create_app
from iwanttowatch.tmdb import TmdbClient

KEY = "0123456789abcdef0123456789abcdef"

# A small fake TMDb catalogue. Two films share a title and year (an ambiguous
# Letterboxd row, though one is far better known), and Premam has a same-titled film
# one year later.
MOVIES: dict[int, dict[str, Any]] = {
    101: {"title": "Léon: The Professional", "original_title": "Léon", "lang": "fr",
          "date": "1994-09-14", "imdb": "tt0110413", "certs": {"IN": "A", "US": "R"}},
    201: {"title": "Kumbalangi Nights", "original_title": "കുമ്പളങ്ങി നൈറ്റ്സ്", "lang": "ml",
          "date": "2019-02-07", "imdb": "tt8413338", "certs": {"IN": "U/A 7+", "US": "PG"}},
    301: {"title": "Drishyam", "original_title": "ദൃശ്യം", "lang": "ml",
          "date": "2013-12-19", "imdb": "tt3417422", "certs": {"IN": "U", "US": "PG"},
          "votes": 241},
    302: {"title": "Drishyam", "original_title": "Drishyam", "lang": "en",
          "date": "2013-03-02", "imdb": None, "certs": {"IN": "U/A 13+", "US": "PG-13"},
          "votes": 9},
    401: {"title": "Premam", "original_title": "പ്രേമം", "lang": "ml",
          "date": "2015-05-29", "imdb": "tt4679210", "certs": {"IN": "U", "US": "G"},
          "votes": 133},
    402: {"title": "Premam", "original_title": "ప్రేమమ్", "lang": "te",
          "date": "2016-10-07", "imdb": None, "certs": {}, "votes": 23},
}  # fmt: skip


# Streaming services, and where films stream by region (TMDb's data from JustWatch).
NETFLIX = {"provider_id": 8, "provider_name": "Netflix", "logo_path": "/netflix.jpg"}
PRIME = {"provider_id": 119, "provider_name": "Amazon Prime Video", "logo_path": "/prime.jpg"}
HOTSTAR = {"provider_id": 2336, "provider_name": "JioHotstar", "logo_path": "/hotstar.jpg"}
APPLE = {"provider_id": 2, "provider_name": "Apple TV", "logo_path": "/apple.jpg"}
MX = {"provider_id": 515, "provider_name": "MX Player", "logo_path": "/mx.jpg"}
CATALOGUE = {  # region → services, most prominent first
    "IN": [HOTSTAR, PRIME, NETFLIX, MX, APPLE],
    "US": [NETFLIX, PRIME, APPLE],
}
WATCH: dict[int, dict[str, dict[str, list[dict[str, Any]]]]] = {
    301: {"IN": {"flatrate": [PRIME, HOTSTAR], "rent": [APPLE]}},
    201: {"IN": {"flatrate": [NETFLIX]}},
    101: {"US": {"flatrate": [NETFLIX]}, "IN": {"ads": [MX], "buy": [APPLE]}},
}


def _summary(tmdb_id: int) -> dict[str, Any]:
    m = MOVIES[tmdb_id]
    return {
        "id": tmdb_id,
        "title": m["title"],
        "original_title": m["original_title"],
        "original_language": m["lang"],
        "release_date": m["date"],
        "poster_path": f"/{tmdb_id}.jpg",
        "vote_count": m.get("votes", 0),
    }


def _details(tmdb_id: int) -> dict[str, Any]:
    m = MOVIES[tmdb_id]
    return {
        **_summary(tmdb_id),
        "imdb_id": m["imdb"],
        "genres": [{"id": 18, "name": "Drama"}],
        "spoken_languages": [{"iso_639_1": m["lang"]}],
        "credits": {"cast": [], "crew": [{"id": 9, "name": "A Director", "job": "Director"}]},
        "keywords": {"keywords": [{"id": 1, "name": "family"}]},
        "translations": {"translations": []},
        "alternative_titles": {"titles": []},
        "release_dates": {
            "results": [
                {"iso_3166_1": country, "release_dates": [{"certification": cert, "type": 3}]}
                for country, cert in m.get("certs", {}).items()
            ]
        },
    }


def fake_tmdb(request: httpx.Request) -> httpx.Response:
    path = request.url.path.removeprefix("/3")
    params = request.url.params
    if params.get("api_key") != KEY:
        return httpx.Response(401, json={"status_message": "Invalid API key"})
    if path == "/configuration":
        return httpx.Response(200, json={"images": {}})
    if path.startswith("/find/"):
        imdb_id = path.removeprefix("/find/")
        movies = [_summary(i) for i, m in MOVIES.items() if m["imdb"] == imdb_id]
        tv = [{"id": 1396, "name": "Breaking Bad"}] if imdb_id == "tt0903747" else []
        return httpx.Response(200, json={"movie_results": movies, "tv_results": tv})
    if path == "/search/movie":
        query, year = params["query"].lower(), params.get("year")
        hits = [
            _summary(i)
            for i, m in MOVIES.items()
            # Like TMDb's `year`, which matches any regional release date, allow ±1 year.
            if query in m["title"].lower()
            and (year is None or abs(int(m["date"][:4]) - int(year)) <= 1)
        ]
        return httpx.Response(200, json={"results": hits})
    if path == "/search/tv":
        shows = [{"id": 1, "name": "Our Planet", "original_name": "Our Planet"}]
        return httpx.Response(
            200, json={"results": [s for s in shows if s["name"] == params["query"]]}
        )
    if path == "/certification/movie/list":
        nl = [{"certification": c, "meaning": "", "order": n}
              for n, c in enumerate(["AL", "6", "9", "12", "14", "16", "18"], 1)]  # fmt: skip
        return httpx.Response(200, json={"certifications": {"NL": nl}})
    if path == "/watch/providers/regions":
        regions = [{"iso_3166_1": "IN", "english_name": "India"},
                   {"iso_3166_1": "US", "english_name": "United States of America"}]  # fmt: skip
        return httpx.Response(200, json={"results": regions})
    if path == "/watch/providers/movie":
        region = params["watch_region"]
        # TMDb returns services in no particular order, with a priority per region.
        services = [
            {**p, "display_priority": 99, "display_priorities": {region: n}}
            for n, p in enumerate(CATALOGUE.get(region, []))
        ]
        return httpx.Response(200, json={"results": services[::-1]})
    if path == "/discover/movie":
        if params.get("page", "1") != "1":
            return httpx.Response(200, json={"results": []})
        language = params.get("with_original_language")
        providers = {int(p) for p in params.get("with_watch_providers", "").split("|") if p}
        kinds = params.get("with_watch_monetization_types", "").split("|")
        region = params.get("watch_region", "")

        def streams(tmdb_id: int) -> bool:
            offers = WATCH.get(tmdb_id, {}).get(region, {})
            return any(p["provider_id"] in providers for k in kinds for p in offers.get(k, []))

        hits = [_summary(i) for i, m in MOVIES.items()
                if (not language or m["lang"] == language) and (not providers or streams(i))]  # fmt: skip
        return httpx.Response(200, json={"results": hits})
    if path.startswith("/movie/") and path.endswith("/recommendations"):
        tmdb_id = int(path.split("/")[2])
        hits = [_summary(i) for i in MOVIES if i != tmdb_id]
        return httpx.Response(200, json={"results": hits})
    if path.startswith("/movie/") and path.endswith("/watch/providers"):
        tmdb_id = int(path.split("/")[2])
        if tmdb_id not in MOVIES:
            return httpx.Response(404)
        results = {
            region: {"link": f"https://www.themoviedb.org/movie/{tmdb_id}/watch?locale={region}",
                     **{kind: [{**p, "display_priority": 1} for p in providers]
                        for kind, providers in offers.items()}}
            for region, offers in WATCH.get(tmdb_id, {}).items()
        }  # fmt: skip
        return httpx.Response(200, json={"id": tmdb_id, "results": results})
    if path.startswith("/movie/"):
        tmdb_id = int(path.removeprefix("/movie/"))
        if tmdb_id in MOVIES:
            return httpx.Response(200, json=_details(tmdb_id))
    return httpx.Response(404)


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    with respx.mock(assert_all_called=False) as mock:
        mock.route(host="api.themoviedb.org").mock(side_effect=fake_tmdb)
        client = TestClient(
            create_app(Settings(data_dir=tmp_path, secret_key="t", static_dir=None))
        )
        admin = {"username": "a", "display_name": "A", "password": "password1", "region": "IN"}
        client.post("/api/v1/setup", json=admin)
        assert client.put("/api/v1/settings/tmdb", json={"api_key": KEY}).status_code == 200
        yield client


def upload(client: TestClient, filename: str, content: bytes) -> dict[str, Any]:
    response = client.post("/api/v1/imports", files={"file": (filename, content)})
    assert response.status_code == 201, response.text
    client.app.state.import_worker.wait_until_idle()  # type: ignore[attr-defined]
    job: dict[str, Any] = next(
        j for j in client.get("/api/v1/imports").json() if j["id"] == response.json()["id"]
    )
    return job


def ratings(client: TestClient) -> dict[str, Any]:
    page: dict[str, Any] = client.get("/api/v1/ratings").json()
    return page


IMDB_NEW = """Const,Your Rating,Date Rated,Title,Original Title,URL,Title Type,IMDb Rating,Runtime (mins),Year,Genres,Num Votes,Release Date,Directors
tt0110413,9,2020-01-01,Léon: The Professional,Léon,https://www.imdb.com/title/tt0110413,Movie,8.5,110,1994,Drama,1,1994-09-14,Luc Besson
tt0903747,10,2021-01-01,Breaking Bad,Breaking Bad,https://www.imdb.com/title/tt0903747,TV Series,9.5,49,2008,Drama,1,2008-01-20,
tt9999999,6,2021-02-01,Some Lost Film,Some Lost Film,https://www.imdb.com/title/tt9999999,Movie,6.0,90,1990,Drama,1,1990-01-01,
"""
# Older exports have no "Original Title" column and camelCase title types.
IMDB_OLD = """Const,Your Rating,Date Rated,Title,URL,Title Type,IMDb Rating,Runtime (mins),Year,Genres,Num Votes,Release Date,Directors
tt0110413,8,2022-03-04,Léon: The Professional,https://www.imdb.com/title/tt0110413,movie,8.5,110,1994,Drama,1,1994-09-14,Luc Besson
"""


def test_imdb_import_matches_movies_skips_tv_and_reimports_idempotently(
    client: TestClient,
) -> None:
    job = upload(client, "ratings.csv", IMDB_NEW.encode())
    assert job["source"] == "imdb" and job["status"] == "done"
    assert job["counts"] == {"pending": 0, "matched": 1, "review": 1, "skipped": 1}

    page = ratings(client)
    assert page["total"] == 1
    leon = page["items"][0]
    assert (leon["tmdb_id"], leon["rating"], leon["original_language"]) == (101, 9.0, "fr")

    job = upload(client, "ratings.csv", IMDB_OLD.encode())
    assert job["counts"]["matched"] == 1
    page = ratings(client)
    assert page["total"] == 1 and page["items"][0]["rating"] == 8.0


def letterboxd_zip(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, text in files.items():
            archive.writestr(name, text)
    return buffer.getvalue()


LETTERBOXD = {
    "ratings.csv": """Date,Name,Year,Letterboxd URI,Rating
2024-05-01,Kumbalangi Nights,2019,https://boxd.it/a,4.5
2024-05-02,Drishyam,2013,https://boxd.it/b,5
2024-05-03,Premam,2015,https://boxd.it/c,4
2024-05-04,Léon: The Professional,1994,https://boxd.it/d,3.5
""",
    "watched.csv": """Date,Name,Year,Letterboxd URI
2023-01-01,Kumbalangi Nights,2019,https://boxd.it/a
2023-01-02,Drishyam,2013,https://boxd.it/b
2023-01-03,Premam,2015,https://boxd.it/c
""",
    "diary.csv": """Date,Name,Year,Letterboxd URI,Rating,Rewatch,Tags,Watched Date
2023-06-01,Premam,2015,https://boxd.it/c2,3,Yes,,2023-05-30
""",
    "likes/films.csv": """Date,Name,Year,Letterboxd URI
2024-06-01,Premam,2015,https://boxd.it/c
""",
}


def test_letterboxd_import_matches_by_title_and_queues_ambiguous_rows(client: TestClient) -> None:
    upload(client, "ratings.csv", IMDB_NEW.encode())
    job = upload(client, "letterboxd-export.zip", letterboxd_zip(LETTERBOXD))
    assert job["source"] == "letterboxd" and job["status"] == "done"
    # Kumbalangi Nights, Premam (not its 2016 namesake), and Léon match; Drishyam is ambiguous.
    assert job["counts"]["matched"] == 3 and job["counts"]["review"] == 1

    review = client.get(f"/api/v1/imports/{job['id']}/rows").json()
    assert [r["title"] for r in review] == ["Drishyam"]
    assert {c["tmdb_id"] for c in review[0]["candidates"]} == {301, 302}
    resolved = client.post(
        f"/api/v1/imports/{job['id']}/rows/{review[0]['id']}/resolve", json={"tmdb_id": 301}
    )
    assert resolved.json()["status"] == "matched"

    by_id = {item["tmdb_id"]: item for item in ratings(client)["items"]}
    assert set(by_id) == {101, 201, 301, 401}
    assert by_id[201]["rating"] == 9.0  # 4.5 stars
    assert by_id[401]["favorite"] is True and by_id[401]["rating"] == 8.0
    # Léon: Letterboxd's 2024 rating is newer than IMDb's 2020 one.
    assert (by_id[101]["rating"], by_id[101]["source"]) == (7.0, "letterboxd")
    languages = {lang["language"]: lang["count"] for lang in ratings(client)["languages"]}
    assert languages == {"ml": 3, "fr": 1}


# Day-first dates, all with days up to 12, so only their newest-first order tells them
# from month-first ones.
NETFLIX_HISTORY = """Title,Date
"Kumbalangi Nights","05/03/24"
"Dark: Season 1: Lies","02/03/24"
"Dark: Season 1: Secrets","01/03/24"
"Léon: The Professional","10/02/24"
"Our Planet: Jungles","03/02/24"
"Premam","01/12/15"
"Drishyam","04/11/15"
"Dune: Part Two","01/10/15"
"""


def test_netflix_history_marks_films_watched_and_skips_series(client: TestClient) -> None:
    job = upload(client, "NetflixViewingHistory.csv", NETFLIX_HISTORY.encode())
    assert job["source"] == "netflix" and job["status"] == "done"
    # Dark is one series row; Our Planet is a show TMDb knows; "Part Two" isn't an episode.
    assert job["counts"] == {"pending": 0, "matched": 4, "review": 1, "skipped": 2}
    review = client.get(f"/api/v1/imports/{job['id']}/rows").json()
    assert [r["title"] for r in review] == ["Dune: Part Two"]

    entries = {e["tmdb_id"]: e for e in client.get("/api/v1/me/export").json()["entries"]}
    # Premam was watched in 2015, so not the 2016 Telugu remake, which is too well known
    # to rule out by votes; the Malayalam Drishyam has 26 times its namesake's votes.
    assert set(entries) == {101, 201, 301, 401}
    assert entries[201]["watched_at"] == "2024-03-05" and entries[201]["rating"] is None
    assert all(e["watched"] and e["source"] == "netflix" for e in entries.values())


def test_imports_need_a_valid_tmdb_key(tmp_path: Path) -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.route(host="api.themoviedb.org").mock(side_effect=fake_tmdb)
        client = TestClient(
            create_app(Settings(data_dir=tmp_path, secret_key="t", static_dir=None))
        )
        admin = {"username": "a", "display_name": "A", "password": "password1", "region": "IN"}
        client.post("/api/v1/setup", json=admin)

        files = {"file": ("ratings.csv", IMDB_NEW.encode())}
        assert client.post("/api/v1/imports", files=files).status_code == 409
        wrong = {"api_key": "wrong-key-wrong-key-wrong"}
        assert client.put("/api/v1/settings/tmdb", json=wrong).status_code == 400
        assert client.get("/api/v1/settings").json()["tmdb_configured"] is False

        assert client.put("/api/v1/settings/tmdb", json={"api_key": KEY}).status_code == 200
        notes = {"file": ("notes.csv", b"a,b\n1,2\n")}
        assert client.post("/api/v1/imports", files=notes).status_code == 400


def test_tmdb_client_waits_out_rate_limits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(time, "sleep", sleeps.append)
    app = create_app(Settings(data_dir=tmp_path, secret_key="t", static_dir=None))
    client = TmdbClient(KEY, app.state.engine)
    with respx.mock as mock:
        mock.get("https://api.themoviedb.org/3/configuration").mock(
            side_effect=[
                httpx.Response(429, headers={"Retry-After": "3"}),
                httpx.Response(200, json={"ok": True}),
            ]
        )
        assert client.get("/configuration") == {"ok": True}
    assert 3.0 in sleeps


def test_fetching_many_titles_leaves_the_database_writable(tmp_path: Path) -> None:
    # A first feed fetches hundreds of films; ratings saved meanwhile must not time out
    # waiting for SQLite's write lock.
    app = create_app(Settings(data_dir=tmp_path, secret_key="t", static_dir=None))
    blocked: list[str] = []

    class SlowTmdb:
        def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
            if path != "/movie/1":
                time.sleep(0.2)  # long enough for film 1 to be stored first
                db = sqlite3.connect(tmp_path / "iwanttowatch.db", timeout=0)
                try:
                    db.execute("BEGIN IMMEDIATE")
                    db.rollback()
                except sqlite3.OperationalError:
                    blocked.append(path)
                finally:
                    db.close()
            return {**_details(201), "id": int(path.rsplit("/", 1)[1])}

    with Session(app.state.engine) as session:
        titles = ensure_titles(session, cast(TmdbClient, SlowTmdb()), [1, 2, 3])
        session.commit()
    assert sorted(titles) == [1, 2, 3]
    assert blocked == []
