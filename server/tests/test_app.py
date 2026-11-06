from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient

from iwanttowatch.config import Settings
from iwanttowatch.db import Base
from iwanttowatch.main import create_app

ADMIN = {
    "username": "sinoop",
    "display_name": "Sinoop",
    "password": "correct horse",
    "region": "IN",
    "languages": ["ml", "en"],
}


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(Settings(data_dir=tmp_path, secret_key="test", static_dir=None)))


def test_first_run_setup_creates_admin_once_and_sessions_work(client: TestClient) -> None:
    assert client.get("/api/v1/setup").json() == {"complete": False}
    assert client.get("/api/v1/me").status_code == 401

    created = client.post("/api/v1/setup", json=ADMIN)
    assert created.status_code == 201
    assert created.json()["is_admin"] is True
    assert client.get("/api/v1/me").json()["languages"] == ["ml", "en"]
    assert client.get("/api/v1/setup").json() == {"complete": True}

    # A second visitor cannot claim the server once an admin exists.
    assert client.post("/api/v1/setup", json={**ADMIN, "username": "intruder"}).status_code == 409

    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.get("/api/v1/me").status_code == 401

    wrong = {"username": "sinoop", "password": "wrong password"}
    assert client.post("/api/v1/auth/login", json=wrong).status_code == 401
    unknown = {"username": "nobody", "password": "correct horse"}
    assert client.post("/api/v1/auth/login", json=unknown).status_code == 401

    right = {"username": "sinoop", "password": "correct horse"}
    assert client.post("/api/v1/auth/login", json=right).status_code == 200
    assert client.get("/api/v1/me").json()["username"] == "sinoop"


def test_web_app_fallback_does_not_swallow_api_routes(tmp_path: Path) -> None:
    static = tmp_path / "web"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<div id=root></div>")
    (static / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("outside the web root")
    settings = Settings(data_dir=tmp_path / "data", secret_key="test", static_dir=static)
    client = TestClient(create_app(settings))

    assert client.get("/assets/app.js").text == "console.log(1)"
    assert client.get("/discover/123").text == "<div id=root></div>"
    assert client.get("/%2E%2E/secret.txt").text == "<div id=root></div>"
    assert client.get("/api/v1/does-not-exist").status_code == 404
    assert client.get("/api/v1/setup").json() == {"complete": False}


def test_migrations_match_models(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path, secret_key="test", static_dir=None))
    with app.state.engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
