from datetime import date
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_imports import KEY

from iwanttowatch.feed import user_labels
from iwanttowatch.models import Title, UserTitle
from iwanttowatch.tags import TAGS
from iwanttowatch.taste import refresh_reaction_ratings, taste_summary


def add_title(
    client: TestClient, tmdb_id: int, genres: list[str], keywords: tuple[str, ...] = ()
) -> None:
    with Session(client.app.state.engine) as session:  # type: ignore[attr-defined]
        session.add(
            Title(tmdb_id=tmdb_id, title=f"Film {tmdb_id}", original_title=f"Film {tmdb_id}",
                  original_language="en", year=2020, genres=genres, keywords=list(keywords))
        )  # fmt: skip
        session.commit()


def react(client: TestClient, tmdb_id: int, reaction: str, tags: list[str]) -> Any:
    return client.put(
        f"/api/v1/titles/{tmdb_id}/reaction", json={"reaction": reaction, "tags": tags}
    )


def test_reaction_and_tags_feed_ratings_and_the_persona_summary(client: TestClient) -> None:
    assert client.put("/api/v1/settings/tmdb", json={"api_key": KEY}).status_code == 200

    # Premam isn't in the catalogue yet, so rating it fetches it from TMDb.
    loved = react(client, 401, "loved", ["moved_me", "great_story"])
    assert loved.status_code == 200, loved.text
    assert loved.json()["reaction"] == "loved" and loved.json()["title"] == "Premam"
    [item] = client.get("/api/v1/ratings").json()["items"]
    assert (item["reaction"], item["tags"], item["rating"], item["source"]) == (
        "loved", ["moved_me", "great_story"], 9.5, "app"
    )  # fmt: skip

    assert react(client, 401, "disliked", ["moved_me"]).status_code == 400  # a "liked" tag
    assert react(client, 401, "loved", ["not_a_tag"]).status_code == 400
    four = ["moved_me", "great_story", "great_acting", "great_music"]
    assert react(client, 401, "loved", four).status_code == 422

    disliked = client.put(
        "/api/v1/titles/401/reaction",
        json={"reaction": "disliked", "tags": ["too_slow"], "note": "  Second half\n dragged "},
    )
    assert disliked.json()["note"] == "Second half\n dragged"
    assert client.get("/api/v1/titles/401/reaction").json()["note"] == "Second half\n dragged"
    [item] = client.get("/api/v1/ratings").json()["items"]
    assert (item["reaction"], item["rating"]) == ("disliked", 3.0)
    with Session(client.app.state.engine) as session:  # type: ignore[attr-defined]
        summary = taste_summary(session, 1)
    assert "What puts them off, in their own words: too slow (1 films)" in summary
    assert "Premam / പ്രേമം (2015, ml): didn't like (too slow)" in summary
    assert (
        'Their notes on recent films: Premam (2015, didn\'t like): "Second half dragged"' in summary
    )
    assert react(client, 401, "disliked", ["too_slow"]).json()["note"] is None  # blank clears it

    assert client.delete("/api/v1/titles/401/reaction").status_code == 204
    assert client.get("/api/v1/ratings").json()["total"] == 0


def test_reaction_scores_follow_the_users_own_rating_scale(client: TestClient) -> None:
    # Stable 3-point scores: in-app reactions keep distinct scores and never collide.
    scores = [4, 5, 6, 6, 7, 8, 8, 9, 9, 10]
    with Session(client.app.state.engine) as session:  # type: ignore[attr-defined]
        for i, score in enumerate(scores):
            session.add(
                Title(
                    tmdb_id=100 + i, title=f"T{i}", original_title=f"T{i}", original_language="en"
                )
            )
            session.add(
                UserTitle(
                    user_id=1,
                    tmdb_id=100 + i,
                    source="imdb",
                    rating=score,
                    rated_at=date(2020, 1, 1),
                )
            )
        session.commit()
        # Backfill reaction for the imported ratings.
        assert refresh_reaction_ratings(session, 1) == 10
        session.commit()

    # Imported ratings map to 3-point reactions:
    with Session(client.app.state.engine) as session:  # type: ignore[attr-defined]
        ut = {e.tmdb_id: e.reaction for e in session.scalars(select(UserTitle)).all()}
    assert ut[109] == "loved"  # score 10
    assert ut[108] == "loved"  # score 9
    assert ut[105] == "liked"  # score 8
    assert ut[100] == "disliked"  # score 4

    add_title(client, 500, ["Drama"])
    expected = {"disliked": 3.0, "liked": 8.0, "loved": 9.5}
    for reaction, expected_score in expected.items():
        assert react(client, 500, reaction, []).status_code == 200
        rated = {i["tmdb_id"]: i for i in client.get("/api/v1/ratings").json()["items"]}
        assert rated[500]["rating"] == expected_score, reaction


