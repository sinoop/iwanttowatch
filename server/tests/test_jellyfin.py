import json
import uuid
from datetime import date
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_imports import KEY

from iwanttowatch.models import UserTitle

JELLYFIN = "http://jellyfin.test:8096"
API_KEY = "jellyfin-api-key"
RIYA = uuid.UUID("c51a58f2-c944-4467-a684-90d75f6c97b0")
ANU = uuid.UUID("0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0")
PASSWORDS = {"riya": ("jfpass1", RIYA), "anu": ("anupass1", ANU)}


class FakeJellyfin:
    """Jellyfin's API as iWantToWatch uses it, with per-user play state."""

    def __init__(self) -> None:
        self.items: dict[str, dict[str, Any]] = {}
        self.user_data: dict[tuple[uuid.UUID, str], dict[str, Any]] = {}

    def add(self, name: str, year: int, **provider_ids: str) -> str:
        item_id = uuid.uuid4().hex
        self.items[item_id] = {
            "Id": item_id,
            "Name": name,
            "ProductionYear": year,
            "ProviderIds": provider_ids,
        }
        return item_id

    def play(self, user: uuid.UUID, item_id: str, played: bool = True, **extra: Any) -> None:
        data = self.user_data.setdefault((user, item_id), {})
        data.update({"Played": played, "LastPlayedDate": "2026-11-05T20:31:12.1234567Z", **extra})

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path, params = request.url.path, request.url.params
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("MediaBrowser ") or 'Client="iWantToWatch"' not in auth:
            return httpx.Response(400)
        if path == "/Users/AuthenticateByName":
            body = json.loads(request.content)
            if body["Username"] not in PASSWORDS or body["Pw"] != PASSWORDS[body["Username"]][0]:
                return httpx.Response(401)
            account = {"Id": PASSWORDS[body["Username"]][1].hex, "Name": body["Username"]}
            return httpx.Response(200, json={"User": account, "AccessToken": "session-token"})
        if path == "/Sessions/Logout" and 'Token="session-token"' in auth:
            return httpx.Response(204)
        if f'Token="{API_KEY}"' not in auth:
            return httpx.Response(401)
        if path == "/System/Info":
            return httpx.Response(200, json={"ServerName": "Home", "Version": "10.11.0"})
        if path == "/Items":
            viewer = uuid.UUID(params["userId"])
            wanted = params.get("ids", "").split(",") if params.get("ids") else None
            items = [
                {**item, "UserData": {"Played": False, **self.user_data.get((viewer, i), {})}}
                for i, item in self.items.items()
                if wanted is None or i in wanted
            ]
            start, limit = int(params["startIndex"]), int(params["limit"])
            page = items[start : start + limit]
            return httpx.Response(200, json={"Items": page, "TotalRecordCount": len(items)})
        return httpx.Response(404)


@pytest.fixture
def jellyfin(mock: respx.MockRouter) -> FakeJellyfin:
    fake = FakeJellyfin()
    mock.route(host="jellyfin.test").mock(side_effect=fake)
    return fake


def connect(client: TestClient) -> str:
    """Connect TMDb and Jellyfin as the admin; returns the webhook path."""
    assert client.put("/api/v1/settings/tmdb", json={"api_key": KEY}).status_code == 200
    wrong = client.put("/api/v1/settings/jellyfin", json={"url": JELLYFIN, "api_key": "nope"})
    assert wrong.status_code == 400
    settings = client.put("/api/v1/settings/jellyfin", json={"url": JELLYFIN, "api_key": API_KEY})
    assert settings.status_code == 200, settings.text
    path: str = settings.json()["jellyfin"]["webhook_path"]
    return path


def idle(client: TestClient) -> None:
    client.app.state.jellyfin_worker.wait_until_idle()  # type: ignore[attr-defined]


def history(client: TestClient) -> dict[int, tuple[bool, date | None, bool]]:
    """The admin's Jellyfin watch history: tmdb_id → (watched, watched_at, favourite)."""
    with Session(client.app.state.engine) as session:  # type: ignore[attr-defined]
        rows = session.scalars(select(UserTitle).where(UserTitle.source == "jellyfin"))
        return {r.tmdb_id: (r.watched, r.watched_at, r.favorite) for r in rows}


