"""Tests for Declutter Assistant: inspection, household protection, whitelisting, and deletion."""

from datetime import date, timedelta

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
    ShortlistItem,
    Title,
    User,
    UserTitle,
)


@pytest.fixture
def fake_radarr(mock: respx.MockRouter) -> FakeRadarr:
    fake = FakeRadarr()
    mock.route(host="radarr.test").mock(side_effect=fake)
    return fake


def _setup_radarr(client: TestClient) -> None:
    client.put("/api/v1/settings/tmdb", json={"api_key": KEY})
    client.put(
        "/api/v1/settings/radarr",
        json={
            "url": RADARR,
            "api_key": API_KEY,
            "root_folder_path": "/data/movies/english",
        },
    )


def test_declutter_categories_and_protection(client: TestClient, fake_radarr: FakeRadarr) -> None:
    _setup_radarr(client)

    # Populate FakeRadarr with 4 movies with file sizes
    fake_radarr.movies[101] = {
        "id": 1,
        "title": "Disliked Movie",
        "tmdbId": 101,
        "year": 2021,
        "hasFile": True,
        "monitored": True,
        "sizeOnDisk": 15000000000,  # ~15 GB
    }
    fake_radarr.movies[102] = {
        "id": 2,
        "title": "Abandoned Movie",
        "tmdbId": 102,
        "year": 2022,
        "hasFile": True,
        "monitored": True,
        "sizeOnDisk": 10000000000,  # ~10 GB
    }
    fake_radarr.movies[103] = {
        "id": 3,
        "title": "Streamable Redundant Movie",
        "tmdbId": 103,
        "year": 2020,
        "hasFile": True,
        "monitored": True,
        "sizeOnDisk": 8000000000,  # ~8 GB
    }
    fake_radarr.movies[104] = {
        "id": 4,
        "title": "Low Match Movie",
        "tmdbId": 104,
        "year": 2023,
        "hasFile": True,
        "monitored": True,
        "sizeOnDisk": 12000000000,  # ~12 GB
    }

    app = client.app
    engine = app.state.engine  # type: ignore[attr-defined]

    with Session(engine) as session:
        admin_user = session.scalars(select(User).where(User.username == "riya")).one()
        member_user = User(
            username="anoop",
            display_name="Anoop Joy",
            password_hash="test",
            region="IN",
            languages=["en", "ml"],
        )
        session.add(member_user)
        session.flush()

        for tmdb_id, title_str in [
            (101, "Disliked Movie"),
            (102, "Abandoned Movie"),
            (103, "Streamable Redundant Movie"),
            (104, "Low Match Movie"),
        ]:
            session.merge(
                Title(
                    tmdb_id=tmdb_id,
                    title=title_str,
                    original_title=title_str,
                    original_language="en",
                    year=2022,
                    runtime=120,
                )
            )

        # 101: Disliked by admin
        session.merge(
            UserTitle(
                user_id=admin_user.id,
                tmdb_id=101,
                source="app",
                rating=2.0,
                reaction="disliked",
                watched=True,
            )
        )

        # 102: Abandoned by admin > 30 days ago
        session.merge(
            LibraryItem(
                user_id=admin_user.id,
                item_id="item-102",
                tmdb_id=102,
                name="Abandoned Movie",
                played=False,
                last_played=date.today() - timedelta(days=45),
            )
        )

        # 103: Watched by admin, available on Netflix (user subscription)
        session.merge(
            UserTitle(
                user_id=admin_user.id,
                tmdb_id=103,
                source="app",
                rating=6.0,
                watched=True,
            )
        )
        session.merge(
            Availability(
                tmdb_id=103,
                region="IN",
                offers=[{"provider_id": 8, "name": "Netflix", "kind": "flatrate"}],
            )
        )
        # Give admin a subscription to Netflix (provider 8)
        admin_user.subscriptions = [8]

        # 104: Unwatched, low recommendation score (20%)
        session.merge(
            Recommendation(
                user_id=admin_user.id,
                tmdb_id=104,
                score=0.20,
                rank=1,
                reasons=["Low affinity"],
            )
        )

        # Member protects 102 by shortlisting it!
        session.merge(
            ShortlistItem(
                user_id=member_user.id,
                tmdb_id=102,
            )
        )

        session.commit()

    # Call inspection endpoint
    res = client.get("/api/v1/library/declutter")
    assert res.status_code == 200
    data = res.json()
    assert data["radarr_configured"] is True
    assert data["total_candidates"] == 4
    assert data["protected_count"] == 1  # 102 is protected!

    by_tmdb = {item["tmdb_id"]: item for item in data["items"]}

    # Verify 101: disliked
    assert by_tmdb[101]["category"] == "disliked"
    assert by_tmdb[101]["is_protected"] is False
    assert any("Rated 2/10" in r for r in by_tmdb[101]["reasons"])

    # Verify 102: abandoned and PROTECTED by Anoop's shortlist
    assert by_tmdb[102]["category"] == "abandoned"
    assert by_tmdb[102]["is_protected"] is True
    assert any("Shortlisted by Anoop Joy" in pr for pr in by_tmdb[102]["protection_reasons"])

    # Verify 103: redundant streamable on Netflix
    assert by_tmdb[103]["category"] == "redundant_streamable"
    assert by_tmdb[103]["streaming_offers"] == ["Netflix"]

    # Verify 104: low match
    assert by_tmdb[104]["category"] == "low_match"
    assert by_tmdb[104]["match_pct"] == 20

    # Test category filter
    filtered = client.get("/api/v1/library/declutter?category=disliked")
    assert filtered.status_code == 200
    assert len(filtered.json()["items"]) == 1
    assert filtered.json()["items"][0]["tmdb_id"] == 101


