from pathlib import Path

import respx
from fastapi.testclient import TestClient
from test_imports import KEY

from iwanttowatch.config import Settings
from iwanttowatch.main import create_app


def test_export_restores_into_another_server(
    client: TestClient, tmp_path: Path, mock: respx.MockRouter
) -> None:
    client.put("/api/v1/settings/tmdb", json={"api_key": KEY})
    client.put("/api/v1/me/streaming", json={"region": "US", "subscriptions": [8]})
    assert client.put("/api/v1/me/profile", json={"birth_year": 2999}).status_code == 422
    assert client.put("/api/v1/me/profile", json={"birth_year": 1985}).json()["birth_year"] == 1985
    client.put(
        "/api/v1/titles/201/reaction",
        json={"reaction": "loved", "tags": ["great_story", "too_slow"], "note": "The ending!"},
    )
    client.put("/api/v1/titles/301/feedback", json={"kind": "seen"})
    client.put("/api/v1/titles/401/feedback", json={"kind": "dismissed"})
    client.put("/api/v1/titles/402/shortlist")

    response = client.get("/api/v1/me/export")
    assert "attachment" in response.headers["content-disposition"]
    exported = response.json()
    assert exported["profile"] == {
        "region": "US",
        "languages": [],
        "subscriptions": [8],
        "show_rent_buy": False,
        "show_continue_watching": False,
        "birth_year": 1985,
    }
    by_id = {e["tmdb_id"]: e for e in exported["entries"]}
    assert (
        by_id[201]["reaction"] == "loved"
        and by_id[201]["tags"] == ["great_story", "too_slow"]
        and by_id[201]["note"] == "The ending!"
    )
    assert by_id[301]["watched"] is True and by_id[301]["rating"] is None
    assert [(f["tmdb_id"], f["kind"]) for f in exported["feedback"]] == [(401, "dismissed")]
    assert [s["tmdb_id"] for s in exported["shortlist"]] == [402]

    other = TestClient(create_app(Settings(data_dir=tmp_path / "other", secret_key="t")))
    other.post(
        "/api/v1/setup",
        json={"username": "anu", "display_name": "Anu", "password": "password1", "region": "IN"},
    )
    other.put("/api/v1/settings/tmdb", json={"api_key": KEY})
    assert (
        other.post(
            "/api/v1/me/import", files={"file": ("broken.json", b'{"format": "something"}')}
        ).status_code
        == 400
    )

    restored = other.post("/api/v1/me/import", files={"file": ("me.json", response.content)})
    assert restored.json() == {"entries": 2, "feedback": 1, "skipped": 0}
    me = other.get("/api/v1/me").json()
    assert me["region"] == "US" and me["birth_year"] == 1985
    again = other.get("/api/v1/me/export").json()
    assert again["entries"] == exported["entries"] and again["feedback"] == exported["feedback"]
    assert again["shortlist"] == exported["shortlist"]