def test_every_film_offers_the_same_core_tags_then_suggestions_that_fit_it(
    client: TestClient,
) -> None:
    add_title(client, 600, ["Thriller", "Crime"], ("twist ending",))
    add_title(client, 601, ["Comedy", "Romance"])

    def groups(film: dict[str, Any], side: str) -> dict[str, list[str]]:
        found: dict[str, list[str]] = {"core": [], "suggested": [], "more": []}
        for tag in film[side]:
            found[tag["group"]].append(tag["id"])
        return found

    thriller = groups(client.get("/api/v1/titles/600/reaction").json(), "liked_tags")
    comedy = groups(client.get("/api/v1/titles/601/reaction").json(), "liked_tags")
    assert thriller["core"] == comedy["core"]  # same tags, same order
    assert thriller["core"][:3] == ["great_story", "great_acting", "great_direction"]
    assert thriller["suggested"][0] == "clever_twist"  # keyword match ranks first
    assert len(thriller["suggested"]) == 3 and "great_villain" in thriller["suggested"]
    assert "lovely_romance" in comedy["suggested"] and "genuinely_scary" in comedy["more"]
    # Every positive tag is offered exactly once, so any of them can be picked.
    every = thriller["core"] + thriller["suggested"] + thriller["more"]
    assert sorted(every) == sorted(t.id for t in TAGS if t.positive)

    disliked = groups(client.get("/api/v1/titles/601/reaction").json(), "disliked_tags")
    assert "not_funny" in disliked["suggested"] and "not_scary" in disliked["more"]


def add_imported(client: TestClient, scores: list[float], first_id: int = 100) -> None:
    with Session(client.app.state.engine) as session:  # type: ignore[attr-defined]
        for i, score in enumerate(scores):
            tmdb_id = first_id + i
            session.add(
                Title(
                    tmdb_id=tmdb_id, title=f"T{i}", original_title=f"T{i}", original_language="en"
                )
            )
            session.add(
                UserTitle(
                    user_id=1, tmdb_id=tmdb_id, source="imdb", rating=score,
                    rated_at=date(2020, 1, 1),
                )
            )  # fmt: skip
        session.commit()


def test_earlier_reactions_follow_ratings_imported_afterwards(client: TestClient) -> None:
    add_title(client, 500, ["Drama"])
    assert react(client, 500, "liked", []).status_code == 200
    assert client.get("/api/v1/ratings").json()["items"][0]["rating"] == 8.0  # the default

    # Imported ratings without reactions get backfilled by refresh_reaction_ratings:
    add_imported(client, [3, 4, 4, 5, 5, 6, 6, 7, 7, 8])
    with Session(client.app.state.engine) as session:  # type: ignore[attr-defined]
        assert refresh_reaction_ratings(session, 1) == 10
        session.commit()
        assert refresh_reaction_ratings(session, 1) == 0  # nothing left to change
    rated = {i["tmdb_id"]: i for i in client.get("/api/v1/ratings").json()["items"]}
    assert rated[500]["rating"] == 8.0 and rated[500]["reaction"] == "liked"


def test_reactions_do_not_join_the_pool_they_are_scored_against(client: TestClient) -> None:
    add_imported(client, [4, 5, 6, 6, 7, 8, 8, 9, 9, 10])
    with Session(client.app.state.engine) as session:  # type: ignore[attr-defined]
        before = {label.tmdb_id: label.value for label in user_labels(session, 1)}
    for tmdb_id in range(500, 520):
        add_title(client, tmdb_id, ["Drama"])
        assert react(client, tmdb_id, "liked", []).status_code == 200
    with Session(client.app.state.engine) as session:  # type: ignore[attr-defined]
        after = {label.tmdb_id: label.value for label in user_labels(session, 1)}
    # Twenty "liked" films add no ties to the imported ratings' scale...
    assert all(after[i] == before[i] for i in before)
    # ...and each receives the discrete liked label weight (0.70).
    assert all(after[i] == 0.70 for i in range(500, 520))


