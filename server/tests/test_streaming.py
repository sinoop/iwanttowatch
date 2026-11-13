from datetime import timedelta
from typing import Any

import respx
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.orm import Session
from test_imports import KEY

from iwanttowatch.db import utcnow
from iwanttowatch.models import Availability, LibraryItem, set_setting
from iwanttowatch.tmdb import API_KEY_SETTING


def availability(client: TestClient, *ids: int) -> dict[int, dict[str, Any]]:
    response = client.get("/api/v1/availability", params={"ids": list(ids)})
    assert response.status_code == 200, response.text
    return {a["tmdb_id"]: a for a in response.json()}


def names(entry: dict[str, Any]) -> list[str]:
    return [offer["name"] for offer in entry["offers"]]


def watch_requests(mock: respx.MockRouter) -> int:
    return sum(call.request.url.path.endswith("/watch/providers") for call in mock.calls)


def test_badges_show_only_what_each_person_can_play_in_their_region(
    client: TestClient, mock: respx.MockRouter
) -> None:
    assert client.put("/api/v1/settings/tmdb", json={"api_key": KEY}).status_code == 200
    regions = client.get("/api/v1/streaming/regions").json()
    assert {"code": "IN", "name": "India"} in regions
    services = client.get("/api/v1/streaming/providers").json()
    assert [s["name"] for s in services][:3] == ["JioHotstar", "Amazon Prime Video", "Netflix"]

    me = client.put("/api/v1/me/streaming", json={"region": "IN", "subscriptions": [8, 2336]})
    assert me.json()["subscriptions"] == [8, 2336]
    engine = client.app.state.engine  # type: ignore[attr-defined]
    with Session(engine) as session:
        session.add(LibraryItem(user_id=1, item_id="a" * 32, tmdb_id=101, name="Léon", year=1994))
        session.commit()

    found = availability(client, 301, 201, 101, 999)
    # Prime isn't subscribed and renting doesn't count; JioHotstar is subscribed.
    assert names(found[301]) == ["JioHotstar"]
    assert found[301]["link"] == "https://www.themoviedb.org/movie/301/watch?locale=IN"
    assert names(found[201]) == ["Netflix"]
    # On Netflix only in the US; in India it's free with ads on MX Player, or to buy.
    assert found[101]["on_jellyfin"] is True
    assert found[101]["offers"] == [{"provider_id": 515, "name": "MX Player",
                                     "logo_path": "/mx.jpg", "kind": "ads"}]  # fmt: skip
    assert found[999] == {
        "tmdb_id": 999,
        "on_jellyfin": False,
        "offers": [],
        "other_offers": [],
        "link": None,
        "checked_at": found[999]["checked_at"],
        "stale": False,
    }
    assert found[201]["on_jellyfin"] is False

    # Checks are cached per region.
    before = watch_requests(mock)
    availability(client, 301, 201, 101)
    assert watch_requests(mock) == before
    # Changing country rechecks in the new one. (The feed build it starts checks offers
    # too, so let it finish before counting requests.)
    client.put("/api/v1/me/streaming", json={"region": "US", "subscriptions": [8]})
    client.app.state.feed_worker.wait_until_idle()  # type: ignore[attr-defined]
    assert names(availability(client, 101)[101]) == ["Netflix"]
    before = watch_requests(mock)
    availability(client, 101)
    assert watch_requests(mock) == before

    # After three days titles are rechecked; if TMDb fails, the old offers stay, marked stale.
    with Session(engine) as session:
        session.execute(update(Availability).values(checked_at=utcnow() - timedelta(days=4)))
        set_setting(session, API_KEY_SETTING, "revoked-key-0123456789")
        session.commit()
    stale = availability(client, 101)[101]
    assert names(stale) == ["Netflix"] and stale["stale"] is True


