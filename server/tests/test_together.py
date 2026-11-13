from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
import test_imports
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session
from test_feed import base_details, idle
from test_imports import KEY

from iwanttowatch.api import vote as vote_api
from iwanttowatch.config import Settings
from iwanttowatch.main import create_app
from iwanttowatch.models import (
    Feedback,
    Guest,
    LibraryItem,
    Recommendation,
    User,
    UserTitle,
    Voter,
    VoteSession,
)
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
    assert [m["name"] for m in by_id[302]["matches"]] == ["Riya Menon", "Anu", "Mira"]
    # Anu is the one who'd likely dislike it, and that sinks it for the group.
    anu = {i: by_id[i]["matches"][1]["match"] for i in by_id}
    assert anu[302] < min(anu[201], anu[401])
    assert by_id[302]["match"] <= min(by_id[201]["match"], by_id[401]["match"])

    # With the Jellyfin chip, only films on the host's server: Drishyam (302).
    with Session(engine) as session:
        session.add(LibraryItem(user_id=1, item_id="c" * 32, tmdb_id=302, name="D", year=2013))
        session.commit()
    page = client.get(
        "/api/v1/together/picks",
        params={"users": [1, 2], "guests": [guest["id"]], "platforms": ["jellyfin"]},
    ).json()
    assert [i["tmdb_id"] for i in page["items"]] == [302]
    assert [(p["key"], p["count"]) for p in page["platforms"]] == [("jellyfin", 1)]
    unavailable_page = client.get(
        "/api/v1/together/picks",
        params={"users": [1, 2], "guests": [guest["id"]], "unavailable_only": True},
    ).json()
    assert 302 not in [i["tmdb_id"] for i in unavailable_page["items"]]

    # Mira revokes her link; at the next refresh her copy is dropped.
    friend.delete("/api/v1/me/share")
    with Session(engine) as session:
        row = session.get(Guest, guest["id"])
        assert row is not None
        row.fetched_at = datetime.now(UTC) - timedelta(hours=2)
        session.commit()
    items = picks(client, users=[1, 2], guests=[guest["id"]])
    assert [m["name"] for m in items[0]["matches"]] == ["Riya Menon", "Anu"]
    assert client.get("/api/v1/together").json()["guests"] == []
    revoked = client.post("/api/v1/guests", json={"name": "Mira", "link": link})
    assert revoked.status_code == 400

    # Mira sends a taste card file instead: the same data, with nothing to fetch.
    card = friend.get("/api/v1/me/taste-card")
    assert "attachment" in card.headers["content-disposition"]
    assert set(card.json()) == {"format", "version", "labels", "seen"}
    bad = client.post(
        "/api/v1/guests/card", data={"name": "Mira"}, files={"file": ("x.json", b"[1, 2]")}
    )
    assert bad.status_code == 400
    added = client.post(
        "/api/v1/guests/card", data={"name": "Mira"}, files={"file": ("card.json", card.content)}
    ).json()
    assert (added["from_card"], added["ratings"]) == (True, 1)
    mock.route(host="mira.example").mock(side_effect=AssertionError("cards aren't fetched"))
    with Session(engine) as session:
        row = session.get(Guest, added["id"])
        assert row is not None
        row.fetched_at = datetime.now(UTC) - timedelta(days=30)
        session.commit()
    items = picks(client, users=[1, 2], guests=[added["id"]])
    assert [m["name"] for m in items[0]["matches"]] == ["Riya Menon", "Anu", "Mira"]
    assert {i["tmdb_id"] for i in items} == {201, 302, 401}  # still without Premam


def test_one_unhappy_person_outweighs_two_happy_ones() -> None:
    # Two love it and one would hate it, against a film all three would quite like.
    assert group_score([0.95, 0.95, 0.35]) < group_score([0.7, 0.7, 0.7])
    # Above the threshold it's a plain average.
    assert group_score([0.9, 0.7]) == pytest.approx(0.8)


def test_the_group_shortlist_is_shared_and_shows_who_added_each_film(
    client: TestClient,
) -> None:
    client.put("/api/v1/settings/tmdb", json={"api_key": KEY})
    client.put("/api/v1/titles/101/reaction", json={"reaction": "loved"})
    client.get("/api/v1/feed")
    idle(client)
    engine = client.app.state.engine  # type: ignore[attr-defined]
    with Session(engine) as session:
        # Anu said she isn't interested in Premam (401); nobody's feed has 402 any more.
        session.add(User(id=2, username="anu", display_name="Anu", region="IN"))
        session.flush()
        session.add(Feedback(user_id=2, tmdb_id=401, kind="dismissed"))
        session.execute(delete(Recommendation).where(Recommendation.tmdb_id == 402))
        session.commit()
    both = {"users": [1, 2]}
    page = client.get("/api/v1/together/picks", params={"available_only": False, **both}).json()
    assert {401, 402}.isdisjoint(i["tmdb_id"] for i in page["items"])
    assert page["shortlist_count"] == 0

    for tmdb_id in (401, 402):
        assert client.put(f"/api/v1/together/shortlist/{tmdb_id}").status_code == 204
    saved = client.get(
        "/api/v1/together/picks", params={"available_only": False, "shortlist": True, **both}
    ).json()
    # Saved films come back even if out of every feed or turned down, scored for both.
    assert {i["tmdb_id"] for i in saved["items"]} == {401, 402}
    assert saved["shortlist_count"] == 2
    assert all(i["shortlisted_by"] == "Riya Menon" for i in saved["items"])
    assert all(len(i["matches"]) == 2 for i in saved["items"])
    unsaved = [i for i in picks(client, **both) if i["shortlisted_by"] is None]
    assert unsaved and {i["tmdb_id"] for i in unsaved}.isdisjoint({401, 402})

    # Once anyone watching has seen a film, it drops out for the group.
    with Session(engine) as session:
        session.add(UserTitle(user_id=2, tmdb_id=402, source="app", watched=True))
        session.commit()
    assert [i["tmdb_id"] for i in picks(client, shortlist=True, **both)] == [401]
    assert client.delete("/api/v1/together/shortlist/401").status_code == 204
    assert picks(client, shortlist=True, **both) == []


