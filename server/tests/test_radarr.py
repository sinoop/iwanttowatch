"""Tests for Radarr client, settings endpoints, and title download triggers."""

import json
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from test_imports import KEY

from iwanttowatch.radarr import RadarrAuthError, RadarrClient, RadarrError

RADARR = "http://radarr.test:7878"
API_KEY = "radarr-secret-key"


class FakeRadarr:
    def __init__(self) -> None:
        self.movies: dict[int, dict[str, Any]] = {}
        self.commands: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        key = request.headers.get("X-Api-Key")
        if key != API_KEY:
            return httpx.Response(401, json={"message": "Unauthorized"})

        path = request.url.path
        if path == "/api/v3/system/status" and request.method == "GET":
            return httpx.Response(200, json={"version": "5.3.6", "appName": "Radarr"})

        if path == "/api/v3/qualityprofile" and request.method == "GET":
            return httpx.Response(
                200,
                json=[
                    {"id": 1, "name": "HD - 1080p"},
                    {"id": 2, "name": "Ultra-HD"},
                ],
            )

        if path == "/api/v3/rootfolder" and request.method == "GET":
            return httpx.Response(
                200,
                json=[
                    {"id": 1, "path": "/data/movies/english", "freeSpace": 50000000000},
                    {"id": 2, "path": "/data/movies/malayalam", "freeSpace": 20000000000},
                ],
            )

        if path == "/api/v3/movie" and request.method == "GET":
            tmdb_id_str = request.url.params.get("tmdbId")
            if tmdb_id_str:
                if int(tmdb_id_str) in self.movies:
                    return httpx.Response(200, json=[self.movies[int(tmdb_id_str)]])
                return httpx.Response(200, json=[])
            return httpx.Response(200, json=list(self.movies.values()))

        if path == "/api/v3/movie/lookup/tmdb" and request.method == "GET":
            tmdb_id = int(request.url.params["tmdbId"])
            return httpx.Response(
                200,
                json={
                    "title": f"Movie {tmdb_id}",
                    "tmdbId": tmdb_id,
                    "year": 2024,
                    "titleSlug": f"movie-{tmdb_id}",
                },
            )

        if path == "/api/v3/movie" and request.method == "POST":
            data = json.loads(request.content)
            tmdb_id = data["tmdbId"]
            movie = {
                "id": len(self.movies) + 1,
                "title": data.get("title", f"Movie {tmdb_id}"),
                "tmdbId": tmdb_id,
                "year": data.get("year", 2024),
                "titleSlug": data.get("titleSlug", f"movie-{tmdb_id}"),
                "rootFolderPath": data.get("rootFolderPath"),
                "hasFile": False,
                "monitored": data.get("monitored", True),
                "isAvailable": True,
            }
            self.movies[tmdb_id] = movie
            return httpx.Response(201, json=movie)

        if path.startswith("/api/v3/movie/") and request.method == "PUT":
            data = json.loads(request.content)
            tmdb_id = data["tmdbId"]
            self.movies[tmdb_id] = data
            return httpx.Response(200, json=data)

        if path == "/api/v3/command" and request.method == "POST":
            data = json.loads(request.content)
            self.commands.append(data)
            return httpx.Response(201, json={"id": 1, "name": data.get("name")})

        if path.startswith("/api/v3/movie/") and request.method == "DELETE":
            movie_id_str = path.split("/")[-1]
            if movie_id_str.isdigit():
                m_id = int(movie_id_str)
                to_delete = [t for t, m in self.movies.items() if m.get("id") == m_id]
                for t in to_delete:
                    del self.movies[t]
                return httpx.Response(200, json={})
            return httpx.Response(404)

        return httpx.Response(404)


@pytest.fixture
def fake_radarr(mock: respx.MockRouter) -> FakeRadarr:
    fake = FakeRadarr()
    mock.route(host="radarr.test").mock(side_effect=fake)
    return fake


