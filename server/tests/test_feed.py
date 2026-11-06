import gzip
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx
import test_imports
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from test_imports import KEY
from test_persona import FILMS, GEMINI, add_ratings, gemini_reply

from iwanttowatch import imdb
from iwanttowatch.models import Feedback, LibraryItem

base_details = test_imports._details


def feed(client: TestClient, **params: Any) -> dict[str, Any]:
    page: dict[str, Any] = client.get("/api/v1/feed", params=params).json()
    return page


def idle(client: TestClient) -> None:
    client.app.state.feed_worker.wait_until_idle()  # type: ignore[attr-defined]


def test_feed_suggests_unseen_films_the_user_can_play(client: TestClient) -> None:
    assert client.put("/api/v1/settings/tmdb", json={"api_key": KEY}).status_code == 200
    client.put("/api/v1/titles/101/reaction", json={"reaction": "loved"})
    # Drishyam (Hindi remake, 302) is on the user's Jellyfin server.
    with Session(client.app.state.engine) as session:  # type: ignore[attr-defined]
        session.add(LibraryItem(user_id=1, item_id="b" * 32, tmdb_id=302, name="D", year=2013))
        session.commit()
    # Picking services rebuilds the feed: Netflix, which has Kumbalangi Nights (201) in India.
    client.put("/api/v1/me/streaming", json={"region": "IN", "subscriptions": [8]})
    idle(client)

    page = feed(client)
    assert page["status"] == "ready" and page["error"] is None
    # Léon is rated, so it's left out. Drishyam (301) is only on services the user
    # doesn't have, or to rent; the Premams stream nowhere.
    assert {i["tmdb_id"] for i in page["items"]} == {201, 302}
    by_id = {i["tmdb_id"]: i for i in page["items"]}
    assert [o["name"] for o in by_id[201]["availability"]["offers"]] == ["Netflix"]
    assert by_id[302]["availability"]["on_jellyfin"] is True
    assert all(1 <= i["match"] <= 99 for i in page["items"])
    assert {lang["language"] for lang in page["languages"]} == {"ml", "en"}

    everything = feed(client, available_only=False)
    assert {i["tmdb_id"] for i in everything["items"]} == {201, 301, 302, 401, 402}
    assert [i["tmdb_id"] for i in feed(client, language="ml")["items"]] == [201]

    # Rating a suggestion takes it out of the feed at once, without a rebuild.
    client.put("/api/v1/titles/201/reaction", json={"reaction": "liked"})
    assert [i["tmdb_id"] for i in feed(client)["items"]] == [302]

    detail = client.get("/api/v1/titles/302").json()
    assert detail["match"] == by_id[302]["match"]
    assert detail["directors"] == ["A Director"] and detail["jellyfin_url"] is None


def test_imdb_ratings_reach_the_feed_once_an_admin_turns_them_on(
    client: TestClient, mock: respx.MockRouter
) -> None:
    ratings = "tconst\taverageRating\tnumVotes\ntt8413338\t8.5\t22506\ntt0000001\t7.0\t10\n"
    download = mock.get(imdb.RATINGS_URL).respond(content=gzip.compress(ratings.encode()))
    client.put("/api/v1/settings/tmdb", json={"api_key": KEY})
    client.put("/api/v1/me/streaming", json={"region": "IN", "subscriptions": [8]})
    idle(client)
    assert all(i["imdb"] is None for i in feed(client, available_only=False)["items"])
    assert not download.called

    on = client.put("/api/v1/settings/imdb", json={"enabled": True}).json()["imdb"]
    assert on["enabled"] is True
    idle(client)
    by_id = {i["tmdb_id"]: i for i in feed(client, available_only=False)["items"]}
    assert by_id[201]["imdb"] == {"id": "tt8413338", "rating": 8.5, "votes": 22506}
    assert client.get("/api/v1/titles/201").json()["imdb"]["rating"] == 8.5
    status = client.get("/api/v1/settings").json()["imdb"]
    assert status["rated_films"] == 1 and status["updated_at"] and status["error"] is None
    # The next build the same day reuses the downloaded file.
    client.post("/api/v1/feed/refresh")
    idle(client)
    assert download.call_count == 1

    client.put("/api/v1/settings/imdb", json={"enabled": False})
    idle(client)
    assert all(i["imdb"] is None for i in feed(client, available_only=False)["items"])
    assert client.get("/api/v1/settings").json()["imdb"]["rated_films"] == 0


