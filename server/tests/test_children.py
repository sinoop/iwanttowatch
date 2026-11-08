import json
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

PIN = "2468"


def test_child_profile_filters_above_certificate_and_hides_others_ratings(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Give Premam (401, U) family-positive keywords so it outranks Drishyam (301, U)
    # before the parent tags Drishyam as Great with family.
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
    # Parent loves Léon (101, certificate A) — an adult rating the child must not see.
    client.put("/api/v1/titles/101/reaction", json={"reaction": "loved", "tags": ["great_story"]})

    certs = [c["code"] for c in client.get("/api/v1/certificates").json()]
    assert certs == ["U", "U/A 7+", "U/A 13+", "U/A 16+"]
    # Adult-only "A" and unknown codes cannot be set as a child's age limit.
    assert (
        client.post("/api/v1/children", json={"name": "Kabir", "max_certificate": "A"}).status_code
        == 400
    )

    child = client.post(
        "/api/v1/children", json={"name": "Kabir", "max_certificate": "U/A 7+"}
    ).json()
    assert child == {"id": 2, "name": "Kabir", "max_certificate": "U/A 7+"}
    assert client.get("/api/v1/children").json() == [child]
    idle(client)
    client.put("/api/v1/me/parent-pin", json={"pin": PIN})

    switched = client.post(f"/api/v1/children/{child['id']}/switch").json()
    assert switched["display_name"] == "Kabir"
    assert switched["parent_id"] == 1 and switched["max_certificate"] == "U/A 7+"
    # Kids can't see the parent's ratings or use adult-only account endpoints.
    assert client.get("/api/v1/ratings").json()["total"] == 0
    assert client.get("/api/v1/me/export").status_code == 403
    assert client.post("/api/v1/me/share").status_code == 403
    assert (
        client.post("/api/v1/children", json={"name": "X", "max_certificate": "U"}).status_code
        == 403
    )

    # Feed for U/A 7+ in IN: Kumbalangi Nights (201, U/A 7+), Drishyam (301, U),
    # and Premam (401, U). Léon (101, A), Drishyam (302, U/A 13+), and uncertified
    # Premam (402) are left out.
    items = feed(client, available_only=False)["items"]
    assert {i["tmdb_id"] for i in items} == {201, 301, 401}
    by_id = {i["tmdb_id"]: i for i in items}
    assert by_id[201]["certificate"] == "U/A 7+"
    assert "Themes of friendship and kindness" in by_id[401]["reasons"]
    assert by_id[401]["match"] > by_id[301]["match"]

    # Films above the child's certificate cannot be opened, rated, or given feedback.
    assert client.get("/api/v1/titles/101").status_code == 403
    assert client.put("/api/v1/titles/101/reaction", json={"reaction": "liked"}).status_code == 403
    assert client.put("/api/v1/titles/302/feedback", json={"kind": "up"}).status_code == 403

    # Parent switches back, tags Drishyam (301, U) as Great with family, and tightens
    # the child's certificate to U.
    parent = client.post("/api/v1/children/exit", json={"pin": PIN}).json()
    assert parent["id"] == 1 and parent["parent_id"] is None
    client.put(
        "/api/v1/titles/301/reaction",
        json={"reaction": "loved", "tags": ["great_with_family"]},
    )
    updated = client.put(
        f"/api/v1/children/{child['id']}", json={"name": "Kabir", "max_certificate": "U"}
    ).json()
    assert updated["max_certificate"] == "U"
    idle(client)

    client.post(f"/api/v1/children/{child['id']}/switch")
    # Kumbalangi Nights (201, U/A 7+) is now above U and gone from the feed; Drishyam
    # (301, U) is still unseen by the child and boosted by the parent's family tag,
    # while the parent's rating still doesn't appear in the child's rating list.
    items = feed(client, available_only=False)["items"]
    assert {i["tmdb_id"] for i in items} == {301, 401}
    by_id = {i["tmdb_id"]: i for i in items}
    assert by_id[301]["reasons"][0] == "Tagged Great with family"
    assert client.get("/api/v1/ratings").json()["total"] == 0

    # The child's own reaction is stored on the child's profile, not the parent's.
    client.put("/api/v1/titles/401/reaction", json={"reaction": "loved"})
    assert [i["tmdb_id"] for i in client.get("/api/v1/ratings").json()["items"]] == [401]
    assert [i["tmdb_id"] for i in feed(client, available_only=False)["items"]] == [301]
    client.post("/api/v1/children/exit", json={"pin": PIN})
    assert {i["tmdb_id"] for i in client.get("/api/v1/ratings").json()["items"]} == {101, 301}


def test_group_picks_apply_the_childs_certificate_to_the_whole_group(
    client: TestClient,
) -> None:
    client.put("/api/v1/settings/tmdb", json={"api_key": KEY})
    client.put("/api/v1/titles/101/reaction", json={"reaction": "loved"})
    feed(client)
    idle(client)
    # Without a child, the parent's feed has 201 (U/A 7+), 301 (U), 302 (U/A 13+),
    # 401 (U), and 402 (no certificate).
    assert {i["tmdb_id"] for i in picks(client, users=[1])} == {201, 301, 302, 401, 402}

    older = client.post(
        "/api/v1/children", json={"name": "Aarav", "max_certificate": "U/A 7+"}
    ).json()
    younger = client.post("/api/v1/children", json={"name": "Meera", "max_certificate": "U"}).json()
    idle(client)

    together = client.get("/api/v1/together").json()
    by_name = {p["name"]: p["max_certificate"] for p in together["household"]}
    assert by_name == {"Aarav": "U/A 7+", "Meera": "U", "Riya Menon": None}

    # Parent + Aarav (U/A 7+): 302 (U/A 13+) and uncertified 402 are left out.
    assert {i["tmdb_id"] for i in picks(client, users=[1, older["id"]])} == {201, 301, 401}
    # Adding Meera (U) tightens the whole group to U: 201 (U/A 7+) is left out too.
    assert {i["tmdb_id"] for i in picks(client, users=[1, older["id"], younger["id"]])} == {
        301,
        401,
    }

    # While switched to Meera, Watch together still enforces her U limit and hides
    # what films the parent rated in the reasons.
    client.put("/api/v1/me/parent-pin", json={"pin": PIN})
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
        return gemini_reply("Warm brotherhood and kindness carry four brothers through hardship.")

    mock.post(GEMINI).mock(side_effect=gemini)
    assert client.post("/api/v1/titles/201/themes").status_code == 409
    client.put("/api/v1/settings/llm", json={"provider": "gemini", "gemini_api_key": "k" * 30})

    child = client.post(
        "/api/v1/children", json={"name": "Kabir", "max_certificate": "U/A 7+"}
    ).json()
    client.put("/api/v1/me/parent-pin", json={"pin": PIN})
    client.post(f"/api/v1/children/{child['id']}/switch")
    detail = client.get("/api/v1/titles/201").json()
    assert detail["certificate"] == "U/A 7+"
    assert (
        detail["themes_note"]
        == "Warm brotherhood and kindness carry four brothers through hardship."
    )
    assert len(prompts) == 1 and "Kumbalangi Nights" in prompts[0]
    assert "riya" not in prompts[0].lower() and "kabir" not in prompts[0].lower()

    # The note is stored on the title, so reading or requesting it again needs no LLM call.
    client.post("/api/v1/children/exit", json={"pin": PIN})
    assert client.get("/api/v1/titles/201").json()["themes_note"] == detail["themes_note"]
    assert client.post("/api/v1/titles/201/themes").json()["themes_note"] == detail["themes_note"]
    assert len(prompts) == 1


def test_only_a_childs_parent_can_manage_or_switch_to_them(client: TestClient) -> None:
    client.put("/api/v1/settings/tmdb", json={"api_key": KEY})
    child = client.post(
        "/api/v1/children", json={"name": "Kabir", "max_certificate": "U/A 7+"}
    ).json()
    # Changing the parent's country maps the child's certificate to that country.
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
                region="IN",
            )
        )
        session.commit()
    client.post("/api/v1/auth/login", json={"username": "anu", "password": "password1"})
    assert client.get("/api/v1/children").json() == []
    assert client.post(f"/api/v1/children/{child['id']}/switch").status_code == 404
    assert client.delete(f"/api/v1/children/{child['id']}").status_code == 204
    login = {"username": "riya", "password": "password1"}
    assert client.post("/api/v1/auth/login", json=login).status_code == 200
    assert len(client.get("/api/v1/children").json()) == 1
    assert client.delete(f"/api/v1/children/{child['id']}").status_code == 204
    assert client.get("/api/v1/children").json() == []