def test_details_list_what_the_user_cant_play_yet(client: TestClient) -> None:
    assert client.put("/api/v1/settings/tmdb", json={"api_key": KEY}).status_code == 200
    client.put("/api/v1/me/streaming", json={"region": "IN", "subscriptions": [8]})
    client.app.state.feed_worker.wait_until_idle()  # type: ignore[attr-defined]

    # Drishyam is on Prime and JioHotstar, which the user doesn't have, and to rent on Apple.
    where = client.get("/api/v1/titles/301").json()["availability"]
    assert where["offers"] == []
    assert [(o["name"], o["kind"]) for o in where["other_offers"]] == [
        ("Amazon Prime Video", "flatrate"), ("JioHotstar", "flatrate"), ("Apple TV", "rent"),
    ]  # fmt: skip
    # Lists stay light: only a film's details carry them.
    assert availability(client, 301)[301]["other_offers"] == []
    # What can be played now isn't repeated.
    assert client.get("/api/v1/titles/201").json()["availability"]["other_offers"] == []


def test_streaming_settings_show_rent_buy_preference(client: TestClient) -> None:
    me = client.get("/api/v1/me").json()
    assert me["show_rent_buy"] is False

    updated = client.put(
        "/api/v1/me/streaming",
        json={"region": "IN", "subscriptions": [8], "show_rent_buy": True},
    ).json()
    assert updated["show_rent_buy"] is True

    # Persists on me
    assert client.get("/api/v1/me").json()["show_rent_buy"] is True

    # Can be turned back off
    off = client.put(
        "/api/v1/me/streaming",
        json={"region": "IN", "subscriptions": [8], "show_rent_buy": False},
    ).json()
    assert off["show_rent_buy"] is False


def test_shown_for_unavailable_only() -> None:
    from iwanttowatch.api.streaming import Offer, TitleAvailability, shown_for

    avail_jellyfin = TitleAvailability(
        tmdb_id=1, on_jellyfin=True, offers=[], link=None, checked_at=None, stale=False
    )
    avail_subscription = TitleAvailability(
        tmdb_id=2,
        on_jellyfin=False,
        offers=[Offer(provider_id=8, name="Netflix", logo_path=None, kind="flatrate")],
        link=None,
        checked_at=None,
        stale=False,
    )
    avail_free = TitleAvailability(
        tmdb_id=3,
        on_jellyfin=False,
        offers=[Offer(provider_id=515, name="MX Player", logo_path=None, kind="ads")],
        link=None,
        checked_at=None,
        stale=False,
    )
    avail_none = TitleAvailability(
        tmdb_id=4, on_jellyfin=False, offers=[], link=None, checked_at=None, stale=False
    )

    # When available_only=True: only Jellyfin and subscriptions are shown
    assert shown_for(avail_jellyfin, available_only=True, platforms=[]) is True
    assert shown_for(avail_subscription, available_only=True, platforms=[]) is True
    assert shown_for(avail_free, available_only=True, platforms=[]) is False
    assert shown_for(avail_none, available_only=True, platforms=[]) is False

    # When unavailable_only=True: Jellyfin and subscriptions are excluded, free and none are included
    assert (
        shown_for(avail_jellyfin, available_only=False, platforms=[], unavailable_only=True)
        is False
    )
    assert (
        shown_for(avail_subscription, available_only=False, platforms=[], unavailable_only=True)
        is False
    )
    assert shown_for(avail_free, available_only=False, platforms=[], unavailable_only=True) is True
    assert shown_for(avail_none, available_only=False, platforms=[], unavailable_only=True) is True

    # When available_only=False and unavailable_only=False: everything is shown
    assert (
        shown_for(avail_jellyfin, available_only=False, platforms=[], unavailable_only=False)
        is True
    )
    assert (
        shown_for(avail_subscription, available_only=False, platforms=[], unavailable_only=False)
        is True
    )
    assert shown_for(avail_free, available_only=False, platforms=[], unavailable_only=False) is True
    assert shown_for(avail_none, available_only=False, platforms=[], unavailable_only=False) is True
