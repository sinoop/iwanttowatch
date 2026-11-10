"""Tests for Declutter Assistant: inspection, household protection, whitelisting, and deletion."""

from datetime import date, timedelta

import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_imports import KEY
from test_jellyfin import API_KEY as JELLYFIN_API_KEY
from test_jellyfin import JELLYFIN, FakeJellyfin
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


def test_declutter_unplayable_in_jellyfin(
    client: TestClient, fake_radarr: FakeRadarr, mock: respx.MockRouter
) -> None:
    _setup_radarr(client)

    # Mock Jellyfin
    fake_jf = FakeJellyfin()
    mock.route(host="jellyfin.test").mock(side_effect=fake_jf)

    # Configure Jellyfin in Settings
    client.put(
        "/api/v1/settings/jellyfin",
        json={"url": JELLYFIN, "api_key": JELLYFIN_API_KEY},
    )

    # Movie 301: Present in Radarr and present in Jellyfin (normal, not unplayable)
    fake_radarr.movies[301] = {
        "id": 31,
        "title": "Playable In Jellyfin",
        "tmdbId": 301,
        "year": 2020,
        "hasFile": True,
        "monitored": True,
        "sizeOnDisk": 10000000000,
    }
    # Movie 302: Present in Radarr but 0 bytes on disk (not downloaded / unplayable)
    fake_radarr.movies[302] = {
        "id": 32,
        "title": "Zero Byte Movie",
        "tmdbId": 302,
        "year": 2021,
        "hasFile": False,
        "monitored": True,
        "sizeOnDisk": 0,
    }
    # Movie 303: Present in Radarr with non-zero disk occupied (16 GB), but missing from Jellyfin!
    fake_radarr.movies[303] = {
        "id": 33,
        "title": "Corrupt Unplayable File",
        "tmdbId": 303,
        "year": 2022,
        "hasFile": True,
        "monitored": True,
        "sizeOnDisk": 16000000000,  # ~16 GB
    }

    app = client.app
    engine = app.state.engine  # type: ignore[attr-defined]
    with Session(engine) as session:
        admin_user = session.scalars(select(User).where(User.username == "riya")).one()
        member_user = User(
            username="anoop2",
            display_name="Anoop Joy",
            password_hash="test",
            region="IN",
            languages=["en"],
        )
        session.add(member_user)
        session.flush()
        member_user_id = member_user.id

        session.merge(
            Title(
                tmdb_id=303,
                title="Corrupt Unplayable File",
                original_title="Corrupt Unplayable File",
                original_language="en",
                year=2022,
                runtime=110,
            )
        )

        # Add 301 to Jellyfin library
        session.merge(
            LibraryItem(
                user_id=admin_user.id,
                item_id="jf-301",
                tmdb_id=301,
                name="Playable In Jellyfin",
                played=False,
            )
        )
        session.commit()

    # Call inspection endpoint
    res = client.get("/api/v1/library/declutter")
    assert res.status_code == 200
    data = res.json()
    assert data["radarr_configured"] is True
    assert data["jellyfin_configured"] is True

    # 303 must be detected as unplayable candidate!
    items = data["items"]
    by_tmdb = {item["tmdb_id"]: item for item in items}
    assert 303 in by_tmdb
    assert by_tmdb[303]["category"] == "unplayable"
    assert by_tmdb[303]["title"] == "Corrupt Unplayable File"
    assert by_tmdb[303]["size_bytes"] == 16000000000
    assert by_tmdb[303]["size_formatted"] == "14.9 GB"
    assert any("not found in Jellyfin" in r for r in by_tmdb[303]["reasons"])
    assert by_tmdb[303]["is_protected"] is False

    # 301 is playable in Jellyfin, and not disliked/abandoned/etc., so not a declutter candidate
    assert 301 not in by_tmdb
    # 302 has 0 bytes on disk, so not an unplayable candidate
    assert 302 not in by_tmdb

    # Summary check
    assert data["categories_summary"]["unplayable"]["count"] == 1
    assert data["categories_summary"]["unplayable"]["bytes"] == 16000000000
    assert data["categories_summary"]["unplayable"]["formatted"] == "14.9 GB"

    # Filter to unplayable category
    unplayable_res = client.get("/api/v1/library/declutter?category=unplayable")
    assert unplayable_res.status_code == 200
    unplayable_data = unplayable_res.json()
    assert len(unplayable_data["items"]) == 1
    assert unplayable_data["items"][0]["tmdb_id"] == 303

    # Household protection on unplayable movie
    with Session(engine) as session:
        session.merge(ShortlistItem(user_id=member_user_id, tmdb_id=303))
        session.commit()

    prot_res = client.get("/api/v1/library/declutter?category=unplayable")
    assert prot_res.status_code == 200
    prot_item = prot_res.json()["items"][0]
    assert prot_item["is_protected"] is True
    assert any("Shortlisted by Anoop Joy" in pr for pr in prot_item["protection_reasons"])

    # Delete 303 from Radarr and disk
    del_res = client.post(
        "/api/v1/library/declutter/delete",
        json={"tmdb_ids": [303], "delete_files": True},
    )
    assert del_res.status_code == 200
    del_data = del_res.json()
    assert del_data["deleted_count"] == 1
    assert del_data["freed_bytes"] == 16000000000
    assert 303 not in fake_radarr.movies