def test_leaving_a_child_profile_needs_the_parent_pin(client: TestClient) -> None:
    client.put("/api/v1/settings/tmdb", json={"api_key": KEY})
    child = client.post(
        "/api/v1/children", json={"name": "Kabir", "max_certificate": "U/A 7+"}
    ).json()
    sibling = client.post("/api/v1/children", json={"name": "Meera", "max_certificate": "U"}).json()
    assert client.post(f"/api/v1/children/{child['id']}/switch").status_code == 409
    assert client.put("/api/v1/me/parent-pin", json={"pin": "12"}).status_code == 422
    assert client.put("/api/v1/me/parent-pin", json={"pin": PIN}).json() == {"pin_set": True}

    assert client.post(f"/api/v1/children/{child['id']}/switch").status_code == 200
    # From a child profile, there's no way to the parent or a sibling without the PIN.
    assert client.get("/api/v1/children").status_code == 403
    assert client.post(f"/api/v1/children/{sibling['id']}/switch").status_code == 403
    assert client.put("/api/v1/me/parent-pin", json={"pin": "1111"}).status_code == 403
    assert client.post("/api/v1/children/exit", json={"pin": "1357"}).status_code == 403
    assert client.get("/api/v1/me").json()["display_name"] == "Kabir"
    # Search only finds films within the child's limit: Drishyam 301 (U), not 302 (U/A 13+).
    found = client.get("/api/v1/catalog/search", params={"query": "drishyam"}).json()
    assert [c["tmdb_id"] for c in found] == [301]

    # Guessing is cut off after five wrong PINs, even if the next one is right.
    for _ in range(4):
        client.post("/api/v1/children/exit", json={"pin": "0000"})
    assert client.post("/api/v1/children/exit", json={"pin": PIN}).status_code == 429
    client.app.state.pin_failures.clear()  # type: ignore[attr-defined]
    assert client.post("/api/v1/children/exit", json={"pin": PIN}).json()["id"] == 1
    assert len(client.get("/api/v1/children").json()) == 2

    # A device left on a child profile that's deleted elsewhere is signed out, not
    # handed the parent's account.
    client.post(f"/api/v1/children/{child['id']}/switch")
    with Session(client.app.state.engine) as session:  # type: ignore[attr-defined]
        session.delete(session.get(User, child["id"]))
        session.commit()
    assert client.get("/api/v1/me").status_code == 401
    assert client.get("/api/v1/me").status_code == 401


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
    client.put("/api/v1/me/parent-pin", json={"pin": PIN})
    child = client.post(
        "/api/v1/children", json={"name": "Kabir", "max_certificate": "U/A 7+"}
    ).json()
    idle(client)
    client.post(f"/api/v1/children/{child['id']}/switch")
    # Kumbalangi Nights (201) is U/A 7+ and A in India, so it's out.
    assert {i["tmdb_id"] for i in feed(client, available_only=False)["items"]} == {301, 401}
    client.post("/api/v1/children/exit", json={"pin": PIN})

    # In the Netherlands the limits come from TMDb's Dutch scale, without its adult 18.
    client.put("/api/v1/me/streaming", json={"region": "NL", "subscriptions": []})
    certs = [c["code"] for c in client.get("/api/v1/certificates").json()]
    assert certs == ["AL", "6", "9", "12", "14", "16"]
    client.put(f"/api/v1/children/{child['id']}", json={"name": "Kabir", "max_certificate": "12"})
    idle(client)
    client.post(f"/api/v1/children/{child['id']}/switch")
    # 201 (6), 301 (AL), and 302 (12) are within 12; 101 (16), 401 (18), and 402 (no
    # Dutch certificate) are not.
    items = feed(client, available_only=False)["items"]
    assert {i["tmdb_id"] for i in items} == {201, 301, 302}
