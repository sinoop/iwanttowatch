import hashlib
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from iwanttowatch import radarr
from iwanttowatch.api import integrations
from iwanttowatch.api.mcp import KEY_SETTING as MCP_KEY_SETTING
from iwanttowatch.models import (
    Availability,
    LibraryItem,
    Recommendation,
    ShortlistItem,
    Title,
    set_setting,
)
from iwanttowatch.tmdb import API_KEY_SETTING as TMDB_KEY_SETTING


def test_home_assistant_integration_session_and_bearer(client: TestClient) -> None:
    with Session(client.app.state.engine) as session:  # type: ignore[attr-defined]
        set_setting(session, MCP_KEY_SETTING, hashlib.sha256(b"ha-secret-key").hexdigest())
        set_setting(session, TMDB_KEY_SETTING, "test-tmdb-key")
        session.add_all(
            [
                Title(
                    tmdb_id=301,
                    title="Drishyam",
                    original_title="Drishyam",
                    original_language="ml",
                    year=2013,
                    poster_path="/drishyam.jpg",
                    imdb_rating=8.3,
                ),
                Title(
                    tmdb_id=302,
                    title="Kumbalangi Nights",
                    original_title="Kumbalangi Nights",
                    original_language="ml",
                    year=2019,
                    poster_path="/kumbalangi.jpg",
                    imdb_rating=8.5,
                ),
                Title(
                    tmdb_id=303,
                    title="Low Match Movie",
                    original_title="Low Match Movie",
                    original_language="en",
                    year=2020,
                    imdb_rating=5.4,
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                Recommendation(user_id=1, tmdb_id=301, score=0.92, rank=1, reasons=[]),
                Recommendation(user_id=1, tmdb_id=303, score=0.55, rank=2, reasons=[]),
                ShortlistItem(user_id=1, tmdb_id=302),
                LibraryItem(
                    user_id=1,
                    item_id="jf-301",
                    name="Drishyam",
                    year=2013,
                    tmdb_id=301,
                ),
                Availability(
                    tmdb_id=302,
                    region="IN",
                    offers=[{"type": "flatrate", "provider_name": "Amazon Prime Video"}],
                ),
            ]
        )
        session.commit()

    # Authenticated via session cookie
    res = client.get("/api/v1/integrations/home-assistant", params={"min_match": 80})
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["user"] == "Riya Menon"
    assert data["radarr_configured"] is False
    assert len(data["high_rated_recommendations"]) == 1
    rec = data["high_rated_recommendations"][0]
    assert rec["tmdb_id"] == 301
    assert rec["match"] == 92
    assert rec["imdb_rating"] == 8.3
    assert rec["in_jellyfin"] is True
    assert rec["in_shortlist"] is False
    assert rec["poster_url"] == "https://image.tmdb.org/t/p/w500/drishyam.jpg"

    assert len(data["shortlisted"]) == 1
    sl = data["shortlisted"][0]
    assert sl["tmdb_id"] == 302
    assert sl["in_shortlist"] is True
    assert sl["streaming_services"] == ["Amazon Prime Video"]

    # Unauthenticated request without session or Bearer key is rejected
    client.post("/api/v1/auth/logout")
    unauth = client.get("/api/v1/integrations/home-assistant")
    assert unauth.status_code == 401

    # Invalid Bearer key is rejected
    bad = client.get(
        "/api/v1/integrations/home-assistant",
        headers={"Authorization": "Bearer wrong-key"},
    )
    assert bad.status_code == 401

    # Valid Bearer key succeeds
    ok = client.get(
        "/api/v1/integrations/home-assistant",
        headers={"Authorization": "Bearer ha-secret-key"},
        params={"username": "riya"},
    )
    assert ok.status_code == 200
    assert ok.json()["user"] == "Riya Menon"
    assert len(ok.json()["shortlisted"]) == 1


def test_home_assistant_search_shortlist_and_radarr(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Session(client.app.state.engine) as session:  # type: ignore[attr-defined]
        set_setting(session, MCP_KEY_SETTING, hashlib.sha256(b"ha-secret-key").hexdigest())
        set_setting(session, TMDB_KEY_SETTING, "test-tmdb-key")
        session.add(
            Title(
                tmdb_id=401,
                title="Premam",
                original_title="Premam",
                original_language="ml",
                year=2015,
                poster_path="/premam.jpg",
                imdb_rating=8.3,
                overview="Three stages of love.",
            )
        )
        session.flush()
        session.add(Recommendation(user_id=1, tmdb_id=401, score=0.88, rank=1, reasons=[]))
        session.commit()

    headers = {"Authorization": "Bearer ha-secret-key"}

    monkeypatch.setattr(
        integrations,
        "search_movies",
        lambda _tmdb, _query, _year=None: [
            {
                "tmdb_id": 401,
                "title": "Premam",
                "year": 2015,
                "poster_path": "/premam.jpg",
                "overview": "Three stages of love.",
            },
            {
                "tmdb_id": 402,
                "title": "Banglore Days",
                "year": 2014,
                "poster_path": "/bdays.jpg",
                "overview": "Three cousins in Bangalore.",
            },
        ],
    )
    search_res = client.get(
        "/api/v1/integrations/home-assistant/search",
        headers=headers,
        params={"query": "Premam"},
    )
    assert search_res.status_code == 200, search_res.text
    items = search_res.json()
    assert len(items) == 2
    assert items[0]["tmdb_id"] == 401
    assert items[0]["match"] == 88
    assert items[0]["imdb_rating"] == 8.3
    assert items[1]["tmdb_id"] == 402
    assert items[1]["match"] is None

    # Shortlist add & remove
    monkeypatch.setattr(integrations, "availability", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(radarr, "auto_sync_if_unstreamable", lambda *_args, **_kwargs: None)
    add_res = client.put(
        "/api/v1/integrations/home-assistant/titles/401/shortlist",
        headers=headers,
    )
    assert add_res.status_code == 204

    feed_res = client.get("/api/v1/integrations/home-assistant", headers=headers)
    assert any(m["tmdb_id"] == 401 for m in feed_res.json()["shortlisted"])

    del_res = client.delete(
        "/api/v1/integrations/home-assistant/titles/401/shortlist",
        headers=headers,
    )
    assert del_res.status_code == 204

    feed_after = client.get("/api/v1/integrations/home-assistant", headers=headers)
    assert all(m["tmdb_id"] != 401 for m in feed_after.json()["shortlisted"])

    # Radarr status & request
    queued: list[dict[str, Any]] = []

    def fake_queue(**kwargs: Any) -> dict[str, Any]:
        queued.append(kwargs)
        return {"id": 99}

    monkeypatch.setattr(radarr, "queue_movie", fake_queue)
    monkeypatch.setattr(
        radarr,
        "movie_status",
        lambda _session, tmdb_id: {
            "configured": True,
            "movie_id": 99 if queued else None,
            "title": "Premam",
            "has_file": False,
            "monitored": bool(queued),
            "is_available": True,
            "status": "monitored" if queued else "not_in_radarr",
        },
    )

    st_before = client.get(
        "/api/v1/integrations/home-assistant/titles/401/radarr",
        headers=headers,
    )
    assert st_before.status_code == 200
    assert st_before.json()["status"] == "not_in_radarr"

    req_res = client.post(
        "/api/v1/integrations/home-assistant/titles/401/radarr",
        headers=headers,
    )
    assert req_res.status_code == 200, req_res.text
    assert req_res.json()["monitored"] is True
    assert req_res.json()["status"] == "monitored"
    assert queued[0]["tmdb_id"] == 401


def test_home_assistant_detail_reaction_and_ask(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Session(client.app.state.engine) as session:  # type: ignore[attr-defined]
        set_setting(session, MCP_KEY_SETTING, hashlib.sha256(b"ha-secret-key").hexdigest())
        set_setting(session, TMDB_KEY_SETTING, "test-tmdb-key")
        session.add(
            Title(
                tmdb_id=501,
                title="Manichitrathazhu",
                original_title="Manichitrathazhu",
                original_language="ml",
                year=1993,
                runtime=169,
                poster_path="/mani.jpg",
                imdb_rating=8.8,
                overview="A psychological mystery in an ancestral home.",
                genres=["Mystery", "Horror", "Comedy"],
            )
        )
        session.flush()
        session.add(Recommendation(user_id=1, tmdb_id=501, score=0.95, rank=1, reasons=[]))
        session.commit()

    headers = {"Authorization": "Bearer ha-secret-key"}

    monkeypatch.setattr(integrations, "availability", lambda *_args, **_kwargs: {})
    detail_res = client.get("/api/v1/integrations/home-assistant/titles/501", headers=headers)
    assert detail_res.status_code == 200, detail_res.text
    detail = detail_res.json()
    assert detail["title"] == "Manichitrathazhu"
    assert detail["runtime"] == 169
    assert detail["genres"] == ["Mystery", "Horror", "Comedy"]

    # Set reaction (loved) and clear it
    react_res = client.put(
        "/api/v1/integrations/home-assistant/titles/501/reaction",
        headers=headers,
        json={"reaction": "loved", "watched": True, "tags": []},
    )
    assert react_res.status_code == 200, react_res.text
    assert react_res.json()["reaction"] == "loved"
    assert react_res.json()["watched"] is True

    clear_res = client.delete(
        "/api/v1/integrations/home-assistant/titles/501/reaction",
        headers=headers,
    )
    assert clear_res.status_code == 204

    # Ask AI
    from iwanttowatch.api.feed import AskAnswer, AskPick

    monkeypatch.setattr(
        integrations,
        "ask_feed",
        lambda *_args, **_kwargs: AskAnswer(
            picks=[AskPick(tmdb_id=501, why="Classic Malayalam mystery")],
            considered=1,
        ),
    )
    ask_res = client.post(
        "/api/v1/integrations/home-assistant/ask",
        headers=headers,
        json={"text": "classic mystery"},
    )
    assert ask_res.status_code == 200, ask_res.text
    ask_data = ask_res.json()
    assert ask_data["considered"] == 1
    assert len(ask_data["picks"]) == 1
    assert ask_data["picks"][0]["tmdb_id"] == 501
    assert ask_data["picks"][0]["why"] == "Classic Malayalam mystery"