def test_sync_and_webhooks_keep_watch_history_current(
    client: TestClient, jellyfin: FakeJellyfin
) -> None:
    drishyam = jellyfin.add("Drishyam", 2013, Tmdb="301")
    kumbalangi = jellyfin.add("Kumbalangi Nights", 2019, Imdb="tt8413338")
    # No provider IDs and no online metadata: named after its folder.
    premam = jellyfin.add("Premam (2015)", 2015)
    jellyfin.add("Some Lost Film (1990) [1080p]", 1990)
    # Two editions of one film, only one of them played.
    leon_cut = jellyfin.add("Léon", 1994, Tmdb="101")
    jellyfin.add("Léon (Director's Cut)", 1994, Tmdb="101")
    jellyfin.play(RIYA, drishyam)
    jellyfin.play(RIYA, leon_cut)
    jellyfin.play(RIYA, kumbalangi, played=False, IsFavorite=True)
    jellyfin.play(ANU, premam)  # Another person's plays aren't the admin's.

    webhook = connect(client)
    link = client.put("/api/v1/me/jellyfin", json={"username": "riya", "password": "x"})
    assert link.status_code == 400
    link = client.put("/api/v1/me/jellyfin", json={"username": "riya", "password": "jfpass1"})
    assert link.status_code == 200
    idle(client)

    played = date(2026, 11, 5)
    assert history(client) == {301: (True, played, False), 101: (True, played, False),
                               201: (False, None, True)}  # fmt: skip
    account = client.get("/api/v1/me/jellyfin").json()
    assert account == {"server_configured": True, "linked": True, "can_unlink": True,
                       "library_movies": 6, "watched": 2, "favorites": 1}  # fmt: skip
    status = client.get("/api/v1/settings").json()["jellyfin"]
    assert status["unmatched"] == ["Some Lost Film (1990) [1080p]"]
    assert status["synced_at"] is not None and status["error"] is None

    def notify(event: dict[str, Any], token: str | None = None) -> int:
        url = webhook if token is None else webhook.replace(webhook.split("=")[1], token)
        # The Webhook plugin sends its JSON as text/plain.
        body = json.dumps({"ItemType": "Movie", **event})
        code = client.post(url, content=body, headers={"Content-Type": "text/plain"}).status_code
        idle(client)
        return code

    # The Webhook plugin sends GUIDs with dashes ("Send All Properties").
    finished = {"NotificationType": "UserDataSaved", "SaveReason": "PlaybackFinished",
                "UserId": str(RIYA), "ItemId": str(uuid.UUID(premam)).upper()}  # fmt: skip
    jellyfin.play(RIYA, premam)
    assert notify(finished, token="wrong") == 401
    assert 401 not in history(client)
    # Progress saves during playback don't trigger a sync.
    assert notify({**finished, "SaveReason": "PlaybackProgress"}) == 204
    assert 401 not in history(client)
    assert notify(finished) == 204
    assert history(client)[401] == (True, played, False)

    # Marking a film unplayed in Jellyfin removes it from the history.
    jellyfin.play(RIYA, drishyam, played=False)
    assert notify({**finished, "ItemId": drishyam}) == 204
    assert 301 not in history(client)

    # Deleting a file drops it from the library, but the user still saw the film.
    del jellyfin.items[kumbalangi]
    assert notify({"NotificationType": "ItemDeleted", "ItemId": kumbalangi}) == 204
    assert client.get("/api/v1/me/jellyfin").json()["library_movies"] == 5
    assert history(client)[201] == (False, None, True)
    assert client.get("/api/v1/settings").json()["jellyfin"]["webhook_at"] is not None

    # Unlinking forgets everything synced from Jellyfin.
    assert client.delete("/api/v1/me/jellyfin").json()["library_movies"] == 0
    assert history(client) == {}