def test_radarr_client(fake_radarr: FakeRadarr) -> None:
    client = RadarrClient(RADARR, API_KEY)
    status = client.system_status()
    assert status["appName"] == "Radarr"

    profiles = client.quality_profiles()
    assert len(profiles) == 2
    assert profiles[0]["name"] == "HD - 1080p"

    folders = client.root_folders()
    assert len(folders) == 2
    assert folders[0]["path"] == "/data/movies/english"
    assert folders[1]["path"] == "/data/movies/malayalam"

    # Not found yet
    assert client.get_movie_by_tmdb(496243) is None

    # Add movie
    added = client.add_movie(496243, quality_profile_id=1, root_folder_path="/data/movies")
    assert added["tmdbId"] == 496243
    assert added["monitored"] is True

    # Now found
    found = client.get_movie_by_tmdb(496243)
    assert found is not None
    assert found["id"] == added["id"]


def test_radarr_client_auth_error(mock: respx.MockRouter) -> None:
    mock.route(host="radarr.test").mock(
        return_value=httpx.Response(401, json={"message": "Bad key"})
    )
    client = RadarrClient(RADARR, "wrong-key")
    with pytest.raises(RadarrAuthError):
        client.system_status()


def test_radarr_client_unreachable() -> None:
    client = RadarrClient("http://nonexistent.local:7878", "key", timeout=0.1)
    with pytest.raises(RadarrError):
        client.system_status()


def test_radarr_settings_flow(client: TestClient, fake_radarr: FakeRadarr) -> None:
    # Initially radarr is unconfigured
    settings = client.get("/api/v1/settings").json()
    assert settings["radarr"]["configured"] is False

    # Connect with wrong key fails
    bad = client.put("/api/v1/settings/radarr", json={"url": RADARR, "api_key": "bad-key"})
    assert bad.status_code == 400

    # Connect with valid credentials including language root folder mappings
    ok = client.put(
        "/api/v1/settings/radarr",
        json={
            "url": RADARR,
            "api_key": API_KEY,
            "minimum_availability": "announced",
            "language_root_folders": {"ml": "/data/movies/malayalam"},
        },
    )
    assert ok.status_code == 200
    radarr_data = ok.json()["radarr"]
    assert radarr_data["configured"] is True
    assert radarr_data["url"] == RADARR
    assert radarr_data["quality_profile_id"] == 1
    assert radarr_data["root_folder_path"] == "/data/movies/english"
    assert radarr_data["language_root_folders"] == {"ml": "/data/movies/malayalam"}
    assert len(radarr_data["profiles"]) == 2
    assert len(radarr_data["root_folders"]) == 2

    # Disconnect
    del_res = client.delete("/api/v1/settings/radarr")
    assert del_res.status_code == 200
    assert del_res.json()["radarr"]["configured"] is False


def test_title_radarr_trigger(client: TestClient, fake_radarr: FakeRadarr) -> None:
    # Configure TMDb and Radarr with language root folders
    client.put("/api/v1/settings/tmdb", json={"api_key": KEY})
    client.put(
        "/api/v1/settings/radarr",
        json={
            "url": RADARR,
            "api_key": API_KEY,
            "root_folder_path": "/data/movies/english",
            "language_root_folders": {"ml": "/data/movies/malayalam"},
        },
    )

    # Kumbalangi Nights (tmdb_id = 201) has original_language = "ml"
    tmdb_id = 201
    title_res = client.get(f"/api/v1/titles/{tmdb_id}")
    assert title_res.status_code == 200
    title = title_res.json()
    assert title["radarr"] is not None
    assert title["radarr"]["configured"] is True
    assert title["radarr"]["status"] == "not_added"
    assert title["radarr"]["has_file"] is False

    # Queue download via Radarr
    resp = client.post(f"/api/v1/titles/{tmdb_id}/radarr")
    assert resp.status_code == 200
    data = resp.json()
    assert data["configured"] is True
    assert data["status"] == "downloading"
    assert data["monitored"] is True
    assert data["has_file"] is False

    # Check that FakeRadarr received the language-specific root folder path!
    assert fake_radarr.movies[tmdb_id]["rootFolderPath"] == "/data/movies/malayalam"

    # Léon: The Professional (tmdb_id = 101) has original_language = "fr", not mapped
    # so it must fall back to the default root folder
    client.post("/api/v1/titles/101/radarr")
    assert fake_radarr.movies[101]["rootFolderPath"] == "/data/movies/english"

    # Re-checking title now reflects downloading status
    title_after = client.get(f"/api/v1/titles/{tmdb_id}").json()
    assert title_after["radarr"]["status"] == "downloading"
    assert title_after["radarr"]["monitored"] is True


