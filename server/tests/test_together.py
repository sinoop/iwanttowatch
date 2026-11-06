from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
import test_imports
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from test_feed import base_details, idle
from test_imports import KEY

from iwanttowatch.config import Settings
from iwanttowatch.main import create_app
from iwanttowatch.models import Guest, User, UserTitle
from iwanttowatch.together import group_score


def picks(client: TestClient, **params: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = client.get(
        "/api/v1/together/picks", params={"available_only": False, **params}
    ).json()["items"]
    return items


def test_group_picks_suit_everyone_and_skip_what_anyone_has_seen(
    client: TestClient, tmp_path: Path, mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Both Drishyams (301, 302) share a director nobody else in the catalogue has.
    def details(tmdb_id: int) -> dict[str, Any]:
        d = base_details(tmdb_id)
        if tmdb_id in (301, 302):
            d["credits"]["crew"] = [{"id": 7, "name": "Jeethu Joseph", "job": "Director"}]
        return d

    monkeypatch.setattr(test_imports, "_details", details)
    client.put("/api/v1/settings/tmdb", json={"api_key": KEY})
    client.put("/api/v1/titles/101/reaction", json={"reaction": "loved"})
    client.get("/api/v1/feed")
    idle(client)
    # Anu, also on this server, didn't like Drishyam (301).
    engine = client.app.state.engine  # type: ignore[attr-defined]
    with Session(engine) as session:
        session.add(User(id=2, username="anu", display_name="Anu", region="IN"))
        session.add(UserTitle(user_id=2, tmdb_id=301, source="app", rating=3.0, watched=True))
        session.commit()

    # Mira, on her own server, has watched Premam (402) and shares her taste.
    friend = TestClient(create_app(Settings(data_dir=tmp_path / "mira", secret_key="t")))
    friend.post(
        "/api/v1/setup",
        json={"username": "mira", "display_name": "M", "password": "password1", "region": "IN"},
    )
    friend.put("/api/v1/settings/tmdb", json={"api_key": KEY})
    friend.put("/api/v1/titles/101/reaction", json={"reaction": "liked"})
    friend.put("/api/v1/titles/402/feedback", json={"kind": "seen"})
    token = friend.post("/api/v1/me/share").json()["token"]
    shared = friend.get(f"/api/v1/shared/{token}").json()
    assert set(shared) == {"format", "version", "labels", "seen"} and 402 in shared["seen"]

    def forward(request: httpx.Request) -> httpx.Response:
        answer = friend.get(request.url.path)
        return httpx.Response(answer.status_code, content=answer.content)

    mock.route(host="mira.example").mock(side_effect=forward)
    link = f"https://mira.example/api/v1/shared/{token}"
    guest = client.post("/api/v1/guests", json={"name": "Mira", "link": link}).json()
    assert (guest["name"], guest["ratings"]) == ("Mira", 1)

    items = picks(client, users=[1, 2], guests=[guest["id"]])
    # Léon is rated, Drishyam was seen by Anu, and Premam (402) by Mira.
    assert [i["tmdb_id"] for i in items][-1] == 302
    assert {i["tmdb_id"] for i in items} == {201, 302, 401}
    by_id = {i["tmdb_id"]: i for i in items}
    assert [m["name"] for m in by_id[302]["matches"]] == ["Sinoop Joy", "Anu", "Mira"]
    # Anu is the one who'd likely dislike it, and that sinks it for the group.
    anu = {i: by_id[i]["matches"][1]["match"] for i in by_id}
    assert anu[302] < min(anu[201], anu[401])
    assert by_id[302]["match"] < min(by_id[201]["match"], by_id[401]["match"])

    # Mira revokes her link; at the next refresh her copy is dropped.
    friend.delete("/api/v1/me/share")
    with Session(engine) as session:
        row = session.get(Guest, guest["id"])
        assert row is not None
        row.fetched_at = datetime.now(UTC) - timedelta(hours=2)
        session.commit()
    items = picks(client, users=[1, 2], guests=[guest["id"]])
    assert [m["name"] for m in items[0]["matches"]] == ["Sinoop Joy", "Anu"]
    assert client.get("/api/v1/together").json()["guests"] == []
    revoked = client.post("/api/v1/guests", json={"name": "Mira", "link": link})
    assert revoked.status_code == 400


def test_one_unhappy_person_outweighs_two_happy_ones() -> None:
    # Two love it and one would hate it, against a film all three would quite like.
    assert group_score([0.95, 0.95, 0.35]) < group_score([0.7, 0.7, 0.7])
    # Above the threshold it's a plain average.
    assert group_score([0.9, 0.7]) == pytest.approx(0.8)
