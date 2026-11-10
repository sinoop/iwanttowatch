from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from test_imports import KEY

from iwanttowatch.models import Availability, LibraryItem, Title, UserTitle


def test_person_details_affinity_and_filmography(client: TestClient) -> None:
    client.put("/api/v1/settings/tmdb", json={"api_key": KEY})
    # Set subscriptions to Netflix (8)
    client.put("/api/v1/me/streaming", json={"region": "IN", "subscriptions": [8]})

    with Session(client.app.state.engine) as session:  # type: ignore[attr-defined]
        # Seed titles
        session.add_all(
            [
                Title(
                    tmdb_id=157336,
                    title="Interstellar",
                    original_title="Interstellar",
                    original_language="en",
                    year=2014,
                    directors=[{"id": 525, "name": "Christopher Nolan"}],
                ),
                Title(
                    tmdb_id=27205,
                    title="Inception",
                    original_title="Inception",
                    original_language="en",
                    year=2010,
                    directors=[{"id": 525, "name": "Christopher Nolan"}],
                ),
                Title(
                    tmdb_id=77,
                    title="Memento",
                    original_title="Memento",
                    original_language="en",
                    year=2000,
                    directors=[{"id": 525, "name": "Christopher Nolan"}],
                ),
            ]
        )
        # Seed user ratings: Interstellar loved (9.5), Inception rated 8.0, Memento in Jellyfin library
        session.add(
            UserTitle(
                user_id=1,
                tmdb_id=157336,
                source="app",
                reaction="loved",
                rating=9.5,
                watched=True,
            )
        )
        session.add(
            UserTitle(
                user_id=1,
                tmdb_id=27205,
                source="imdb",
                rating=8.0,
                watched=True,
            )
        )
        session.add(
            LibraryItem(
                user_id=1,
                item_id="jellyfin-memento-item",
                tmdb_id=77,
                name="Memento",
                year=2000,
            )
        )
        # Seed streaming availability: Interstellar on Netflix (8) in IN
        session.add(
            Availability(
                tmdb_id=157336,
                region="IN",
                offers=[{"provider_id": 8, "name": "Netflix", "kind": "flatrate"}],
            )
        )
        session.commit()

    res = client.get("/api/v1/people/525")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["id"] == 525
    assert body["name"] == "Christopher Nolan"
    assert body["is_favorite"] is False

    # Check affinity
    affinity = body["affinity"]
    assert affinity["rated_count"] == 2
    assert affinity["average_rating"] == 8.8  # (9.5 + 8.0) / 2 = 8.75 -> 8.8
    assert affinity["loved_count"] == 1
    assert affinity["liked_count"] == 1
    assert affinity["disliked_count"] == 0
    assert len(affinity["rated_films"]) == 2

    # Check filmography
    films = {f["tmdb_id"]: f for f in body["filmography"]}
    assert len(films) == 3
    # Interstellar
    assert films[157336]["user_rating"] == 9.5
    assert films[157336]["user_reaction"] == "loved"
    assert films[157336]["watched"] is True
    assert films[157336]["streaming_services"] == ["Netflix"]
    # Inception
    assert films[27205]["user_rating"] == 8.0
    assert films[27205]["watched"] is True
    # Memento
    assert films[77]["in_library"] is True
    assert films[77]["watched"] is False


def test_favorite_person_crud(client: TestClient) -> None:
    client.put("/api/v1/settings/tmdb", json={"api_key": KEY})

    # Initial favorites list is empty
    assert client.get("/api/v1/people/favorites").json() == []

    # Add favorite
    put_res = client.put(
        "/api/v1/people/287/favorite",
        json={"name": "Brad Pitt", "role": "Acting", "profile_path": "/pitt.jpg"},
    )
    assert put_res.status_code == 200
    assert put_res.json() == {"ok": True, "is_favorite": True}

    # Verify favorites endpoint
    favs = client.get("/api/v1/people/favorites").json()
    assert len(favs) == 1
    assert favs[0]["person_id"] == 287
    assert favs[0]["name"] == "Brad Pitt"

    # Verify is_favorite flag in get_person
    person_res = client.get("/api/v1/people/287")
    assert person_res.status_code == 200, person_res.text
    person = person_res.json()
    assert person["is_favorite"] is True

    # Remove favorite
    del_res = client.delete("/api/v1/people/287/favorite")
    assert del_res.status_code == 200
    assert del_res.json() == {"ok": True, "is_favorite": False}
    assert client.get("/api/v1/people/favorites").json() == []