def test_guests_vote_by_link_without_an_account(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    vote_api._recent.clear()
    client.put("/api/v1/settings/tmdb", json={"api_key": KEY})
    client.put("/api/v1/titles/101/reaction", json={"reaction": "loved"})
    engine = client.app.state.engine  # type: ignore[attr-defined]
    with Session(engine) as session:
        session.add(LibraryItem(user_id=1, item_id="b" * 32, tmdb_id=302, name="D", year=2013))
        session.commit()
    # Kumbalangi Nights (201) is on Netflix; Drishyam (302) is on the host's Jellyfin.
    client.put("/api/v1/me/streaming", json={"region": "IN", "subscriptions": [8]})
    idle(client)
    client.put("/api/v1/together/shortlist/302")
    monkeypatch.setattr(vote_api, "BALLOT_SIZE", 1)

    started = client.post("/api/v1/together/vote", json={"users": [1]})
    assert started.status_code == 201, started.text
    token = started.json()["token"]
    # Only films the host can play, the group shortlist first.
    assert [f["tmdb_id"] for f in started.json()["films"]] == [302]

    guest = TestClient(client.app)  # no session cookie
    assert guest.get("/api/v1/together/vote").status_code == 401
    ballot = guest.get(f"/api/v1/vote/{token}")
    assert [f["tmdb_id"] for f in ballot.json()["films"]] == [302]
    # Guests see where films stream, never anyone's matches or ratings.
    assert "match" not in ballot.text and "Riya" not in ballot.text
    assert guest.put(f"/api/v1/vote/{token}/votes/201", json={"choice": "yes"}).status_code == 401

    def join(name: str) -> dict[str, str]:
        joined = guest.post(f"/api/v1/vote/{token}/join", json={"name": name})
        return {"X-Voter": joined.json()["voter_token"]}

    anu, ravi = join("Anu"), join("  Ravi  ")
    # A guest finds Kumbalangi Nights and adds it. Drishyam (301) streams only on a
    # service the host doesn't have, so it isn't offered and can't be added.
    found = guest.get(f"/api/v1/vote/{token}/search", params={"query": "kumbalangi"}).json()
    assert [(f["tmdb_id"], f["on_ballot"]) for f in found] == [(201, False)]
    assert guest.post(f"/api/v1/vote/{token}/films/201").status_code == 401
    assert guest.post(f"/api/v1/vote/{token}/films/201", headers=anu).status_code == 204
    found = guest.get(f"/api/v1/vote/{token}/search", params={"query": "drishyam"}).json()
    assert [(f["tmdb_id"], f["on_ballot"]) for f in found] == [(302, True)]
    assert guest.post(f"/api/v1/vote/{token}/films/301", headers=anu).status_code == 404
    for who, tmdb_id, choice in [(anu, 201, "yes"), (anu, 302, "seen"), (ravi, 201, "no")]:
        cast = guest.put(
            f"/api/v1/vote/{token}/votes/{tmdb_id}", json={"choice": choice}, headers=who
        )
        assert cast.status_code == 204
    assert (
        guest.put(
            f"/api/v1/vote/{token}/votes/401", json={"choice": "yes"}, headers=anu
        ).status_code
        == 404
    )
    assert guest.get(f"/api/v1/vote/{token}", headers=anu).json()["votes"] == {
        "201": "yes",
        "302": "seen",
    }

    tally = client.get("/api/v1/together/vote").json()
    assert tally["voters"] == ["Anu", "Ravi"]
    first, last = tally["films"]
    # Kumbalangi: a yes, a no, and the household's match counted as one more voter.
    assert first["tmdb_id"] == 201 and first["added"] and first["tally"] == {
        "yes": ["Anu"], "maybe": [], "no": ["Ravi"], "seen": [],
    }  # fmt: skip
    assert first["score"] == round((1 + 0 + first["match"] / 100) / 3 * 100)
    # A guest has seen Drishyam, so it drops to the end without a score.
    assert last["tmdb_id"] == 302 and last["score"] is None and last["tally"]["seen"] == ["Anu"]

    # Closing the vote ends the link and deletes guests' names and votes.
    assert client.delete("/api/v1/together/vote").status_code == 204
    assert guest.get(f"/api/v1/vote/{token}").status_code == 404
    with Session(engine) as session:
        assert session.scalars(select(Voter)).all() == []

    # A vote also ends on its own after a day.
    token = client.post("/api/v1/together/vote", json={"users": [1]}).json()["token"]
    with Session(engine) as session:
        session.execute(
            update(VoteSession).values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
        )
        session.commit()
    assert guest.get(f"/api/v1/vote/{token}").status_code == 404
    assert client.get("/api/v1/together/vote").json() is None

    # The guest pages are rate-limited per address.
    monkeypatch.setattr(vote_api, "GUEST_REQUESTS_PER_MINUTE", 2)
    vote_api._recent.clear()
    codes = [guest.get(f"/api/v1/vote/{token}").status_code for _ in range(3)]
    assert codes == [404, 404, 429]
