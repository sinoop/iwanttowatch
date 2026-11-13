import json
import time
from datetime import date

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from test_imports import IMDB_NEW, KEY, upload

from iwanttowatch import llm
from iwanttowatch.models import Title, UserTitle

GEMINI = (
    "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent"
)
OLLAMA = "http://ollama.local:11434/api/chat"
PERSONA = "You love slow, warm Malayalam dramas and skip loud action films."


def add_ratings(client: TestClient, films: list[tuple[str, str, int, float, str, str]]) -> None:
    """Insert rated titles directly: (title, language, year, rating, genre, director)."""
    engine = client.app.state.engine  # type: ignore[attr-defined]
    with Session(engine) as session:
        start = session.query(Title).count()
        for i, (name, lang, year, rating, genre, director) in enumerate(films, start=start):
            session.add(
                Title(
                    tmdb_id=9000 + i, title=name, original_title=name, original_language=lang,
                    year=year, genres=[genre], directors=[{"id": i, "name": director}],
                )
            )  # fmt: skip
            session.add(
                UserTitle(
                    user_id=1, tmdb_id=9000 + i, source="imdb", rating=rating,
                    rated_at=date(2024, 1, 1 + i), watched=True,
                )
            )  # fmt: skip
        session.commit()


FILMS = [
    ("Kumbalangi Nights", "ml", 2019, 10.0, "Drama", "Madhu C. Narayanan"),
    ("Maheshinte Prathikaaram", "ml", 2016, 9.0, "Drama", "Dileesh Pothan"),
    ("Thondimuthalum Driksakshiyum", "ml", 2017, 9.0, "Drama", "Dileesh Pothan"),
    ("Joji", "ml", 2021, 8.0, "Drama", "Dileesh Pothan"),
    ("The Godfather", "en", 1972, 9.0, "Crime", "Francis Ford Coppola"),
    ("Transformers", "en", 2007, 3.0, "Action", "Michael Bay"),
]


def gemini_reply(*texts: str, thought: str | None = None) -> httpx.Response:
    parts = ([{"text": thought, "thought": True}] if thought else []) + [{"text": t} for t in texts]
    return httpx.Response(200, json={"candidates": [{"content": {"parts": parts}}]})


