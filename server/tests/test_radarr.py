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
                    {"id": 1, "path": "/data/movies", "freeSpace": 50000000000},
                ],
            )

        if path == "/api/v3/movie" and request.method == "GET":
            tmdb_id_str = request.url.params.get("tmdbId")
            if tmdb_id_str and int(tmdb_id_str) in self.movies:
                return httpx.Response(200, json=[self.movies[int(tmdb_id_str)]])
            return httpx.Response(200, json=[])

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
    assert len(folders) == 1
    assert folders[0]["path"] == "/data/movies"

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

    # Connect with valid credentials
    ok = client.put(
        "/api/v1/settings/radarr",
        json={"url": RADARR, "api_key": API_KEY, "minimum_availability": "announced"},
    )
    assert ok.status_code == 200
    radarr_data = ok.json()["radarr"]
    assert radarr_data["configured"] is True
    assert radarr_data["url"] == RADARR
    assert radarr_data["quality_profile_id"] == 1
    assert radarr_data["root_folder_path"] == "/data/movies"
    assert len(radarr_data["profiles"]) == 2
    assert len(radarr_data["root_folders"]) == 1

    # Disconnect
    del_res = client.delete("/api/v1/settings/radarr")
    assert del_res.status_code == 200
    assert del_res.json()["radarr"]["configured"] is False


def test_title_radarr_trigger(client: TestClient, fake_radarr: FakeRadarr) -> None:
    # Configure TMDb and Radarr
    client.put("/api/v1/settings/tmdb", json={"api_key": KEY})
    client.put("/api/v1/settings/radarr", json={"url": RADARR, "api_key": API_KEY})

    # Kumbalangi Nights tmdb_id = 201
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

    # Re-checking title now reflects downloading status
    title_after = client.get(f"/api/v1/titles/{tmdb_id}").json()
    assert title_after["radarr"]["status"] == "downloading"
    assert title_after["radarr"]["monitored"] is True
