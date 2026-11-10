from datetime import date
from unittest.mock import MagicMock

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from test_imports import KEY

from iwanttowatch.models import AppSetting, OpinionClash, Title, UserTitle
from iwanttowatch.taste import explain_clash, find_divergent_ratings

GEMINI = (
    "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent"
)


def gemini_reply(text: str) -> httpx.Response:
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": text}]}}]})


def setup_sample_movies(client: TestClient) -> None:
    engine = client.app.state.engine  # type: ignore[attr-defined]
    with Session(engine) as session:
        # 1. Guilty pleasure: user gave 9.0, audience 5.5 (TMDb 600 votes) -> delta +3.5
        session.add(
            Title(
                tmdb_id=5001,
                title="Cheesy Action",
                original_title="Cheesy Action",
                original_language="en",
                year=2020,
                vote_average=5.5,
                vote_count=600,
                genres=["Action"],
            )
        )
        session.add(
            UserTitle(
                user_id=1,
                tmdb_id=5001,
                source="app",
                rating=9.0,
                reaction="loved",
                tags=["exciting", "great_action"],
                note="Pure mindless fun",
                rated_at=date(2024, 1, 1),
            )
        )

        # 2. Unpopular dislike: user gave 3.0, audience 8.4 (IMDb 2000 votes) -> delta -5.4
        session.add(
            Title(
                tmdb_id=5002,
                title="Acclaimed Drama",
                original_title="Acclaimed Drama",
                original_language="en",
                year=2021,
                imdb_rating=8.4,
                imdb_votes=2000,
                genres=["Drama"],
            )
        )
        session.add(
            UserTitle(
                user_id=1,
                tmdb_id=5002,
                source="imdb",
                rating=3.0,
                reaction="disliked",
                tags=["too_slow"],
                rated_at=date(2024, 1, 2),
            )
        )

        # 3. Consensus match: user gave 7.5, audience 7.6 -> delta -0.1 (not divergent)
        session.add(
            Title(
                tmdb_id=5003,
                title="Normal Movie",
                original_title="Normal Movie",
                original_language="en",
                year=2022,
                vote_average=7.6,
                vote_count=800,
            )
        )
        session.add(
            UserTitle(
                user_id=1,
                tmdb_id=5003,
                source="app",
                rating=7.5,
                rated_at=date(2024, 1, 3),
            )
        )

        # 4. Obscure film: user gave 10.0, audience 4.0, but only 5 votes -> excluded
        session.add(
            Title(
                tmdb_id=5004,
                title="Obscure Indie",
                original_title="Obscure Indie",
                original_language="en",
                year=2023,
                vote_average=4.0,
                vote_count=5,
            )
        )
        session.add(
            UserTitle(
                user_id=1,
                tmdb_id=5004,
                source="app",
                rating=10.0,
                rated_at=date(2024, 1, 4),
            )
        )

        session.commit()


def test_find_divergent_ratings(client: TestClient) -> None:
    setup_sample_movies(client)
    engine = client.app.state.engine  # type: ignore[attr-defined]
    with Session(engine) as session:
        divergent = find_divergent_ratings(session, user_id=1)
        assert len(divergent) == 2
        # Acclaimed Drama has delta -5.4 and 2000 votes -> higher rank weight
        assert divergent[0].tmdb_id == 5002
        assert divergent[0].divergence == -5.4
        assert divergent[0].consensus_rating == 8.4
        assert divergent[0].user_rating == 3.0

        assert divergent[1].tmdb_id == 5001
        assert divergent[1].divergence == 3.5
        assert divergent[1].consensus_rating == 5.5
        assert divergent[1].user_rating == 9.0

    # Test API endpoint
    response = client.get("/api/v1/me/divergent-ratings")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["tmdb_id"] == 5002
    assert data[0]["divergence"] == -5.4
    assert data[0]["clash"] is None


def test_explain_clash_logic(client: TestClient) -> None:
    setup_sample_movies(client)
    engine = client.app.state.engine  # type: ignore[attr-defined]
    fake_llm = MagicMock()
    fake_llm.generate.return_value = (
        "While critics lauded its solemn restraint, your aversion to slow pacing made it a slog. "
        "Your taste favors propulsive narrative tension."
    )

    with Session(engine) as session:
        title = session.get(Title, 5002)
        assert title is not None
        clash = explain_clash(
            session=session,
            user_id=1,
            title=title,
            user_rating=3.0,
            reaction="disliked",
            tags=["too_slow"],
            note=None,
            llm=fake_llm,
        )
        assert "solemn restraint" in clash
        assert fake_llm.generate.call_count == 1

        # Check cached in DB
        db_clash = session.get(OpinionClash, (1, 5002))
        assert db_clash is not None
        assert db_clash.text == clash

        # Calling again uses cache without invoking LLM
        cached = explain_clash(
            session=session,
            user_id=1,
            title=title,
            user_rating=3.0,
            reaction="disliked",
            tags=["too_slow"],
            note=None,
            llm=fake_llm,
        )
        assert cached == clash
        assert fake_llm.generate.call_count == 1


def test_explain_title_clash_endpoint(
    client: TestClient, mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup_sample_movies(client)
    monkeypatch.setenv("IWANTTOWATCH_TMDB_BASE_URL", "https://api.themoviedb.org/3")
    engine = client.app.state.engine  # type: ignore[attr-defined]
    with Session(engine) as session:
        session.merge(AppSetting(key="tmdb_api_key", value=KEY))
        session.merge(AppSetting(key="gemini_api_key", value="test-key"))
        session.merge(AppSetting(key="llm_order", value="gemini"))
        session.commit()

    analysis_text = (
        "General audiences loved the inventive spectacle, but your preference for tight storytelling "
        "made the plot holes unignorable for you."
    )
    mock.post(GEMINI).mock(return_value=gemini_reply(analysis_text))

    # Request clash explanation via API
    res = client.post("/api/v1/titles/5001/clash")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["tmdb_id"] == 5001
    assert body["clash"] == analysis_text

    # Verify divergent-ratings endpoint now includes the clash
    div_res = client.get("/api/v1/me/divergent-ratings")
    assert div_res.status_code == 200
    item = next(x for x in div_res.json() if x["tmdb_id"] == 5001)
    assert item["clash"] == analysis_text

    # Request for an unrated film should return 400
    with Session(engine) as session:
        session.add(
            Title(
                tmdb_id=5099,
                title="Unrated Movie",
                original_title="Unrated Movie",
                original_language="en",
            )
        )
        session.commit()
    unrated_res = client.post("/api/v1/titles/5099/clash")
    assert unrated_res.status_code == 400
