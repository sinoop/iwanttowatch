import hashlib

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from iwanttowatch.api.mcp import KEY_SETTING as MCP_KEY_SETTING
from iwanttowatch.models import (
    Availability,
    LibraryItem,
    Recommendation,
    ShortlistItem,
    Title,
    set_setting,
)


def test_home_assistant_integration_session_and_bearer(client: TestClient) -> None:
    with Session(client.app.state.engine) as session:  # type: ignore[attr-defined]
        set_setting(session, MCP_KEY_SETTING, hashlib.sha256(b"ha-secret-key").hexdigest())
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
    assert len(data["high_rated_recommendations"]) == 1
    rec = data["high_rated_recommendations"][0]
    assert rec["tmdb_id"] == 301
    assert rec["match"] == 92
    assert rec["imdb_rating"] == 8.3
    assert rec["in_jellyfin"] is True
    assert rec["poster_url"] == "https://image.tmdb.org/t/p/w500/drishyam.jpg"

    assert len(data["shortlisted"]) == 1
    sl = data["shortlisted"][0]
    assert sl["tmdb_id"] == 302
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
