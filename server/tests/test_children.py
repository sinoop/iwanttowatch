import json
from datetime import date
from typing import Any

import httpx
import pytest
import respx
import test_imports
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from test_feed import base_details, feed, idle
from test_imports import KEY
from test_persona import GEMINI, gemini_reply
from test_together import picks

from iwanttowatch.models import User

YEAR = date.today().year


def test_child_profile_uses_birth_year_certificate_and_allows_removing_filter_or_rating_any_film(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Give Premam (401, U) family-positive keywords so it outranks Drishyam (301, U)
    # before an adult tags Drishyam as Great with family.
    def details(tmdb_id: int) -> dict[str, Any]:
        d = base_details(tmdb_id)
        if tmdb_id == 401:
            d["keywords"]["keywords"] = [
                {"id": 10, "name": "friendship"},
                {"id": 11, "name": "kindness"},
            ]
        return d

    monkeypatch.setattr(test_imports, "_details", details)
    client.put("/api/v1/settings/tmdb", json={"api_key": KEY})
    # Adult loves Léon (101, certificate A) — an adult rating the child must not see.
    client.put("/api/v1/titles/101/reaction", json={"reaction": "loved", "tags": ["great_story"]})

    # A future birth year is rejected.
    assert (
        client.post("/api/v1/children", json={"name": "Kabir", "birth_year": YEAR + 1}).status_code
        == 422
    )

    # An 8-year-old in India gets U/A 7+.
    child = client.post("/api/v1/children", json={"name": "Kabir", "birth_year": YEAR - 8}).json()
    assert child == {
        "id": 2,
        "name": "Kabir",
        "birth_year": YEAR - 8,
        "max_certificate": "U/A 7+",
    }
    assert client.get("/api/v1/children").json() == [child]
    idle(client)

    # Switching needs no PIN.
    switched = client.post(f"/api/v1/children/{child['id']}/switch").json()
    assert switched["display_name"] == "Kabir"
    assert switched["is_child"] is True and switched["max_certificate"] == "U/A 7+"
    # Child profiles don't see adults' ratings or use adult-only account endpoints.
    assert client.get("/api/v1/ratings").json()["total"] == 0
    assert client.get("/api/v1/me/export").status_code == 403
    assert client.post("/api/v1/me/share").status_code == 403
    assert (
        client.post("/api/v1/children", json={"name": "X", "birth_year": YEAR - 5}).status_code
        == 403
    )

    # Default Discover feed for U/A 7+ in IN: Kumbalangi Nights (201, U/A 7+), Drishyam
    # (301, U), and Premam (401, U). Léon (101, A), Drishyam (302, U/A 13+), and
    # uncertified Premam (402) are filtered out by default.
    items = feed(client, available_only=False)["items"]
    assert {i["tmdb_id"] for i in items} == {201, 301, 401}
    by_id = {i["tmdb_id"]: i for i in items}
    assert by_id[201]["certificate"] == "U/A 7+"
    assert "Themes of friendship and kindness" in by_id[401]["reasons"]
    assert by_id[401]["match"] > by_id[301]["match"]

    # Removing the age filter on Discover shows all scored films, including above U/A 7+.
    unfiltered = feed(client, available_only=False, age_limit=False)["items"]
    assert {i["tmdb_id"] for i in unfiltered} == {101, 201, 301, 302, 401, 402}

    # Child accounts can search, open, and rate/add any film to their library, regardless
    # of its certificate.
    found = client.get("/api/v1/catalog/search", params={"query": "drishyam"}).json()
    assert {c["tmdb_id"] for c in found} == {301, 302}
    assert client.get("/api/v1/titles/101").status_code == 200
    assert client.put("/api/v1/titles/302/feedback", json={"kind": "up"}).status_code == 200
    assert client.delete("/api/v1/titles/302/feedback").status_code == 204

    # Adult switches back without a PIN, tags Drishyam (301, U) as Great with family, and
    # changes the child's birth year to a 5-year-old (U).
    adult = client.post("/api/v1/children/exit").json()
    assert adult["id"] == 1 and adult["is_child"] is False
    client.put(
        "/api/v1/titles/301/reaction",
        json={"reaction": "loved", "tags": ["great_with_family"]},
    )
    updated = client.put(
        f"/api/v1/children/{child['id']}", json={"name": "Kabir", "birth_year": YEAR - 5}
    ).json()
    assert updated["max_certificate"] == "U"
    idle(client)

    client.post(f"/api/v1/children/{child['id']}/switch")
    # Kumbalangi Nights (201, U/A 7+) is now above U and gone from the default feed;
    # Drishyam (301, U) is boosted by the adult's family tag.
    items = feed(client, available_only=False)["items"]
    assert {i["tmdb_id"] for i in items} == {301, 401}
    by_id = {i["tmdb_id"]: i for i in items}
    assert by_id[301]["reasons"][0] == "Tagged Great with family"
    assert client.get("/api/v1/ratings").json()["total"] == 0

    # The child can rate any film (even 101, rated A) and it's stored on the child's profile.
    assert client.put("/api/v1/titles/101/reaction", json={"reaction": "liked"}).status_code == 200
    client.put("/api/v1/titles/401/reaction", json={"reaction": "loved"})
    assert {i["tmdb_id"] for i in client.get("/api/v1/ratings").json()["items"]} == {101, 401}
    assert [i["tmdb_id"] for i in feed(client, available_only=False)["items"]] == [301]
    client.post("/api/v1/children/exit")
    assert {i["tmdb_id"] for i in client.get("/api/v1/ratings").json()["items"]} == {101, 301}


def test_group_picks_apply_the_childs_certificate_to_the_whole_group(
    client: TestClient,
) -> None:
    client.put("/api/v1/settings/tmdb", json={"api_key": KEY})
    client.put("/api/v1/titles/101/reaction", json={"reaction": "loved"})
    feed(client)
    idle(client)
    assert {i["tmdb_id"] for i in picks(client, users=[1])} == {201, 301, 302, 401, 402}

    older = client.post("/api/v1/children", json={"name": "Aarav", "birth_year": YEAR - 9}).json()
    younger = client.post("/api/v1/children", json={"name": "Meera", "birth_year": YEAR - 5}).json()
    idle(client)

    together = client.get("/api/v1/together").json()
    by_name = {p["name"]: p["max_certificate"] for p in together["household"]}
    assert by_name == {"Aarav": "U/A 7+", "Meera": "U", "Riya Menon": None}

    # Adult + Aarav (U/A 7+): 302 (U/A 13+) and uncertified 402 are left out.
    assert {i["tmdb_id"] for i in picks(client, users=[1, older["id"]])} == {201, 301, 401}
    # Adding Meera (U) tightens the whole group to U: 201 (U/A 7+) is left out too.
    assert {i["tmdb_id"] for i in picks(client, users=[1, older["id"], younger["id"]])} == {
        301,
        401,
    }

    # While switched to Meera, Watch together still enforces her U limit and hides
    # what films the adult rated in the reasons.
    client.post(f"/api/v1/children/{younger['id']}/switch")
    as_child = picks(client, users=[1])
    assert {i["tmdb_id"] for i in as_child} == {301, 401}
    assert all("Riya" not in r for i in as_child for r in i["reasons"])


def test_themes_note_is_written_by_the_llm_and_cached_per_film(
    client: TestClient, mock: respx.MockRouter
) -> None:
    client.put("/api/v1/settings/tmdb", json={"api_key": KEY})
    prompts: list[str] = []

    def gemini(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if "themes and values" not in body["systemInstruction"]["parts"][0]["text"]:
            return gemini_reply("OK")
        prompts.append(body["contents"][0]["parts"][0]["text"])
        return gemini_reply(
            "- Values: Brotherhood, kindness, forgiveness\n"
            "- Remake: No, original film.\n"
            "- Other famous films: None (directorial debut)."
        )

    mock.post(GEMINI).mock(side_effect=gemini)
    assert client.post("/api/v1/titles/201/themes").status_code == 409
    client.put("/api/v1/settings/llm", json={"provider": "gemini", "gemini_api_key": "k" * 30})

    child = client.post("/api/v1/children", json={"name": "Kabir", "birth_year": YEAR - 8}).json()
    client.post(f"/api/v1/children/{child['id']}/switch")
    detail = client.get("/api/v1/titles/201").json()
    assert detail["certificate"] == "U/A 7+"
    assert (
        detail["themes_note"] == "- Values: Brotherhood, kindness, forgiveness\n"
        "- Remake: No, original film.\n"
        "- Other famous films: None (directorial debut)."
    )
    assert len(prompts) == 1 and "Kumbalangi Nights" in prompts[0]
    assert "Films I watched already" in prompts[0]
    assert "riya" not in prompts[0].lower() and "kabir" not in prompts[0].lower()

    # The note is stored on the title, so reading or requesting it again needs no LLM call.
    client.post("/api/v1/children/exit")
    assert client.get("/api/v1/titles/201").json()["themes_note"] == detail["themes_note"]
    assert client.post("/api/v1/titles/201/themes").json()["themes_note"] == detail["themes_note"]
    assert len(prompts) == 1

    # Forcing a write regenerates the themes note.
    forced = client.post("/api/v1/titles/201/themes?force=true").json()
    assert forced["themes_note"] == detail["themes_note"]
    assert len(prompts) == 2

    # When the user has watched films, they are included in the prompt for the LLM.
    client.put("/api/v1/titles/101/reaction", json={"reaction": "loved"})
    client.post("/api/v1/titles/301/themes")
    assert len(prompts) == 3
    assert "Films I watched already: Léon: The Professional" in prompts[2]


def test_any_adult_in_the_household_can_manage_switch_to_and_assign_films_to_children(
    client: TestClient,
) -> None:
    client.put("/api/v1/settings/tmdb", json={"api_key": KEY})
    client.put("/api/v1/titles/101/reaction", json={"reaction": "loved"})
    child = client.post("/api/v1/children", json={"name": "Kabir", "birth_year": YEAR - 8}).json()
    # Changing an adult's country recomputes the child's certificate for that country (8 -> PG in US).
    client.put("/api/v1/me/streaming", json={"region": "US", "subscriptions": [8]})
    idle(client)
    assert client.get("/api/v1/children").json()[0]["max_certificate"] == "PG"

    engine = client.app.state.engine  # type: ignore[attr-defined]
    with Session(engine) as session:
        from iwanttowatch.api.auth import hasher

        session.add(
            User(
                id=10,
                username="anu",
                display_name="Anu",
                password_hash=hasher.hash("password1"),
                region="US",
            )
        )
        session.commit()
    # Another adult in the household sees Kabir, can assign a film to him, and can switch to him.
    client.post("/api/v1/auth/login", json={"username": "anu", "password": "password1"})
    assert [c["id"] for c in client.get("/api/v1/children").json()] == [child["id"]]
    # Assign Drishyam (302, PG-13 — above PG) to Kabir.
    assert client.put(f"/api/v1/children/{child['id']}/shortlist/302").status_code == 204
    idle(client)
    assert client.get("/api/v1/titles/302").json()["assigned_children"] == [child["id"]]

    switched = client.post(f"/api/v1/children/{child['id']}/switch").json()
    assert switched["id"] == child["id"] and switched["is_child"] is True
    # The assigned film appears in Kabir's shortlist and Discover feed.
    saved = feed(client, shortlist=True, available_only=False)
    assert [i["tmdb_id"] for i in saved["items"]] == [302]
    assert 302 in {i["tmdb_id"] for i in feed(client, available_only=False)["items"]}

    # Exiting returns to Anu (the adult who switched), who can unassign the film.
    back = client.post("/api/v1/children/exit").json()
    assert back["id"] == 10 and back["is_child"] is False
    assert client.delete(f"/api/v1/children/{child['id']}/shortlist/302").status_code == 204
    assert client.get("/api/v1/titles/302").json()["assigned_children"] == []
    assert client.delete(f"/api/v1/children/{child['id']}").status_code == 204
    assert client.get("/api/v1/children").json() == []


def test_age_limits_work_in_any_country_and_the_strictest_release_counts(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def details(tmdb_id: int) -> dict[str, Any]:
        d = base_details(tmdb_id)
        nl = {101: "16", 201: "6", 301: "AL", 302: "12", 401: "18"}
        results = d["release_dates"]["results"]
        if tmdb_id in nl:
            results.append({"iso_3166_1": "NL", "release_dates": [
                {"type": 3, "certification": nl[tmdb_id]}]})  # fmt: skip
        if tmdb_id == 201:
            # Two theatrical releases in India, the dubbed one rated A: A counts.
            for entry in results:
                if entry["iso_3166_1"] == "IN":
                    entry["release_dates"] = [
                        {"type": 3, "certification": "U/A 7+"},
                        {"type": 3, "certification": "A"},
                    ]
        return d

    monkeypatch.setattr(test_imports, "_details", details)
    client.put("/api/v1/settings/tmdb", json={"api_key": KEY})
    client.put("/api/v1/titles/101/reaction", json={"reaction": "loved"})
    child = client.post("/api/v1/children", json={"name": "Kabir", "birth_year": YEAR - 8}).json()
    idle(client)
    client.post(f"/api/v1/children/{child['id']}/switch")
    # Kumbalangi Nights (201) is U/A 7+ and A in India, so it's out.
    assert {i["tmdb_id"] for i in feed(client, available_only=False)["items"]} == {301, 401}
    client.post("/api/v1/children/exit")

    # In the Netherlands a 12-year-old gets certificate 12 from TMDb's Dutch scale.
    client.put("/api/v1/me/streaming", json={"region": "NL", "subscriptions": []})
    updated = client.put(
        f"/api/v1/children/{child['id']}", json={"name": "Kabir", "birth_year": YEAR - 12}
    ).json()
    assert updated["max_certificate"] == "12"
    idle(client)
    client.post(f"/api/v1/children/{child['id']}/switch")
    # 201 (6), 301 (AL), and 302 (12) are within 12; 101 (16), 401 (18), and 402 (no
    # Dutch certificate) are not.
    items = feed(client, available_only=False)["items"]
    assert {i["tmdb_id"] for i in items} == {201, 301, 302}
