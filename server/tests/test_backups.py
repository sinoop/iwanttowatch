import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from iwanttowatch import backups
from iwanttowatch.api.auth import hasher
from iwanttowatch.models import User


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