def test_radarr_settings_auto_sync(client: TestClient, fake_radarr: FakeRadarr) -> None:
    # Connect with auto_sync_shortlist enabled
    ok = client.put(
        "/api/v1/settings/radarr",
        json={
            "url": RADARR,
            "api_key": API_KEY,
            "auto_sync_shortlist": True,
        },
    )
    assert ok.status_code == 200
    assert ok.json()["radarr"]["auto_sync_shortlist"] is True

    # Check GET /api/v1/settings
    settings = client.get("/api/v1/settings").json()
    assert settings["radarr"]["auto_sync_shortlist"] is True

    # Disable auto sync
    update = client.put(
        "/api/v1/settings/radarr",
        json={
            "url": RADARR,
            "api_key": API_KEY,
            "auto_sync_shortlist": False,
        },
    )
    assert update.status_code == 200
    assert update.json()["radarr"]["auto_sync_shortlist"] is False


def test_radarr_shortlist_inspect_and_batch_sync(
    client: TestClient, fake_radarr: FakeRadarr
) -> None:
    client.put("/api/v1/settings/tmdb", json={"api_key": KEY})
    client.put(
        "/api/v1/settings/radarr",
        json={
            "url": RADARR,
            "api_key": API_KEY,
            "root_folder_path": "/data/movies/english",
            "language_root_folders": {"ml": "/data/movies/malayalam"},
            "auto_sync_shortlist": False,
        },
    )

    # Shortlist 401 (Premam, lang=ml, unstreamable)
    res401 = client.put("/api/v1/titles/401/shortlist")
    assert res401.status_code == 204

    # Pre-populate 201 in FakeRadarr as already downloaded (hasFile=True)
    fake_radarr.movies[201] = {
        "id": 10,
        "title": "Kumbalangi Nights",
        "tmdbId": 201,
        "year": 2019,
        "titleSlug": "kumbalangi-nights-201",
        "rootFolderPath": "/data/movies/malayalam",
        "hasFile": True,
        "monitored": True,
        "isAvailable": True,
    }
    # Shortlist 201 as well
    client.put("/api/v1/titles/201/shortlist")

    # Inspect shortlist radarr status
    insp = client.get("/api/v1/titles/shortlist/radarr?scope=user")
    assert insp.status_code == 200
    data = insp.json()
    assert data["configured"] is True
    assert data["total_shortlisted"] == 2
    assert data["unstreamable_count"] == 2
    assert data["to_request_count"] == 1  # 401 is pending request
    assert data["downloaded_count"] == 1  # 201 hasFile
    assert data["downloading_count"] == 0

    # Batch sync shortlist to Radarr
    batch = client.post("/api/v1/titles/shortlist/radarr", json={"scope": "user"})
    assert batch.status_code == 200
    batch_res = batch.json()
    assert batch_res["requested_count"] == 1
    assert batch_res["downloaded_count"] == 1

    # Verify FakeRadarr now has 401 with language-routed folder
    assert 401 in fake_radarr.movies
    assert fake_radarr.movies[401]["rootFolderPath"] == "/data/movies/malayalam"

    # Inspect again: to_request_count is now 0, downloading_count is 1
    insp2 = client.get("/api/v1/titles/shortlist/radarr?scope=user")
    assert insp2.status_code == 200
    d2 = insp2.json()
    assert d2["to_request_count"] == 0
    assert d2["downloading_count"] == 1
    assert d2["downloaded_count"] == 1