def test_ratings_filtering_and_sorting(client: TestClient) -> None:
    with Session(client.app.state.engine) as session:  # type: ignore[attr-defined]
        session.add(
            Title(
                tmdb_id=601,
                title="Inception",
                original_title="Inception",
                original_language="en",
                year=2010,
                genres=["Action", "Sci-Fi"],
                directors=[{"id": 1, "name": "Christopher Nolan"}],
                cast=[{"id": 2, "name": "Leonardo DiCaprio"}],
            )
        )
        session.add(
            Title(
                tmdb_id=602,
                title="Parasite",
                original_title="Gisaengchung",
                original_language="ko",
                year=2019,
                genres=["Thriller", "Drama"],
                directors=[{"id": 3, "name": "Bong Joon-ho"}],
                cast=[{"id": 4, "name": "Song Kang-ho"}],
            )
        )
        session.add(
            Title(
                tmdb_id=603,
                title="The Room",
                original_title="The Room",
                original_language="en",
                year=2003,
                genres=["Drama"],
                directors=[{"id": 5, "name": "Tommy Wiseau"}],
                cast=[{"id": 5, "name": "Tommy Wiseau"}],
            )
        )
        session.add(
            Title(
                tmdb_id=604,
                title="Spirited Away",
                original_title="Sen to Chihiro no Kamikakushi",
                original_language="ja",
                year=2001,
                genres=["Animation", "Fantasy"],
                directors=[{"id": 6, "name": "Hayao Miyazaki"}],
                cast=[],
            )
        )
        session.commit()

    # Rate them
    client.put(
        "/api/v1/titles/601/reaction",
        json={"reaction": "loved", "tags": ["mind_bending"], "note": "Masterpiece"},
    )
    client.put(
        "/api/v1/titles/602/reaction",
        json={"reaction": "loved", "tags": ["clever_twist"]},
    )
    client.put(
        "/api/v1/titles/603/reaction",
        json={"reaction": "disliked", "tags": ["unconvincing_acting"], "note": "Hilariously bad"},
    )
    client.put(
        "/api/v1/titles/604/reaction",
        json={"reaction": "liked", "tags": ["beautiful_visuals"]},
    )

    # 1. Unfiltered page & facets
    res = client.get("/api/v1/ratings").json()
    assert res["total"] == 4
    assert res["total_unfiltered"] == 4
    assert set(res["genres"]) >= {"Action", "Sci-Fi", "Thriller", "Drama", "Animation", "Fantasy"}
    assert set(res["decades"]) == {2010, 2000}
    assert res["reactions"] == {"loved": 2, "disliked": 1, "liked": 1}
    assert res["has_notes_count"] == 2
    assert set(res["tags"]) >= {
        "mind_bending",
        "clever_twist",
        "unconvincing_acting",
        "beautiful_visuals",
    }
    lang_map = {item["language"]: item["count"] for item in res["languages"]}
    assert lang_map["en"] == 2 and lang_map["ko"] == 1 and lang_map["ja"] == 1

    # 2. Text search (English title or original title)
    assert [
        i["tmdb_id"]
        for i in client.get("/api/v1/ratings", params={"query": "incept"}).json()["items"]
    ] == [601]
    assert [
        i["tmdb_id"]
        for i in client.get("/api/v1/ratings", params={"query": "kamikakushi"}).json()["items"]
    ] == [604]

    # 3. Filter by reaction
    loved = client.get("/api/v1/ratings", params={"reaction": "loved"}).json()
    assert loved["total"] == 2
    assert {i["tmdb_id"] for i in loved["items"]} == {601, 602}

    disliked = client.get("/api/v1/ratings", params={"reaction": "disliked"}).json()
    assert disliked["total"] == 1
    assert disliked["items"][0]["tmdb_id"] == 603

    # 4. Filter by language
    ko = client.get("/api/v1/ratings", params={"language": "ko"}).json()
    assert [i["tmdb_id"] for i in ko["items"]] == [602]

    # 5. Filter by genre
    scifi = client.get("/api/v1/ratings", params={"genre": "Sci-Fi"}).json()
    assert [i["tmdb_id"] for i in scifi["items"]] == [601]

    # 6. Filter by person (director or cast)
    nolan = client.get("/api/v1/ratings", params={"person": "nolan"}).json()
    assert [i["tmdb_id"] for i in nolan["items"]] == [601]

    song = client.get("/api/v1/ratings", params={"person": "song kang"}).json()
    assert [i["tmdb_id"] for i in song["items"]] == [602]

    # 7. Filter by tag
    twist = client.get("/api/v1/ratings", params={"tag": "clever_twist"}).json()
    assert [i["tmdb_id"] for i in twist["items"]] == [602]

    # 8. Filter by decade
    d2000s = client.get("/api/v1/ratings", params={"decade": 2000}).json()
    assert {i["tmdb_id"] for i in d2000s["items"]} == {603, 604}

    # 9. Filter by has_note
    notes = client.get("/api/v1/ratings", params={"has_note": True}).json()
    assert {i["tmdb_id"] for i in notes["items"]} == {601, 603}
    assert any(i["note"] == "Masterpiece" for i in notes["items"])

    # 10. Sorting
    by_react = client.get("/api/v1/ratings", params={"sort": "reaction"}).json()
    react_ids = [i["tmdb_id"] for i in by_react["items"]]
    assert react_ids[0] in {601, 602} and react_ids[1] in {601, 602}
    assert react_ids[2] == 604  # liked
    assert react_ids[3] == 603  # disliked

    by_year_desc = client.get("/api/v1/ratings", params={"sort": "year_desc"}).json()
    assert [i["tmdb_id"] for i in by_year_desc["items"]] == [602, 601, 603, 604]

    by_year_asc = client.get("/api/v1/ratings", params={"sort": "year_asc"}).json()
    assert [i["tmdb_id"] for i in by_year_asc["items"]] == [604, 603, 601, 602]

    by_title = client.get("/api/v1/ratings", params={"sort": "title_asc"}).json()
    assert [i["tmdb_id"] for i in by_title["items"]] == [601, 602, 604, 603]
