import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient

from iwanttowatch.config import Settings
from iwanttowatch.db import MIGRATIONS_DIR, Base, create_db_engine
from iwanttowatch.main import create_app

ADMIN = {
    "username": "riya",
    "display_name": "Riya",
    "password": "correct horse",
    "region": "IN",
    "languages": ["ml", "en"],
}


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(Settings(data_dir=tmp_path, secret_key="test", static_dir=None)))


def test_first_run_setup_creates_admin_once_and_sessions_work(client: TestClient) -> None:
    assert client.get("/api/v1/setup").json() == {"complete": False, "jellyfin_login": False}
    assert client.get("/api/v1/me").status_code == 401

    created = client.post("/api/v1/setup", json=ADMIN)
    assert created.status_code == 201
    assert created.json()["is_admin"] is True
    assert client.get("/api/v1/me").json()["languages"] == ["ml", "en"]
    assert client.get("/api/v1/setup").json() == {"complete": True, "jellyfin_login": False}

    # A second visitor cannot claim the server once an admin exists.
    assert client.post("/api/v1/setup", json={**ADMIN, "username": "intruder"}).status_code == 409

    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.get("/api/v1/me").status_code == 401

    wrong = {"username": "riya", "password": "wrong password"}
    assert client.post("/api/v1/auth/login", json=wrong).status_code == 401
    unknown = {"username": "nobody", "password": "correct horse"}
    assert client.post("/api/v1/auth/login", json=unknown).status_code == 401

    right = {"username": "riya", "password": "correct horse"}
    assert client.post("/api/v1/auth/login", json=right).status_code == 200
    assert client.get("/api/v1/me").json()["username"] == "riya"


def test_invite_link_sets_up_one_member_account(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    client.post("/api/v1/setup", json=ADMIN)
    invite = client.post("/api/v1/invites", json={"name": "Asha"}).json()
    guest = TestClient(client.app)
    assert guest.get(f"/api/v1/invites/{invite['token']}").json() == {
        "name": "Asha",
        "invited_by": "Riya",
        "jellyfin_login": False,
    }
    account = {"username": "asha", "display_name": "Asha", "password": "asha-pass"}
    taken = guest.post(
        f"/api/v1/invites/{invite['token']}/accept", json={**account, "username": "riya"}
    )
    assert taken.status_code == 409

    me = guest.post(f"/api/v1/invites/{invite['token']}/accept", json=account).json()
    assert (me["username"], me["is_admin"], me["region"], me["languages"]) == (
        "asha", False, "IN", ["ml", "en"],
    )  # fmt: skip
    assert guest.get("/api/v1/me").json()["id"] == me["id"]
    assert guest.post("/api/v1/auth/login", json=account).status_code == 200
    # One account per link, and only admins invite.
    again = guest.post(f"/api/v1/invites/{invite['token']}/accept", json=account)
    assert again.status_code == 404
    assert client.get("/api/v1/invites").json() == []
    assert guest.post("/api/v1/invites", json={}).status_code == 403

    revoked = client.post("/api/v1/invites", json={}).json()
    assert client.delete(f"/api/v1/invites/{revoked['id']}").status_code == 204
    assert guest.get(f"/api/v1/invites/{revoked['token']}").status_code == 404
    monkeypatch.setattr("iwanttowatch.api.invites.INVITE_LENGTH", timedelta(seconds=-1))
    expired = client.post("/api/v1/invites", json={}).json()
    assert guest.get(f"/api/v1/invites/{expired['token']}").status_code == 404


def test_web_app_is_served_cacheable_without_swallowing_api_routes(tmp_path: Path) -> None:
    static = tmp_path / "web"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<div id=root></div>")
    (static / "assets" / "app.js").write_text("console.log(1);" * 200)
    (tmp_path / "secret.txt").write_text("outside the web root")
    settings = Settings(data_dir=tmp_path / "data", secret_key="test", static_dir=static)
    client = TestClient(create_app(settings))

    script = client.get("/assets/app.js")
    assert script.text == "console.log(1);" * 200
    # Hashed assets are cached for good and sent compressed; the page is always rechecked.
    assert "immutable" in script.headers["cache-control"]
    assert script.headers["content-encoding"] == "gzip"
    page = client.get("/discover/123")
    assert page.text == "<div id=root></div>" and page.headers["cache-control"] == "no-cache"
    assert client.get("/%2E%2E/secret.txt").text == "<div id=root></div>"
    assert client.get("/api/v1/does-not-exist").status_code == 404
    assert client.get("/api/v1/setup").json() == {"complete": False, "jellyfin_login": False}


def test_migrations_match_models(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path, secret_key="test", static_dir=None))
    with app.state.engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []


def test_upgrading_keeps_data_in_tables_that_point_at_rebuilt_ones(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, secret_key="test", static_dir=None)
    engine = create_db_engine(settings.database_url)
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        # The last revision before child profiles, which rebuilds the users table.
        command.upgrade(config, "0aef9577ed45")
        connection.exec_driver_sql(
            "INSERT INTO users (id, username, display_name, is_admin, region, languages,"
            " subscriptions, created_at) VALUES (1, 'riya', 'Riya', 1, 'IN', '[]', '[]',"
            " '2026-11-01')"
        )
        connection.exec_driver_sql(
            "INSERT INTO taste_shares (user_id, token, created_at) VALUES (1, 'x', '2026-11-01')"
        )

    # Starting the app upgrades the database, after copying it as it was.
    app = create_app(settings)
    with app.state.engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT count(*) FROM taste_shares").scalar() == 1
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
    [copy] = (tmp_path / "backups").glob("*-before-upgrade.db")
    with sqlite3.connect(copy) as old:
        assert old.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "0aef9577ed45",
        )
        assert old.execute("SELECT username FROM users").fetchall() == [("riya",)]
    # Starting again, with nothing to upgrade, takes no further copy.
    create_app(settings)
    assert len(list((tmp_path / "backups").glob("*-before-upgrade.db"))) == 1