def test_ai_picks_join_the_feed_with_the_ais_reason(
    client: TestClient, mock: respx.MockRouter
) -> None:
    client.put("/api/v1/settings/tmdb", json={"api_key": KEY})
    add_ratings(client, FILMS)
    client.put("/api/v1/titles/201/reaction", json={"reaction": "loved", "tags": ["great_story"]})
    prompts: list[str] = []

    def gemini(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if "recommending films" not in body["systemInstruction"]["parts"][0]["text"]:
            return gemini_reply("OK")
        prompts.append(body["contents"][0]["parts"][0]["text"])
        picks = [
            {"title": "Premam", "year": 2015, "why": "A warm Malayalam romance."},
            {"title": "Kumbalangi Nights", "year": 2019, "why": "Already seen."},
            {"title": "No Such Film", "year": 1900, "why": "Invented."},
        ]
        return gemini_reply("```json\n" + json.dumps(picks) + "\n```")

    mock.post(GEMINI).mock(side_effect=gemini)
    client.put("/api/v1/settings/llm", json={"provider": "gemini", "gemini_api_key": "k" * 30})
    client.put("/api/v1/me/streaming", json={"region": "IN", "subscriptions": [8]})
    idle(client)

    # The prompt carries what the user said about films, and nothing about who they are.
    assert "great story" in prompts[-1] and "Kumbalangi Nights (2019)" in prompts[-1]
    assert "sinoop" not in prompts[-1].lower()
    by_id = {i["tmdb_id"]: i for i in feed(client, available_only=False)["items"]}
    assert by_id[401]["reasons"][0] == "AI pick: A warm Malayalam romance."
    assert 201 not in by_id  # seen, whatever the AI says

    # Feedback rescores the feed without asking the AI again, keeping its reason.
    client.put("/api/v1/titles/401/feedback", json={"kind": "up"})
    idle(client)
    assert len(prompts) == 1
    by_id = {i["tmdb_id"]: i for i in feed(client, available_only=False)["items"]}
    assert by_id[401]["reasons"][0] == "AI pick: A warm Malayalam romance."


def test_feed_waits_for_a_tmdb_key(client: TestClient) -> None:
    # The first visit starts a build.
    assert feed(client)["status"] in {"queued", "building", "failed"}
    idle(client)
    page = feed(client)
    assert page["status"] == "failed" and page["error"] == "Add a TMDb API key in Settings first"


def test_feedback_hides_films_and_reorders_the_feed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
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
    feed(client)
    idle(client)
    before = {i["tmdb_id"]: i["match"] for i in feed(client, available_only=False)["items"]}
    assert set(before) == {201, 301, 302, 401, 402}

    # Less like this: Drishyam leaves the feed, and once the feed is rescored the
    # other film by its director falls below everything else.
    assert client.put("/api/v1/titles/301/feedback", json={"kind": "down"}).status_code == 200
    page = feed(client, available_only=False)
    assert 301 not in {i["tmdb_id"] for i in page["items"]} and page["rescoring"] is True
    idle(client)
    page = feed(client, available_only=False)
    after = {i["tmdb_id"]: i["match"] for i in page["items"]}
    assert page["rescoring"] is False
    assert after[302] < before[302]
    assert after[302] < min(after[i] for i in (201, 401, 402))

    # More like this keeps the film and shows the thumb.
    client.put("/api/v1/titles/201/feedback", json={"kind": "up"})
    assert {i["tmdb_id"]: i["thumbs_up"] for i in feed(client, available_only=False)["items"]}[201]

    # Not interested, not now, and seen it all hide the film.
    client.put("/api/v1/titles/401/feedback", json={"kind": "dismissed"})
    snooze = client.put("/api/v1/titles/402/feedback", json={"kind": "snoozed"}).json()
    assert snooze["until"] is not None
    client.put("/api/v1/titles/302/feedback", json={"kind": "seen"})
    assert [i["tmdb_id"] for i in feed(client, available_only=False)["items"]] == [201]
    # Seen it counts as watched, so it shows on the rating dialog's film as unrated.
    assert client.get("/api/v1/titles/302/reaction").json()["reaction"] is None

    # A snooze ends on its own; undo brings back the rest.
    with Session(client.app.state.engine) as session:  # type: ignore[attr-defined]
        entry = session.get(Feedback, (1, 402))
        assert entry is not None
        entry.until = datetime.now(UTC) - timedelta(minutes=1)
        session.commit()
    for tmdb_id in (401, 302, 301):
        assert client.delete(f"/api/v1/titles/{tmdb_id}/feedback").status_code == 204
    idle(client)
    shown = {i["tmdb_id"] for i in feed(client, available_only=False)["items"]}
    assert shown == {201, 301, 302, 401, 402}
