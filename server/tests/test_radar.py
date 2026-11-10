"""Tests for Acquisition Radar & Theatrical Tracking."""

from datetime import date

import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_imports import KEY
from test_radarr import API_KEY, RADARR, FakeRadarr

from iwanttowatch.models import (
    Availability,
    LibraryItem,
    Recommendation,
    Title,
    User,
    UserTitle,
)


@pytest.fixture
def fake_radarr(mock: respx.MockRouter) -> FakeRadarr:
    fake = FakeRadarr()
    mock.route(host="radarr.test").mock(side_effect=fake)
    return fake


def _setup_services(client: TestClient) -> None:
    client.put("/api/v1/settings/tmdb", json={"api_key": KEY})
    client.put(
        "/api/v1/settings/radarr",
        json={
            "url": RADARR,
            "api_key": API_KEY,
            "root_folder_path": "/data/movies/english",
        },
    )


def test_radar_missing_from_streaming(client: TestClient, fake_radarr: FakeRadarr) -> None:
    _setup_services(client)

    app = client.app
    engine = app.state.engine  # type: ignore[attr-defined]

    with Session(engine) as session:
        user = session.scalars(select(User).where(User.username == "riya")).one()
        # User subscribes to Netflix (id 8) in IN
        user.subscriptions = [8]
        session.commit()

        # Add titles 101, 201, 301, 401
        for tid, title_name in [
            (101, "Léon: The Professional"),
            (201, "Kumbalangi Nights"),
            (301, "Drishyam"),
            (401, "Premam"),
        ]:
            session.add(
                Title(
                    tmdb_id=tid,
                    title=title_name,
                    original_title=title_name,
                    original_language="ml" if tid > 101 else "fr",
                    year=2020,
                    genres=["Drama"],
                    release_date=date(2020, 1, 1),
                )
            )

        # 101 is in Jellyfin library -> should be excluded from missing
        session.add(
            LibraryItem(
                user_id=user.id,
                item_id="jf-101",
                name="Léon: The Professional",
                tmdb_id=101,
            )
        )

        # 201 is on Netflix (provider 8) -> should be excluded (streamable)
        session.add(
            Availability(
                tmdb_id=201,
                region="IN",
                offers=[{"provider_id": 8, "name": "Netflix", "kind": "flatrate"}],
            )
        )

        # 301 and 401 have no flatrate offers in subscriptions -> unstreamable!
        session.add(
            Availability(
                tmdb_id=301,
                region="IN",
                offers=[{"provider_id": 999, "name": "Other Service", "kind": "flatrate"}],
            )
        )
        session.add(
            Availability(
                tmdb_id=401,
                region="IN",
                offers=[],
            )
        )

        # High match recommendations: 301 (88%), 401 (78%), 201 (90%), 101 (95%)
        session.add(
            Recommendation(user_id=user.id, tmdb_id=101, score=0.95, rank=1, reasons=["Great film"])
        )
        session.add(
            Recommendation(user_id=user.id, tmdb_id=201, score=0.90, rank=2, reasons=["Great film"])
        )
        session.add(
            Recommendation(
                user_id=user.id, tmdb_id=301, score=0.88, rank=3, reasons=["Like Kumbalangi Nights"]
            )
        )
        session.add(
            Recommendation(
                user_id=user.id, tmdb_id=401, score=0.78, rank=4, reasons=["Like Drishyam"]
            )
        )
        session.commit()

    # Pre-populate Radarr with 301 as downloading
    fake_radarr.movies[301] = {
        "id": 10,
        "title": "Drishyam",
        "tmdbId": 301,
        "year": 2013,
        "hasFile": False,
        "monitored": True,
        "titleSlug": "drishyam-2013",
    }

    res = client.get("/api/v1/library/radar/missing?min_match=70")
    assert res.status_code == 200
    data = res.json()
    assert data["radarr_configured"] is True
    # 101 is in library, 201 is on Netflix -> only 301 and 401 should be returned
    assert data["total_missing"] == 2

    items = {item["tmdb_id"]: item for item in data["items"]}
    assert 301 in items
    assert 401 in items
    assert 101 not in items
    assert 201 not in items

    assert items[301]["match_pct"] == 88
    assert items[301]["radarr_status"] == "downloading"
    assert items[301]["radarr_movie_id"] == 10

    assert items[401]["match_pct"] == 78
    assert items[401]["radarr_status"] == "to_request"


def test_radar_theatrical_tracking(client: TestClient, fake_radarr: FakeRadarr) -> None:
    _setup_services(client)

    app = client.app
    engine = app.state.engine  # type: ignore[attr-defined]

    with Session(engine) as session:
        user = session.scalars(select(User).where(User.username == "riya")).one()
        # Add Title 301 first
        session.add(
            Title(
                tmdb_id=301,
                title="Drishyam",
                original_title="Drishyam",
                original_language="ml",
                year=2013,
                genres=["Drama"],
                release_date=date(2013, 12, 19),
            )
        )
        # Rate title 301 highly so taste model has positive training signals
        session.add(
            UserTitle(
                user_id=user.id,
                tmdb_id=301,
                source="app",
                rating=9.0,
                rated_at=date(2024, 1, 1),
                watched=True,
            )
        )
        session.commit()

    res = client.get("/api/v1/library/radar/theatrical?min_match=10")
    assert res.status_code == 200
    data = res.json()
    assert data["radarr_configured"] is True
    assert data["region"] == "IN"
    assert data["total_theatrical"] > 0
    # Theatrical item fields
    item = data["items"][0]
    assert item["is_theatrical"] is True
    assert "match_pct" in item
    assert item["radarr_status"] in ("to_track", "tracking", "downloaded")


def test_radar_queue_candidates(client: TestClient, fake_radarr: FakeRadarr) -> None:
    _setup_services(client)

    # Queue title 401 with minimumAvailability="released"
    res = client.post(
        "/api/v1/library/radar/queue",
        json={"tmdb_ids": [401], "minimum_availability": "released"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["requested_count"] == 1
    assert data["items"][0]["tmdb_id"] == 401
    assert data["items"][0]["status"] == "queued"

    # Verify FakeRadarr received movie with monitored=True
    assert 401 in fake_radarr.movies
    assert fake_radarr.movies[401]["monitored"] is True