def test_radarr_auto_sync_on_shortlist(client: TestClient, fake_radarr: FakeRadarr) -> None:
    client.put("/api/v1/settings/tmdb", json={"api_key": KEY})
    # Configure with auto-sync enabled
    client.put(
        "/api/v1/settings/radarr",
        json={
            "url": RADARR,
            "api_key": API_KEY,
            "root_folder_path": "/data/movies/english",
            "language_root_folders": {"ml": "/data/movies/malayalam"},
            "auto_sync_shortlist": True,
        },
    )

    # 401 is unstreamable; adding to shortlist should automatically queue in Radarr!
    assert 401 not in fake_radarr.movies
    res = client.put("/api/v1/titles/401/shortlist")
    assert res.status_code == 204
    assert 401 in fake_radarr.movies
    assert fake_radarr.movies[401]["rootFolderPath"] == "/data/movies/malayalam"
    assert fake_radarr.movies[401]["monitored"] is True

    # Now turn auto-sync off
    client.put(
        "/api/v1/settings/radarr",
        json={
            "url": RADARR,
            "api_key": API_KEY,
            "auto_sync_shortlist": False,
        },
    )
    # Shortlist 301; should NOT be queued in Radarr
    assert 301 not in fake_radarr.movies
    res301 = client.put("/api/v1/titles/301/shortlist")
    assert res301.status_code == 204
    assert 301 not in fake_radarr.movies


def test_radarr_group_shortlist_sync(client: TestClient, fake_radarr: FakeRadarr) -> None:
    client.put("/api/v1/settings/tmdb", json={"api_key": KEY})
    client.put(
        "/api/v1/settings/radarr",
        json={
            "url": RADARR,
            "api_key": API_KEY,
            "root_folder_path": "/data/movies/english",
            "language_root_folders": {"ml": "/data/movies/malayalam"},
            "auto_sync_shortlist": True,
        },
    )

    # Add 401 to group shortlist; with auto-sync on, should queue in Radarr!
    assert 401 not in fake_radarr.movies
    res = client.put("/api/v1/together/shortlist/401")
    assert res.status_code == 204
    assert 401 in fake_radarr.movies

    # Inspect group shortlist
    group_insp = client.get("/api/v1/titles/shortlist/radarr?scope=group")
    assert group_insp.status_code == 200
    assert group_insp.json()["total_shortlisted"] == 1
    assert group_insp.json()["downloading_count"] == 1


def test_title_radarr_decoupled_and_profiling_flag(
    client: TestClient, fake_radarr: FakeRadarr, caplog: pytest.LogCaptureFixture
) -> None:
    client.put("/api/v1/settings/tmdb", json={"api_key": KEY})
    client.put(
        "/api/v1/settings/radarr",
        json={
            "url": RADARR,
            "api_key": API_KEY,
            "root_folder_path": "/data/movies/english",
        },
    )

    with caplog.at_level("INFO"):
        res = client.get("/api/v1/titles/201?include_radarr=false")
        assert res.status_code == 200
        assert res.json()["radarr"] is None

        radarr_res = client.get("/api/v1/titles/201/radarr")
        assert radarr_res.status_code == 200
        assert radarr_res.json()["configured"] is True
        assert radarr_res.json()["status"] == "not_added"

    assert not any("PROFILE GET /api/v1/titles/201" in r.message for r in caplog.records)

    client.app.state.debug = True  # type: ignore[attr-defined]
    caplog.clear()
    with caplog.at_level("INFO"):
        res_dbg = client.get("/api/v1/titles/201?include_radarr=false")
        assert res_dbg.status_code == 200
        radarr_dbg = client.get("/api/v1/titles/201/radarr")
        assert radarr_dbg.status_code == 200

    messages = [r.message for r in caplog.records]
    assert any("PROFILE GET /api/v1/titles/201 " in m and "load=" in m for m in messages)
    assert any("PROFILE GET /api/v1/titles/201/radarr" in m for m in messages)

    # Also verify runtime toggle via /api/v1/settings/profiling
    client.app.state.debug = False  # type: ignore[attr-defined]
    assert (
        client.put("/api/v1/settings/profiling", json={"enabled": True}).json()["profiling_enabled"]
        is True
    )
    caplog.clear()
    with caplog.at_level("INFO"):
        assert client.get("/api/v1/titles/201?include_radarr=false").status_code == 200
    assert any("PROFILE GET /api/v1/titles/201 " in r.message for r in caplog.records)

    assert (
        client.put("/api/v1/settings/profiling", json={"enabled": False}).json()[
            "profiling_enabled"
        ]
        is False
    )
    caplog.clear()
    with caplog.at_level("INFO"):
        assert client.get("/api/v1/titles/201?include_radarr=false").status_code == 200
    assert not any("PROFILE GET /api/v1/titles/201 " in r.message for r in caplog.records)
