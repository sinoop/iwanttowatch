from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from test_imports import KEY

from iwanttowatch.models import Title, UserTitle


def setup_taste_data(client: TestClient) -> None:
    client.put("/api/v1/settings/tmdb", json={"api_key": KEY})
    engine = client.app.state.engine  # type: ignore[attr-defined]
    with Session(engine) as session:
        # Create a series of Action movies the user loves
        for tmdb_id in range(101, 110):
            session.add(
                Title(
                    tmdb_id=tmdb_id,
                    title=f"Action Hit {tmdb_id}",
                    original_title=f"Action Hit {tmdb_id}",
                    original_language="en",
                    year=2022,
                    genres=["Action", "Thriller"],
                    keywords=["explosion", "chase"],
                    vote_average=7.5,
                    vote_count=500,
                )
            )
            session.add(
                UserTitle(
                    user_id=1,
                    tmdb_id=tmdb_id,
                    source="app",
                    rating=9.5,
                    reaction="loved",
                    tags=["great_action", "exciting"],
                    rated_at=date(2024, 1, 1),
                )
            )

        # Create Horror movies the user dislikes
        for tmdb_id in range(201, 206):
            session.add(
                Title(
                    tmdb_id=tmdb_id,
                    title=f"Spooky Slasher {tmdb_id}",
                    original_title=f"Spooky Slasher {tmdb_id}",
                    original_language="en",
                    year=2021,
                    genres=["Horror"],
                    keywords=["slasher", "gore"],
                    vote_average=6.0,
                    vote_count=200,
                )
            )
            session.add(
                UserTitle(
                    user_id=1,
                    tmdb_id=tmdb_id,
                    source="app",
                    rating=3.0,
                    reaction="disliked",
                    tags=["not_scary"],
                    rated_at=date(2024, 1, 2),
                )
            )

        # Outlier 1: An Action movie the user DISLIKED (predicted like, user disliked)
        session.add(
            Title(
                tmdb_id=901,
                title="Boring Action Film",
                original_title="Boring Action Film",
                original_language="en",
                year=2023,
                genres=["Action", "Thriller"],
                keywords=["explosion"],
                vote_average=7.0,
                vote_count=300,
            )
        )
        session.add(
            UserTitle(
                user_id=1,
                tmdb_id=901,
                source="app",
                rating=3.0,
                reaction="disliked",
                tags=["too_slow"],
                rated_at=date(2024, 1, 3),
            )
        )

        # Outlier 2: A Horror movie the user LIKED (predicted dislike, user liked)
        session.add(
            Title(
                tmdb_id=902,
                title="Cheesy Creature Feature",
                original_title="Cheesy Creature Feature",
                original_language="en",
                year=2020,
                genres=["Horror"],
                keywords=["monster"],
                vote_average=5.5,
                vote_count=150,
            )
        )
        session.add(
            UserTitle(
                user_id=1,
                tmdb_id=902,
                source="imdb",
                rating=7.0,
                reaction="liked",
                tags=[],  # no tags!
                rated_at=date(2024, 1, 4),
            )
        )

        # Outlier 3: A movie marked "loved" with NO tags (loved_rewatch)
        session.add(
            Title(
                tmdb_id=903,
                title="Forgotten Drama",
                original_title="Forgotten Drama",
                original_language="fr",
                year=2018,
                genres=["Drama"],
                keywords=["mystery"],
                vote_average=6.5,
                vote_count=100,
            )
        )
        session.add(
            UserTitle(
                user_id=1,
                tmdb_id=903,
                source="letterboxd",
                rating=9.5,
                reaction="loved",
                tags=[],
                rated_at=date(2024, 1, 5),
            )
        )

        session.commit()


def test_ratings_include_match_percentage(client: TestClient) -> None:
    setup_taste_data(client)
    res = client.get("/api/v1/ratings")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] > 0
    items = data["items"]
    # Every rated film has a calculated match score
    matches = [item["match"] for item in items if item["match"] is not None]
    assert len(matches) > 0
    # An action movie should have high match
    action_item = next(item for item in items if item["tmdb_id"] == 101)
    assert action_item["match"] is not None
    assert action_item["match"] > 50


def test_outliers_endpoint(client: TestClient) -> None:
    setup_taste_data(client)
    res = client.get("/api/v1/ratings/outliers")
    assert res.status_code == 200
    outliers = res.json()
    assert len(outliers) > 0

    tmdb_ids = {o["tmdb_id"] for o in outliers}
    # Outliers should be detected
    assert 901 in tmdb_ids or 902 in tmdb_ids or 903 in tmdb_ids

    # Check structure
    for o in outliers:
        assert "tmdb_id" in o
        assert "predicted_match" in o
        assert "outlier_type" in o
        assert "liked_tags" in o
        assert "disliked_tags" in o
        assert len(o["liked_tags"]) > 0
        assert len(o["disliked_tags"]) > 0