def test_gemini_persona_from_ratings(
    client: TestClient, mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(time, "sleep", lambda _: None)
    persona = client.get("/api/v1/me/persona").json()
    assert persona["text"] is None and persona["llm_configured"] is False
    assert client.post("/api/v1/me/persona").status_code == 409

    gemini = mock.post(GEMINI)
    gemini.side_effect = [httpx.Response(400, json={"error": {"message": "API key not valid"}})]
    bad = client.put("/api/v1/settings/llm", json={"provider": "gemini", "gemini_api_key": "nope"})
    assert bad.status_code == 400 and "API key not valid" in bad.json()["detail"]

    # A brief overload is retried rather than failing the test prompt.
    busy = httpx.Response(503, json={"error": {"message": "high demand"}})
    gemini.side_effect = [busy, gemini_reply("OK")]
    saved = client.put(
        "/api/v1/settings/llm", json={"provider": "gemini", "gemini_api_key": "g-key"}
    )
    assert saved.json()["llm"] == {
        "order": ["gemini"],
        "ollama_url": None,
        "ollama_model": None,
        "gemini_configured": True,
        "gemini_model": "gemini-flash-latest",
        "default_gemini_model": "gemini-flash-latest",
        "openai_base_url": None,
        "openai_configured": False,
        "openai_model": None,
        "default_openai_url": "https://api.openai.com/v1",
        "default_openai_model": "gpt-4o-mini",
        "claude_configured": False,
        "claude_model": None,
        "default_claude_model": "claude-3-5-haiku-latest",
    }
    assert "g-key" not in saved.text

    add_ratings(client, FILMS[:4])
    assert client.post("/api/v1/me/persona").status_code == 409  # fewer than 5 ratings

    add_ratings(client, FILMS[4:])

    gemini.side_effect = [gemini_reply(f'"{PERSONA}"', thought="Let me think about this person")]
    persona = client.post("/api/v1/me/persona").json()
    assert persona["text"] == PERSONA
    assert (persona["based_on_ratings"], persona["current_ratings"]) == (6, 6)

    request = gemini.calls.last.request
    assert request.headers["x-goog-api-key"] == "g-key"
    body = json.loads(request.content)
    assert "no metaphors" in body["systemInstruction"]["parts"][0]["text"]
    prompt = body["contents"][0]["parts"][0]["text"]
    assert "Rated films: 6" in prompt
    assert "ml 66%" in prompt and "en 33%" in prompt  # 4 of 6 Malayalam, 2 of 6 English
    assert "Dileesh Pothan (3 films)" in prompt
    assert "Most rated genres: Drama (4 films)" in prompt
    assert "Lowest rated: Transformers" in prompt
    # The prompt describes taste, not the person: no username or display name.
    assert "riya" not in prompt.lower()

    # Every call is in the admin's LLM log, newest first; retries count as one call.
    log = client.get("/api/v1/settings/llm/calls").json()
    assert (log["last_hour"], log["last_day"], log["failed_last_day"]) == (3, 3, 1)
    calls = log["calls"]
    assert [(c["purpose"], c["user"]) for c in calls] == [
        ("persona", "Riya Menon"), ("test", None), ("test", None),
    ]  # fmt: skip
    assert calls[0]["prompt"] == prompt and calls[0]["reply"].endswith(f'"{PERSONA}"')
    assert calls[0]["provider"] == "gemini" and calls[0]["model"] == "gemini-flash-latest"
    assert (calls[1]["reply"], calls[1]["error"]) == ("OK", None)
    assert calls[2]["reply"] is None and "API key not valid" in calls[2]["error"]

    # Only the newest calls are kept.
    monkeypatch.setattr(llm, "KEEP_CALLS", 2)
    gemini.side_effect = [gemini_reply(PERSONA)]
    client.post("/api/v1/me/persona")
    calls = client.get("/api/v1/settings/llm/calls").json()["calls"]
    assert [c["purpose"] for c in calls] == ["persona", "persona"]


def test_ollama_persona_and_refresh_after_import(
    client: TestClient, mock: respx.MockRouter
) -> None:
    ollama = mock.post(OLLAMA)
    ollama.side_effect = [
        httpx.Response(200, json={"message": {"role": "assistant", "content": "OK"}}),
        httpx.Response(200, json={"message": {"role": "assistant", "content": PERSONA}}),
    ]
    saved = client.put(
        "/api/v1/settings/llm",
        json={
            "provider": "ollama",
            "ollama_url": "http://ollama.local:11434",
            "model": "llama3.2:3b",
        },
    )
    assert saved.status_code == 200, saved.text
    assert json.loads(ollama.calls.last.request.content)["model"] == "llama3.2:3b"

    # Five ratings already exist; an import that adds one more rewrites the persona.
    add_ratings(client, FILMS[:5])
    assert client.put("/api/v1/settings/tmdb", json={"api_key": KEY}).status_code == 200
    upload(client, "ratings.csv", IMDB_NEW.encode())

    persona = client.get("/api/v1/me/persona").json()
    assert persona["text"] == PERSONA and persona["based_on_ratings"] == 6
    messages = json.loads(ollama.calls.last.request.content)["messages"]
    assert [m["role"] for m in messages] == ["system", "user"]
    assert "Léon: The Professional / Léon (1994, fr): loved" in messages[1]["content"]
    client.app.state.feed_worker.wait_until_idle()  # type: ignore[attr-defined]


def test_the_next_llm_in_the_admins_order_answers_when_the_first_fails(
    client: TestClient, mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(time, "sleep", lambda _: None)
    ollama = mock.post(OLLAMA)
    gemini = mock.post(GEMINI)
    ok = httpx.Response(200, json={"message": {"role": "assistant", "content": "OK"}})
    ollama.side_effect = [ok]
    gemini.side_effect = [gemini_reply("OK")]
    client.put(
        "/api/v1/settings/llm",
        json={"provider": "ollama", "ollama_url": "http://ollama.local:11434", "model": "m"},
    )
    added = client.put("/api/v1/settings/llm", json={"provider": "gemini", "gemini_api_key": "k"})
    assert added.json()["llm"]["order"] == ["ollama", "gemini"]  # new ones go last
    assert client.put("/api/v1/settings/llm/order", json={"order": ["gemini"]}).status_code == 400
    moved = client.put("/api/v1/settings/llm/order", json={"order": ["gemini", "ollama"]})
    assert moved.json()["llm"]["order"] == ["gemini", "ollama"]

    # Gemini is at its daily limit, so Ollama writes the persona.
    add_ratings(client, FILMS)
    limit = httpx.Response(429, json={"error": {"message": "Quota exceeded"}})
    gemini.side_effect = [limit, limit, limit]
    ollama.side_effect = [
        httpx.Response(200, json={"message": {"role": "assistant", "content": PERSONA}})
    ]
    assert client.post("/api/v1/me/persona").json()["text"] == PERSONA
    calls = client.get("/api/v1/settings/llm/calls").json()["calls"]
    assert [(c["provider"], c["error"] is None) for c in calls[:2]] == [
        ("ollama", True), ("gemini", False),
    ]  # fmt: skip

    # Turned off, a provider is no longer asked; its settings stay.
    after = client.delete("/api/v1/settings/llm/gemini").json()["llm"]
    assert after["order"] == ["ollama"] and after["gemini_configured"] is True
    gemini.side_effect = [gemini_reply("never")]
    ollama.side_effect = [
        httpx.Response(200, json={"message": {"role": "assistant", "content": PERSONA}})
    ]
    client.post("/api/v1/me/persona")
    assert gemini.call_count == 4  # the test prompt and 3 tries at the limit
    client.delete("/api/v1/settings/llm/ollama")
    assert client.get("/api/v1/me/persona").json()["llm_configured"] is False


def test_llm_activity_pagination_and_24h_limit(client: TestClient) -> None:
    from datetime import timedelta

    from iwanttowatch.db import utcnow
    from iwanttowatch.models import LlmCall

    engine = client.app.state.engine  # type: ignore[attr-defined]
    now = utcnow()

    # Insert 15 calls: 12 within the last 24 hours, 3 older than 24 hours
    with Session(engine) as session:
        for i in range(12):
            session.add(
                LlmCall(
                    created_at=now - timedelta(minutes=i * 10),
                    purpose="test",
                    provider="gemini",
                    model="gemini-flash-latest",
                    system="sys",
                    prompt=f"prompt {i}",
                    reply=f"reply {i}",
                    error=None,
                    duration_ms=100,
                )
            )
        for i in range(3):
            session.add(
                LlmCall(
                    created_at=now - timedelta(hours=25 + i),
                    purpose="test",
                    provider="gemini",
                    model="gemini-flash-latest",
                    system="sys",
                    prompt=f"old prompt {i}",
                    reply=f"old reply {i}",
                    error=None,
                    duration_ms=100,
                )
            )
        session.commit()

    # Default request: page=1, limit=10 -> returns 10 calls, total=12, total_pages=2, page=1
    res1 = client.get("/api/v1/settings/llm/calls").json()
    assert res1["total"] == 12
    assert res1["page"] == 1
    assert res1["total_pages"] == 2
    assert len(res1["calls"]) == 10
    # Calls older than 24 hours are excluded
    assert not any("old" in c["prompt"] for c in res1["calls"])

    # Page 2 returns the remaining 2 calls
    res2 = client.get("/api/v1/settings/llm/calls?page=2").json()
    assert res2["total"] == 12
    assert res2["page"] == 2
    assert res2["total_pages"] == 2
    assert len(res2["calls"]) == 2

    # Out of range page automatically clamps to last page
    res_clamped = client.get("/api/v1/settings/llm/calls?page=99").json()
    assert res_clamped["page"] == 2
    assert len(res_clamped["calls"]) == 2

    # When a new call is logged, it purges entries older than 24 hours from the DB
    with Session(engine) as session:
        assert session.query(LlmCall).count() == 15
    dummy_inner = type("Dummy", (), {"generate": lambda *a, **k: "OK"})()
    with Session(engine) as session:
        provider = llm.LoggedProvider(
            inner=dummy_inner,
            session=session,
            purpose="test",
            provider="gemini",
            model="m",
            user_id=None,
        )
        provider.generate("sys", "prompt")
    with Session(engine) as session:
        # 12 recent + 1 new = 13 calls; the 3 calls older than 24h were deleted!
        assert session.query(LlmCall).count() == 13
