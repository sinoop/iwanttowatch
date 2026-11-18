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


def test_radar_auto_downloader_config_and_guardrails(
    client: TestClient, fake_radarr: FakeRadarr
) -> None:
    _setup_services(client)

    # Check default auto-download settings and reported disk space
    status_res = client.get("/api/v1/library/radar/auto-download")
    assert status_res.status_code == 200
    status_data = status_res.json()
    assert status_data["radarr_configured"] is True
    assert status_data["config"]["enabled"] is False
    assert status_data["config"]["min_match"] == 85
    assert status_data["config"]["min_free_space_gb"] == 20
    assert status_data["config"]["weekly_limit"] == 3
    assert status_data["config"]["min_votes"] == 500
    assert status_data["config"]["released_only"] is True
    assert len(status_data["root_folders"]) == 2
    assert status_data["min_free_space_bytes"] == 20000000000

    app = client.app
    engine = app.state.engine  # type: ignore[attr-defined]

    with Session(engine) as session:
        user = session.scalars(select(User).where(User.username == "riya")).one()
        user.subscriptions = [8]

        # 301: 90% match, released, 5000 votes (eligible!)
        # 401: 82% match, released, 3000 votes (eligible only when min_match <= 82)
        # 501: 92% match, released, 100 votes (below 500 vote floor)
        # 601: 94% match, In Production, 2000 votes (unreleased)
        session.add_all(
            [
                Title(
                    tmdb_id=301,
                    title="Drishyam",
                    original_title="Drishyam",
                    original_language="ml",
                    year=2013,
                    status="Released",
                    release_date=date(2013, 12, 19),
                    vote_count=5000,
                    genres=["Drama"],
                ),
                Title(
                    tmdb_id=401,
                    title="Premam",
                    original_title="Premam",
                    original_language="ml",
                    year=2015,
                    status="Released",
                    release_date=date(2015, 5, 29),
                    vote_count=3000,
                    genres=["Romance"],
                ),
                Title(
                    tmdb_id=501,
                    title="Obscure Indie",
                    original_title="Obscure Indie",
                    original_language="en",
                    year=2021,
                    status="Released",
                    release_date=date(2021, 3, 10),
                    vote_count=100,
                    genres=["Drama"],
                ),
                Title(
                    tmdb_id=601,
                    title="Future Blockbuster",
                    original_title="Future Blockbuster",
                    original_language="en",
                    year=2028,
                    status="In Production",
                    release_date=date(2028, 12, 1),
                    vote_count=2000,
                    genres=["Sci-Fi"],
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                Availability(tmdb_id=301, region="IN", offers=[]),
                Availability(tmdb_id=401, region="IN", offers=[]),
                Availability(tmdb_id=501, region="IN", offers=[]),
                Availability(tmdb_id=601, region="IN", offers=[]),
                Recommendation(user_id=user.id, tmdb_id=601, score=0.94, rank=1, reasons=["Great"]),
                Recommendation(user_id=user.id, tmdb_id=501, score=0.92, rank=2, reasons=["Great"]),
                Recommendation(user_id=user.id, tmdb_id=301, score=0.90, rank=3, reasons=["Great"]),
                Recommendation(user_id=user.id, tmdb_id=401, score=0.82, rank=4, reasons=["Great"]),
            ]
        )
        session.commit()

    # 1. Test HDD remaining space block: require 60 GB free (root folder has ~46.6 GB)
    put_high_space = client.put(
        "/api/v1/library/radar/auto-download",
        json={
            "enabled": True,
            "min_match": 80,
            "min_free_space_gb": 60,
            "weekly_limit": 3,
            "min_votes": 500,
            "released_only": True,
        },
    )
    assert put_high_space.status_code == 200
    assert put_high_space.json()["has_sufficient_space"] is False

    run_low_space = client.post("/api/v1/library/radar/auto-download/run")
    assert run_low_space.status_code == 200
    low_space_data = run_low_space.json()
    assert low_space_data["queued_count"] == 0
    assert low_space_data["skipped_low_space"] == 2  # 301 and 401 blocked by low space
    assert low_space_data["skipped_votes"] == 1  # 501 blocked by votes
    assert low_space_data["skipped_unreleased"] == 1  # 601 blocked by unreleased
    assert 301 not in fake_radarr.movies

    # 2. Lower min_free_space_gb to 10 GB and set min_match to 80% with weekly_limit=1
    client.put(
        "/api/v1/library/radar/auto-download",
        json={
            "enabled": True,
            "min_match": 80,
            "min_free_space_gb": 10,
            "weekly_limit": 1,
            "min_votes": 500,
            "released_only": True,
        },
    )

    run_capped = client.post("/api/v1/library/radar/auto-download/run")
    assert run_capped.status_code == 200
    capped_data = run_capped.json()
    assert capped_data["queued_count"] == 1
    assert capped_data["queued_items"][0]["tmdb_id"] == 301
    assert capped_data["skipped_weekly_cap"] == 1  # 401 skipped due to weekly_limit=1
    assert 301 in fake_radarr.movies
    assert 401 not in fake_radarr.movies

    # 3. Increase weekly_limit to 3 and run again -> 401 (82% match >= 80%) is now queued
    client.put(
        "/api/v1/library/radar/auto-download",
        json={
            "enabled": True,
            "min_match": 80,
            "min_free_space_gb": 10,
            "weekly_limit": 3,
            "min_votes": 500,
            "released_only": True,
        },
    )
    run_second = client.post("/api/v1/library/radar/auto-download/run")
    assert run_second.status_code == 200
    second_data = run_second.json()
    assert second_data["queued_count"] == 1
    assert second_data["queued_items"][0]["tmdb_id"] == 401
    assert second_data["status"]["downloads_this_week"] == 2
    assert second_data["status"]["remaining_weekly_quota"] == 1
    assert 401 in fake_radarr.movies