def test_declutter_ignore_and_delete(client: TestClient, fake_radarr: FakeRadarr) -> None:
    _setup_radarr(client)

    fake_radarr.movies[201] = {
        "id": 10,
        "title": "To Delete Movie",
        "tmdbId": 201,
        "year": 2021,
        "hasFile": True,
        "sizeOnDisk": 14000000000,
    }

    app = client.app
    engine = app.state.engine  # type: ignore[attr-defined]
    with Session(engine) as session:
        admin_user = session.scalars(select(User).where(User.username == "riya")).one()
        session.merge(
            Title(
                tmdb_id=201,
                title="To Delete Movie",
                original_title="To Delete Movie",
                original_language="en",
                year=2021,
            )
        )
        session.merge(
            UserTitle(
                user_id=admin_user.id,
                tmdb_id=201,
                source="app",
                rating=1.0,
                reaction="disliked",
            )
        )
        session.commit()

    # Initial inspection has 201
    insp1 = client.get("/api/v1/library/declutter")
    assert insp1.status_code == 200
    assert len(insp1.json()["items"]) == 1

    # Whitelist / ignore 201
    ign_res = client.post(
        "/api/v1/library/declutter/ignore", json={"tmdb_id": 201, "ignored": True}
    )
    assert ign_res.status_code == 200
    assert ign_res.json()["ignored"] is True

    # Now it is excluded from default inspection
    insp2 = client.get("/api/v1/library/declutter")
    assert insp2.status_code == 200
    assert len(insp2.json()["items"]) == 0

    # But included if include_ignored=true
    insp3 = client.get("/api/v1/library/declutter?include_ignored=true")
    assert insp3.status_code == 200
    assert len(insp3.json()["items"]) == 1
    assert insp3.json()["items"][0]["is_ignored"] is True

    # Un-ignore
    client.post("/api/v1/library/declutter/ignore", json={"tmdb_id": 201, "ignored": False})

    # Delete 201 via Radarr
    del_res = client.post(
        "/api/v1/library/declutter/delete",
        json={"tmdb_ids": [201], "delete_files": True},
    )
    assert del_res.status_code == 200
    del_data = del_res.json()
    assert del_data["deleted_count"] == 1
    assert del_data["freed_bytes"] == 14000000000

    # Verify movie is deleted from FakeRadarr
    assert 201 not in fake_radarr.movies
