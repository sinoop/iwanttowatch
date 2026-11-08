import gzip
import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx
import test_imports
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.orm import Session
from test_imports import KEY
from test_persona import FILMS, GEMINI, add_ratings, gemini_reply

from iwanttowatch import feed as feed_module
from iwanttowatch import imdb
from iwanttowatch.feed import ASK_SYSTEM
from iwanttowatch.models import Feedback, LibraryItem, Recommendation, Title, User, UserTitle
from iwanttowatch.moods import MOODS_SYSTEM
from iwanttowatch.taste import REVIEW_SYSTEM

base_details = test_imports._details


def feed(client: TestClient, **params: Any) -> dict[str, Any]:
    page: dict[str, Any] = client.get("/api/v1/feed", params=params).json()
    return page


def idle(client: TestClient) -> None:
    client.app.state.feed_worker.wait_until_idle()  # type: ignore[attr-defined]


def test_feed_suggests_unseen_films_the_user_can_play(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Malayalam Premam (401) streams free with ads on MX Player.
    monkeypatch.setitem(test_imports.WATCH, 401, {"IN": {"ads": [test_imports.MX]}})
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
    # doesn't have, or to rent; free services don't count unless picked (401), and the
    # Telugu Premam (402) streams nowhere.
    assert {i["tmdb_id"] for i in page["items"]} == {201, 302}
    by_id = {i["tmdb_id"]: i for i in page["items"]}
    assert [o["name"] for o in by_id[201]["availability"]["offers"]] == ["Netflix"]
    assert by_id[302]["availability"]["on_jellyfin"] is True
    assert all(1 <= i["match"] <= 99 for i in page["items"])
    assert {lang["language"] for lang in page["languages"]} == {"ml", "en"}

    everything = feed(client, available_only=False)
    assert {i["tmdb_id"] for i in everything["items"]} == {201, 301, 302, 401, 402}
    assert [i["tmdb_id"] for i in feed(client, language="ml")["items"]] == [201]

    # Platform chips list where the feed's films can be played, Jellyfin first, counted
    # before filtering so the chips don't disappear once one is picked.
    assert [(p["key"], p["name"], p["count"]) for p in page["platforms"]] == [
        ("jellyfin", "Jellyfin", 1), ("8", "Netflix", 1), ("515", "MX Player", 1),
    ]  # fmt: skip
    assert [p["free"] for p in page["platforms"]] == [False, False, True]
    assert [i["tmdb_id"] for i in feed(client, platforms=["515"])["items"]] == [401]
    on_server = feed(client, platforms=["jellyfin"])
    assert [i["tmdb_id"] for i in on_server["items"]] == [302]
    assert on_server["platforms"] == page["platforms"]
    assert [i["tmdb_id"] for i in feed(client, platforms=["8"])["items"]] == [201]
    either = feed(client, platforms=["jellyfin", "8"], available_only=False)
    assert {i["tmdb_id"] for i in either["items"]} == {201, 302}

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


def test_the_ai_reviews_the_feed_and_its_ratings_join_the_match(
    client: TestClient, mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The recommender doesn't find the Telugu Premam (402); only the AI can add it.
    found = feed_module.candidates
    monkeypatch.setattr(feed_module, "candidates", lambda *a: [i for i in found(*a) if i != 402])
    client.put("/api/v1/settings/tmdb", json={"api_key": KEY})
    add_ratings(client, FILMS)
    client.put("/api/v1/titles/201/reaction", json={"reaction": "loved", "tags": ["great_story"]})
    prompts: list[str] = []

    def gemini(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if "predict the rating" not in body["systemInstruction"]["parts"][0]["text"]:
            return gemini_reply("OK")
        prompt = body["contents"][0]["parts"][0]["text"]
        prompts.append(prompt)
        listed = re.findall(r"^(\d+)\. (.+?)(?: / .+?)? \(", prompt, re.MULTILINE)
        ratings = [
            {"n": int(n), "rating": 2 if title == "Premam" else 6, "why": f"About {title}."}
            for n, title in listed
        ]
        new = [
            {"title": "Premam", "year": 2016, "rating": 9.5, "why": "A gentle Telugu remake."},
            {"title": "Kumbalangi Nights", "year": 2019, "rating": 9, "why": "Already seen."},
            {"title": "No Such Film", "year": 1900, "rating": 9, "why": "Invented."},
        ]
        answer = {"ratings": ratings, "new": new}
        return gemini_reply("```json\n" + json.dumps(answer) + "\n```")

    mock.post(GEMINI).mock(side_effect=gemini)
    client.put("/api/v1/settings/llm", json={"provider": "gemini", "gemini_api_key": "k" * 30})
    client.put("/api/v1/me/streaming", json={"region": "IN", "subscriptions": [8]})
    idle(client)

    # The AI sees the recommender's films, unseen ones only, without the recommender's
    # match, plus what the user said about films and nothing about who they are.
    assert len(prompts) == 1
    listed = re.findall(r"^\d+\. (.+?)(?: / .+?)? \((\d{4})", prompts[0], re.MULTILINE)
    assert sorted(listed) == [
        ("Drishyam", "2013"), ("Drishyam", "2013"), ("Léon: The Professional", "1994"),
        ("Premam", "2015"),
    ]  # fmt: skip
    assert "%" not in prompts[0].split("Films to rate:")[1].split("Already seen:")[0]
    assert "great story" in prompts[0] and "Kumbalangi Nights (2019)" in prompts[0]
    assert "riya" not in prompts[0].lower()

    by_id = {i["tmdb_id"]: i for i in feed(client, available_only=False)["items"]}
    # Its addition joins with its reason, a seen film doesn't, and an invented one can't.
    assert by_id[402]["reasons"][0] == "AI pick, expects 9.5/10: A gentle Telugu remake."
    assert 201 not in by_id
    # Its predictions count for half of each match, so the Malayalam Premam it expects
    # the user to rate 2/10 falls below the Telugu one it expects 9.5 for.
    assert by_id[401]["reasons"][0] == "AI, expects 2/10: About Premam."
    assert by_id[402]["match"] > by_id[401]["match"]
    assert by_id[401]["match"] <= 50 <= by_id[402]["match"]

    # Feedback rescores the feed without asking the AI again, keeping its view.
    client.put("/api/v1/titles/302/feedback", json={"kind": "up"})
    idle(client)
    assert len(prompts) == 1
    again = {i["tmdb_id"]: i for i in feed(client, available_only=False)["items"]}
    assert again[402]["reasons"][0] == by_id[402]["reasons"][0]
    assert again[401]["match"] < again[402]["match"]


# About 250 characters: two fit in what the app keeps of a "Why this?" answer, three don't.
LONG_SENTENCE = (
    "You rate gentle, character-driven Malayalam dramas very highly, and this one shares "
    "their warmth, small-town setting, and patient storytelling, though its long middle "
    "stretch and romantic focus may test you."
)


def test_the_ai_tags_moods_explains_and_answers_requests(
    client: TestClient, mock: respx.MockRouter
) -> None:
    client.put("/api/v1/settings/tmdb", json={"api_key": KEY})
    add_ratings(client, FILMS)
    assert client.post("/api/v1/titles/301/why").status_code == 409
    assert client.post("/api/v1/feed/ask", json={"text": "Malayalam"}).status_code == 409
    prompts: dict[str, list[str]] = {"review": [], "moods": [], "why": [], "ask": []}
    json_mode: dict[str, bool] = {}

    def gemini(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        system = body["systemInstruction"]["parts"][0]["text"]
        prompt = body["contents"][0]["parts"][0]["text"]
        listed = re.findall(r"^(\d+)\. (.+?)(?: / .+?)? \(", prompt, re.MULTILINE)
        config = body.get("generationConfig", {})
        json_mode[system[:20]] = config.get("responseMimeType") == "application/json"
        if "predict the rating" in system:
            prompts["review"].append(system)
            # Only Léon gets moods here: one in another case, one not in the vocabulary.
            ratings = [
                {"n": int(n), "rating": 6, "why": "Fine."}
                | ({"moods": ["dark", "Gloomy"]} if title.startswith("Léon") else {})
                for n, title in listed
            ]
            return gemini_reply(json.dumps({"ratings": ratings, "new": []}))
        if "tag films with moods" in system:
            prompts["moods"].append(prompt)
            tags = [{"n": int(n), "moods": ["Heartfelt"]} for n, _ in listed]
            return gemini_reply(json.dumps({"moods": tags}))
        if "well a film fits their taste" in system:
            prompts["why"].append(prompt)
            if "Premam" in prompt:  # a rambling answer, longer than the app keeps
                return gemini_reply(" ".join([LONG_SENTENCE] * 3))
            return gemini_reply('"You love quiet family dramas, and this is one, if darker."')
        if "choose a film for a request" in system:
            prompts["ask"].append(prompt)
            # Picks the Malayalam films, plus a number not in the list and a repeat.
            lines = re.findall(r"^(\d+)\. .+ \(\d{4}; ml[;)]", prompt, re.MULTILINE)
            picks = [{"n": int(n), "why": f" Malayalam, number {n}. "} for n in lines]
            return gemini_reply(json.dumps({"picks": [{"n": 99, "why": "?"}, *picks, picks[0]]}))
        return gemini_reply("OK")

    mock.post(GEMINI).mock(side_effect=gemini)
    client.put("/api/v1/settings/llm", json={"provider": "gemini", "gemini_api_key": "k" * 30})
    client.put("/api/v1/me/streaming", json={"region": "IN", "subscriptions": [8]})
    idle(client)

    assert "Mind-bending" in prompts["review"][0]
    # The review's moods replace the keyword ones; the films it left untagged go to one
    # mood call that describes films only.
    by_id = {i["tmdb_id"]: i for i in feed(client, available_only=False)["items"]}
    assert by_id[101]["moods"] == ["Dark"]
    assert len(prompts["moods"]) == 1
    tagged = re.findall(r"^\d+\. (.+?) \(", prompts["moods"][0], re.MULTILINE)
    assert "Léon: The Professional" not in tagged and "Drishyam" in tagged
    assert "Godfather" not in prompts["moods"][0] and "riya" not in prompts["moods"][0]
    assert all(by_id[i]["moods"] == ["Heartfelt"] for i in (301, 302, 401))

    # Moods are kept per film, so the next build doesn't ask again.
    client.post("/api/v1/feed/refresh")
    idle(client)
    assert len(prompts["review"]) == 2 and len(prompts["moods"]) == 1

    detail = client.post("/api/v1/titles/301/why").json()
    explanation = "You love quiet family dramas, and this is one, if darker."
    assert detail["explanation"] == explanation
    assert "Godfather" in prompts["why"][0] and "Drishyam" in prompts["why"][0]
    assert "riya" not in prompts["why"][0].lower()
    # Asked once per user and film.
    assert client.get("/api/v1/titles/301").json()["explanation"] == explanation
    client.post("/api/v1/titles/301/why")
    assert len(prompts["why"]) == 1
    # A long answer keeps its whole sentences, never a cut-off one.
    long = client.post("/api/v1/titles/401/why").json()["explanation"]
    assert long == f"{LONG_SENTENCE} {LONG_SENTENCE}"

    # A request picks from the filtered feed, sending film details but no taste data.
    everything = feed(client, available_only=False)["items"]
    answer = client.post(
        "/api/v1/feed/ask", params={"available_only": False}, json={"text": "Light Malayalam"}
    ).json()
    assert answer["considered"] == len(everything)
    malayalam = [i["tmdb_id"] for i in everything if i["original_language"] == "ml"]
    assert sorted(p["tmdb_id"] for p in answer["picks"]) == sorted(malayalam)
    assert all(re.fullmatch(r"Malayalam, number \d+\.", p["why"]) for p in answer["picks"])
    asked = prompts["ask"][0]
    assert asked.startswith("Request: Light Malayalam\n") and "Kumbalangi Nights" in asked
    assert "Godfather" not in asked and "riya" not in asked.lower()
    # The default filter leaves out films the user can't play, so the AI never sees them.
    playable = client.post("/api/v1/feed/ask", json={"text": "Malayalam"}).json()
    assert playable["considered"] == len(feed(client)["items"]) < len(everything)
    # The feed shows just the picks, in its own order.
    shown = feed(client, available_only=False, only=malayalam[::-1])["items"]
    assert [i["tmdb_id"] for i in shown] == malayalam
    assert client.post("/api/v1/feed/ask", json={"text": "  "}).status_code == 422

    # Gemini is held to well-formed JSON where the app parses the reply, and only there.
    on = {key for key, on in json_mode.items() if on}
    assert on == {REVIEW_SYSTEM[:20], MOODS_SYSTEM[:20], ASK_SYSTEM[:20]}
    assert len(json_mode) == 5  # with the Settings test and "Why this?"


def test_discover_reads_on_past_films_the_user_has_seen(client: TestClient) -> None:
    # TMDb lists 25 pages of Malayalam films, best first; the user has seen the top 50.
    with Session(client.app.state.engine) as session:  # type: ignore[attr-defined]
        for i in range(1, 51):
            session.add(
                Title(tmdb_id=i, title=f"F{i}", original_title=f"F{i}", original_language="ml")
            )
            session.add(UserTitle(user_id=1, tmdb_id=i, source="imdb", watched=True))
        user = session.get(User, 1)
        assert user is not None
        user.languages, user.subscriptions = ["ml"], []
        session.commit()
        pages: list[int] = []

        class Tmdb:
            def get(self, path: str, params: dict[str, Any], cache: timedelta) -> dict[str, Any]:
                assert path == "/discover/movie" and params["with_original_language"] == "ml"
                pages.append(page := params["page"])
                return {"results": [{"id": i} for i in range(20 * page - 19, 20 * page + 1)],
                        "total_pages": 25}  # fmt: skip

        found = feed_module.candidates(session, Tmdb(), user, [])  # type: ignore[arg-type]
    # It reads on until it has 40 unseen films, rather than stopping at seen ones.
    assert pages == [1, 2, 3, 4, 5]
    assert found == list(range(51, 101))


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


def test_the_shortlist_keeps_films_with_their_match_until_they_are_watched(
    client: TestClient,
) -> None:
    client.put("/api/v1/settings/tmdb", json={"api_key": KEY})
    client.put("/api/v1/titles/101/reaction", json={"reaction": "loved"})
    feed(client)
    idle(client)
    assert feed(client)["shortlist_count"] == 0

    assert client.put("/api/v1/titles/401/shortlist").status_code == 204
    assert client.put("/api/v1/titles/401/shortlist").status_code == 204  # idempotent
    everything = {i["tmdb_id"]: i for i in feed(client, available_only=False)["items"]}
    assert everything[401]["shortlisted"] and not everything[201]["shortlisted"]
    saved = feed(client, shortlist=True, available_only=False)
    assert [i["tmdb_id"] for i in saved["items"]] == [401] and saved["shortlist_count"] == 1
    assert saved["items"][0]["match"] == everything[401]["match"]
    # Platform chips count the shortlist only.
    assert sum(p["count"] for p in saved["platforms"]) <= 1
    # Saving a film overrides having turned it down.
    client.put("/api/v1/titles/401/feedback", json={"kind": "dismissed"})
    assert [i["tmdb_id"] for i in feed(client, shortlist=True, available_only=False)["items"]] == [
        401
    ]

    # A film that has left the feed comes back as a candidate once saved.
    with Session(client.app.state.engine) as session:  # type: ignore[attr-defined]
        session.execute(delete(Recommendation).where(Recommendation.tmdb_id == 402))
        session.commit()
    assert client.get("/api/v1/titles/402").json()["shortlisted"] is False
    client.put("/api/v1/titles/402/shortlist")
    assert client.get("/api/v1/titles/402").json()["shortlisted"] is True
    idle(client)
    saved = feed(client, shortlist=True, available_only=False)
    assert {i["tmdb_id"] for i in saved["items"]} == {401, 402}

    # Watching a film takes it off; so does removing it.
    client.put("/api/v1/titles/401/reaction", json={"reaction": "liked"})
    assert client.delete("/api/v1/titles/402/shortlist").status_code == 204
    saved = feed(client, shortlist=True, available_only=False)
    assert saved["items"] == [] and saved["shortlist_count"] == 0
