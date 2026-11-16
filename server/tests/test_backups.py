import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from iwanttowatch import backups
from iwanttowatch.api.auth import hasher
from iwanttowatch.db import utcnow
from iwanttowatch.models import ApiCache, Availability, Recommendation, Title, User, UserTitle


def test_admins_back_up_the_database_and_download_copies(client: TestClient) -> None:
    made = client.post("/api/v1/backups").json()
    assert made["keep"] == 7 and made["every_hours"] == 24
    newest = made["backups"][0]
    assert made["folder"].endswith("backups") and newest["size"] > 0

    download = client.get(f"/api/v1/backups/{newest['name']}")
    assert download.status_code == 200
    copy = Path(made["folder"]) / "downloaded.db"
    copy.write_bytes(download.content)
    with sqlite3.connect(copy) as db:
        assert db.execute("SELECT username FROM users").fetchall() == [("riya",)]
    # Only backup files can be downloaded, not the database or anything outside the folder.
    for name in ("downloaded.db", "..%2Fiwanttowatch.db", "iwanttowatch-20260101-000000.db"):
        assert client.get(f"/api/v1/backups/{name}").status_code == 404

    # A copy holds every user's data, so only admins see or make them.
    with Session(client.app.state.engine) as session:  # type: ignore[attr-defined]
        session.add(User(id=2, username="anu", display_name="Anu", region="IN",
                         password_hash=hasher.hash("password1")))  # fmt: skip
        session.commit()
    client.post("/api/v1/auth/login", json={"username": "anu", "password": "password1"})
    assert client.get("/api/v1/backups").status_code == 403
    assert client.post("/api/v1/backups").status_code == 403
    assert client.get(f"/api/v1/backups/{newest['name']}").status_code == 403


def test_only_the_newest_seven_backups_are_kept(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    start = datetime(2026, 11, 1, tzinfo=UTC)
    times = iter(start + timedelta(hours=n) for n in range(10))
    monkeypatch.setattr(backups, "utcnow", lambda: next(times))
    folder = tmp_path / "elsewhere"
    for _ in range(10):
        backups.back_up(client.app.state.engine, folder)  # type: ignore[attr-defined]
    kept = backups.list_backups(folder)
    assert [b.created_at for b in kept] == [start + timedelta(hours=n) for n in range(9, 2, -1)]
    assert sorted(p.name for p in folder.iterdir()) == sorted(b.name for b in kept)


def test_compaction_settings_and_manual_run(client: TestClient) -> None:
    old = utcnow() - timedelta(days=45)
    recent = utcnow() - timedelta(days=2)
    with Session(client.app.state.engine) as session:  # type: ignore[attr-defined]
        # 9001: old & unreferenced -> should be pruned
        # 9002: old & rated -> must be kept
        # 9003: old & in feed -> must be kept
        # 9004: recent & unreferenced -> must be kept
        for tid, ts in ((9001, old), (9002, old), (9003, old), (9004, recent)):
            session.add(
                Title(
                    tmdb_id=tid,
                    title=f"Film {tid}",
                    original_title=f"Film {tid}",
                    original_language="en",
                    fetched_at=ts,
                )
            )
            session.add(Availability(tmdb_id=tid, region="IN", offers=[], checked_at=ts))
        session.flush()
        session.add(UserTitle(user_id=1, tmdb_id=9002, source="app", rating=8.0))
        session.add(Recommendation(user_id=1, tmdb_id=9003, score=0.9, rank=0, reasons=[]))
        session.add(ApiCache(key="expired-key", body="{}", expires_at=old))
        session.commit()

    # Configure auto-compaction via API
    updated = client.put(
        "/api/v1/settings/compaction", json={"enabled": True, "retention_days": 30}
    )
    assert updated.status_code == 200
    assert updated.json()["db_compact_enabled"] is True
    assert updated.json()["db_compact_days"] == 30
    assert updated.json()["db_size_bytes"] > 0

    # Trigger manual compaction
    res = client.post("/api/v1/settings/compaction/run")
    assert res.status_code == 200
    body = res.json()
    assert body["titles_removed"] == 1
    assert body["availability_removed"] == 1
    assert body["cache_removed"] >= 1
    assert body["size_after"] > 0

    with Session(client.app.state.engine) as session:  # type: ignore[attr-defined]
        assert session.get(Title, 9001) is None
        assert session.get(Title, 9002) is not None
        assert session.get(Title, 9003) is not None
        assert session.get(Title, 9004) is not None
        assert session.get(Availability, (9001, "IN")) is None

    settings = client.get("/api/v1/settings").json()
    assert settings["db_compact_last_at"] is not None