def test_person_not_found(client: TestClient) -> None:
    client.put("/api/v1/settings/tmdb", json={"api_key": KEY})
    res = client.get("/api/v1/people/999999")
    assert res.status_code == 404


def test_favorite_person_reasons_in_feed_scoring(client: TestClient) -> None:
    client.put("/api/v1/settings/tmdb", json={"api_key": KEY})
    # Favorite Christopher Nolan
    client.put(
        "/api/v1/people/525/favorite",
        json={"name": "Christopher Nolan", "role": "Directing"},
    )

    with Session(client.app.state.engine) as session:  # type: ignore[attr-defined]
        session.add_all(
            [
                Title(
                    tmdb_id=157336,
                    title="Interstellar",
                    original_title="Interstellar",
                    original_language="en",
                    year=2014,
                    directors=[{"id": 525, "name": "Christopher Nolan"}],
                ),
                Title(
                    tmdb_id=27205,
                    title="Inception",
                    original_title="Inception",
                    original_language="en",
                    year=2010,
                    directors=[{"id": 525, "name": "Christopher Nolan"}],
                ),
            ]
        )
        # Rate Interstellar
        session.add(
            UserTitle(
                user_id=1,
                tmdb_id=157336,
                source="app",
                rating=9.0,
                watched=True,
            )
        )
        session.commit()

    # Get title details for Inception (which is unwatched)
    res = client.get("/api/v1/titles/27205")
    assert res.status_code == 200, res.text
    detail = res.json()
    assert any("your favourite Christopher Nolan" in r for r in detail["reasons"])


def test_people_taste_overview(client: TestClient) -> None:
    client.put("/api/v1/settings/tmdb", json={"api_key": KEY})
    # Favorite Christopher Nolan
    client.put(
        "/api/v1/people/525/favorite",
        json={"name": "Christopher Nolan", "role": "Directing"},
    )

    with Session(client.app.state.engine) as session:  # type: ignore[attr-defined]
        session.add_all(
            [
                Title(
                    tmdb_id=157336,
                    title="Interstellar",
                    original_title="Interstellar",
                    original_language="en",
                    year=2014,
                    directors=[{"id": 525, "name": "Christopher Nolan"}],
                    cast=[{"id": 10297, "name": "Matthew McConaughey"}],
                ),
                Title(
                    tmdb_id=27205,
                    title="Inception",
                    original_title="Inception",
                    original_language="en",
                    year=2010,
                    directors=[{"id": 525, "name": "Christopher Nolan"}],
                    cast=[{"id": 6193, "name": "Leonardo DiCaprio"}],
                ),
            ]
        )
        # Rate both films
        session.add(
            UserTitle(
                user_id=1,
                tmdb_id=157336,
                source="app",
                reaction="loved",
                rating=9.5,
                watched=True,
            )
        )
        session.add(
            UserTitle(
                user_id=1,
                tmdb_id=27205,
                source="app",
                reaction="liked",
                rating=8.5,
                watched=True,
            )
        )
        session.commit()

    res = client.get("/api/v1/people/taste")
    assert res.status_code == 200, res.text
    overview = res.json()
    assert len(overview["favorites"]) == 1
    assert overview["favorites"][0]["name"] == "Christopher Nolan"

    # Christopher Nolan directed 2 films (>= 2 threshold), so he appears in top_directors!
    assert len(overview["top_directors"]) == 1
    dir_info = overview["top_directors"][0]
    assert dir_info["id"] == 525
    assert dir_info["name"] == "Christopher Nolan"
    assert dir_info["rated_count"] == 2
    assert dir_info["average_rating"] == 9.0  # (9.5 + 8.5) / 2 = 9.0
    assert dir_info["loved_count"] == 1
    assert dir_info["liked_count"] == 1
    assert dir_info["is_favorite"] is True
