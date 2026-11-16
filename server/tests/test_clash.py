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

    atg = client.get("/api/v1/me/against-the-grain")
    assert atg.status_code == 200
    atg_data = atg.json()
    assert atg_data["divergent_count"] == 2
    assert atg_data["total_compared"] == 3
    assert atg_data["score"] == 67
    assert atg_data["archetype"]
    assert len(atg_data["items"]) == 2


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


def test_clash_hypotheses_playground_and_model_signals(
    client: TestClient, mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup_sample_movies(client)
    monkeypatch.setenv("IWANTTOWATCH_TMDB_BASE_URL", "https://api.themoviedb.org/3")
    engine = client.app.state.engine  # type: ignore[attr-defined]
    with Session(engine) as session:
        session.merge(AppSetting(key="tmdb_api_key", value=KEY))
        session.merge(AppSetting(key="gemini_api_key", value="test-key"))
        session.merge(AppSetting(key="llm_order", value="gemini"))
        # Add candidate films and another Drama for feature-level testing
        session.add(
            Title(
                tmdb_id=5010,
                title="Another Drama",
                original_title="Another Drama",
                original_language="en",
                year=2021,
                genres=["Drama"],
                imdb_rating=7.5,
                imdb_votes=500,
            )
        )
        session.commit()

    import json

    payload = json.dumps(
        {
            "summary": "You rated this acclaimed drama far below consensus.",
            "hypotheses": [
                {
                    "question": "Did it feel too slow even beyond your note?",
                    "kind": "tag",
                    "tag_id": "too_slow",  # Already in UserTitle.tags -> should be skipped!
                },
                {
                    "question": "Were the characters too flat to care about?",
                    "kind": "tag",
                    "tag_id": "flat_characters",
                },
                {
                    "question": "Was the Drama genre itself the mismatch?",
                    "kind": "feature",
                    "feature_key": "genre:Drama",
                },
                {
                    "question": "Was this mostly overhyped / wrong mood?",
                    "kind": "outlier",
                },
            ],
        }
    )
    mock.post(GEMINI).mock(return_value=gemini_reply(payload))

    res = client.post("/api/v1/titles/5002/clash")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["clash"] == "You rated this acclaimed drama far below consensus."
    hyps = body["clash_hypotheses"]
    # too_slow was skipped because it was already tagged; 3 valid hypotheses remain
    assert len(hyps) == 3
    assert [h["kind"] for h in hyps] == ["tag", "feature", "outlier"]
    assert hyps[0]["tag_id"] == "flat_characters"

    # Answer Yes to tag hypothesis -> adds flat_characters tag
    tag_h = hyps[0]["id"]
    ans1 = client.post(f"/api/v1/titles/5002/clash/{tag_h}", json={"answer": True})
    assert ans1.status_code == 200, ans1.text
    assert "flat_characters" in ans1.json()["tags"]
    assert ans1.json()["effect"] == "Added tag: Flat characters"

    # Answer Yes to feature hypothesis -> negative adjustment on genre:Drama
    feat_h = hyps[1]["id"]
    ans2 = client.post(f"/api/v1/titles/5002/clash/{feat_h}", json={"answer": True})
    assert ans2.status_code == 200
    assert "Drama" in ans2.json()["effect"]

    # Answer Yes to outlier hypothesis -> marks 5002 as dampened outlier
    out_h = hyps[2]["id"]
    ans3 = client.post(f"/api/v1/titles/5002/clash/{out_h}", json={"answer": True})
    assert ans3.status_code == 200
    assert "outlier" in ans3.json()["effect"].lower()

    from iwanttowatch.taste import clash_model_signals

    with Session(engine) as session:
        dampened, feat_adj, rated_tags = clash_model_signals(session, user_id=1)
        assert 5002 in dampened
        assert feat_adj.get("genre:Drama") == pytest.approx(-0.05)
        assert "flat_characters" in rated_tags[5002]

    # Toggle tag hypothesis back to No -> removes flat_characters tag
    ans_undo = client.post(f"/api/v1/titles/5002/clash/{tag_h}", json={"answer": False})
    assert ans_undo.status_code == 200
    assert "flat_characters" not in ans_undo.json()["tags"]


def test_recommender_uses_clash_signals() -> None:
    from iwanttowatch.recommender import Label, Vectors, _quality, _weight_divergent_labels, score

    def _title(tmdb_id: int, name: str, genres: list[str], imdb_rating: float) -> Title:
        return Title(
            tmdb_id=tmdb_id,
            title=name,
            original_title=name,
            original_language="en",
            genres=genres,
            keywords=[],
            directors=[],
            writers=[],
            cast=[],
            imdb_rating=imdb_rating,
            imdb_votes=1000,
        )

    titles = {
        1: _title(1, "A", ["Drama"], 8.5),
        2: _title(2, "B", ["Comedy"], 6.0),
        3: _title(3, "C", ["Drama"], 7.5),
    }
    labels = [
        Label(tmdb_id=1, value=0.1, weight=1.0, explicit=True),
        Label(tmdb_id=2, value=0.8, weight=1.0, explicit=True),
    ]
    vectors = Vectors(list(titles.values()))
    quality = _quality(list(titles.values()))

    boosted = _weight_divergent_labels(vectors, labels, quality)
    dampened = _weight_divergent_labels(vectors, labels, quality, dampened_outliers={1})
    assert boosted[0].weight > 1.0
    assert dampened[0].weight < 1.0

    base = score(titles, labels, [3])[0].score
    adjusted = score(
        titles,
        labels,
        [3],
        dampened_outliers={1},
        feature_adjustments={"genre:Drama": -0.1},
    )[0].score
    assert adjusted != base
