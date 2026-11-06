"""Shared fixtures: a signed-in admin with TMDb faked (but no TMDb key set yet)."""

from collections.abc import Iterator
from pathlib import Path

import pytest
import respx
from fastapi.testclient import TestClient
from test_imports import fake_tmdb

from iwanttowatch.config import Settings
from iwanttowatch.main import create_app


@pytest.fixture
def mock() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False) as router:
        router.route(host="api.themoviedb.org").mock(side_effect=fake_tmdb)
        yield router


@pytest.fixture
def client(tmp_path: Path, mock: respx.MockRouter) -> TestClient:
    client = TestClient(create_app(Settings(data_dir=tmp_path, secret_key="t", static_dir=None)))
    admin = {
        "username": "sinoop",
        "display_name": "Sinoop Joy",
        "password": "password1",
        "region": "IN",
    }
    client.post("/api/v1/setup", json=admin)
    return client