def test_jellyfin_users_sign_in_without_taking_over_local_accounts(
    client: TestClient, jellyfin: FakeJellyfin
) -> None:
    connect(client)
    client.post("/api/v1/auth/logout")
    assert client.get("/api/v1/setup").json()["jellyfin_login"] is True

    wrong = {"username": "anu", "password": "wrong"}
    assert client.post("/api/v1/auth/login", json=wrong).status_code == 401
    anu = client.post("/api/v1/auth/login", json={"username": "anu", "password": "anupass1"})
    assert anu.status_code == 200
    assert anu.json()["display_name"] == "anu" and anu.json()["is_admin"] is False
    assert anu.json()["region"] == "IN"
    assert client.get("/api/v1/me/jellyfin").json()["can_unlink"] is False
    assert client.delete("/api/v1/me/jellyfin").status_code == 400
    again = client.post("/api/v1/auth/login", json={"username": "anu", "password": "anupass1"})
    assert again.json()["id"] == anu.json()["id"]

    # A Jellyfin user named like the local admin gets their own account, not the admin's.
    jf_riya = client.post(
        "/api/v1/auth/login", json={"username": "riya", "password": "jfpass1"}
    ).json()
    assert jf_riya["username"] == "riya (Jellyfin)" and jf_riya["is_admin"] is False

    # The admin's local password still signs in to the admin account.
    admin = client.post("/api/v1/auth/login", json={"username": "riya", "password": "password1"})
    assert admin.json()["is_admin"] is True
    taken = client.put("/api/v1/me/jellyfin", json={"username": "riya", "password": "jfpass1"})
    assert taken.status_code == 409
    idle(client)


def test_in_progress_playback_and_rating_prompts(
    client: TestClient, jellyfin: FakeJellyfin
) -> None:
    drishyam = jellyfin.add("Drishyam", 2013, Tmdb="301")
    kumbalangi = jellyfin.add("Kumbalangi Nights", 2019, Imdb="tt8413338")

    # Start Drishyam with 42% progress
    jellyfin.play(
        RIYA,
        drishyam,
        played=False,
        PlaybackPositionTicks=18000000000,
        PlayedPercentage=42.0,
    )

    webhook = connect(client)
    link = client.put("/api/v1/me/jellyfin", json={"username": "riya", "password": "jfpass1"})
    assert link.status_code == 200
    idle(client)

    # In progress endpoint should return Drishyam
    in_prog = client.get("/api/v1/me/in-progress").json()
    assert len(in_prog) == 1
    assert in_prog[0]["tmdb_id"] == 301
    assert in_prog[0]["title"] == "Drishyam"
    assert in_prog[0]["playback_percentage"] == 42.0
    assert in_prog[0]["playback_position_ticks"] == 18000000000
    assert in_prog[0]["jellyfin_url"] == f"{JELLYFIN}/web/#/details?id={drishyam}"

    # No rating prompts yet
    assert client.get("/api/v1/me/rating-prompts").json() == []

    # Finish Drishyam in Jellyfin via webhook
    jellyfin.play(RIYA, drishyam, played=True, PlaybackPositionTicks=0, PlayedPercentage=0.0)
    body = json.dumps(
        {
            "ItemType": "Movie",
            "NotificationType": "PlaybackStop",
            "UserId": str(RIYA),
            "ItemId": drishyam,
        }
    )
    res = client.post(webhook, content=body, headers={"Content-Type": "text/plain"})
    assert res.status_code == 204
    idle(client)

    # Drishyam is no longer in progress
    assert client.get("/api/v1/me/in-progress").json() == []

    # Rating prompt is created for Drishyam
    prompts = client.get("/api/v1/me/rating-prompts").json()
    assert len(prompts) == 1
    assert prompts[0]["tmdb_id"] == 301
    assert prompts[0]["title"] == "Drishyam"

    # Start and finish Kumbalangi Nights
    jellyfin.play(RIYA, kumbalangi, played=True)
    body = json.dumps(
        {
            "ItemType": "Movie",
            "NotificationType": "PlaybackStop",
            "UserId": str(RIYA),
            "ItemId": kumbalangi,
        }
    )
    assert (
        client.post(webhook, content=body, headers={"Content-Type": "text/plain"}).status_code
        == 204
    )
    idle(client)

    prompts = client.get("/api/v1/me/rating-prompts").json()
    assert len(prompts) == 2
    prompt_ids = {p["tmdb_id"] for p in prompts}
    assert prompt_ids == {201, 301}

    # Dismiss Kumbalangi Nights prompt
    dismiss = client.post("/api/v1/me/rating-prompts/201/dismiss")
    assert dismiss.status_code == 204
    prompts = client.get("/api/v1/me/rating-prompts").json()
    assert len(prompts) == 1
    assert prompts[0]["tmdb_id"] == 301

    # Rate Drishyam via reaction endpoint -> automatically clears its rating prompt
    rate = client.put(
        "/api/v1/titles/301/reaction",
        json={"reaction": "loved", "tags": [], "watched": True},
    )
    assert rate.status_code == 200
    assert client.get("/api/v1/me/rating-prompts").json() == []
