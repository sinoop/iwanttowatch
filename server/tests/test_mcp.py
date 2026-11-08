import json
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from test_imports import KEY

from iwanttowatch.models import LibraryItem


def rpc(client: TestClient, key: str, method: str, params: dict[str, Any] | None = None) -> Any:
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert response.status_code == 200, response.text
    return response.json()["result"]


def tool(client: TestClient, key: str, name: str, **arguments: Any) -> Any:
    result = rpc(client, key, "tools/call", {"name": name, "arguments": arguments})
    assert not result.get("isError"), result
    return json.loads(result["content"][0]["text"])


def test_debug_mcp_server_explains_the_feed_to_key_holders(client: TestClient) -> None:
    client.put("/api/v1/settings/tmdb", json={"api_key": KEY})
    client.put("/api/v1/titles/101/reaction", json={"reaction": "loved"})
    with Session(client.app.state.engine) as session:  # type: ignore[attr-defined]
        session.add(LibraryItem(user_id=1, item_id="b" * 32, tmdb_id=302, name="D", year=2013))
        session.commit()
    client.put("/api/v1/me/streaming", json={"region": "IN", "subscriptions": [8]})
    client.app.state.feed_worker.wait_until_idle()  # type: ignore[attr-defined]

    hello = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    assert client.post("/mcp", json=hello).status_code == 401
    key = client.post("/api/v1/settings/mcp").json()["key"]
    assert client.get("/api/v1/settings").json()["mcp_enabled"] is True

    init = rpc(client, key, "initialize", {"protocolVersion": "2025-06-18"})
    assert init["protocolVersion"] == "2025-06-18" and "tools" in init["capabilities"]
    note = {"jsonrpc": "2.0", "method": "notifications/initialized"}
    auth = {"Authorization": f"Bearer {key}"}
    assert client.post("/mcp", json=note, headers=auth).status_code == 202
    names = {t["name"] for t in rpc(client, key, "tools/list")["tools"]}
    assert {"feed", "explain_title", "llm_calls"} <= names

    # The feed as the user sees it: Kumbalangi Nights on Netflix, Drishyam on Jellyfin.
    shown = tool(client, key, "feed", user="Riya Menon")
    assert {i["tmdb_id"] for i in shown["items"]} == {201, 302}
    everything = tool(client, key, "feed", user="riya", include_hidden=True)
    hidden = {i["tmdb_id"]: i.get("hidden_because") for i in everything["items"]}
    assert hidden[201] is None
    assert hidden[301] == ["not on Jellyfin or a subscribed service"]

    loved = tool(client, key, "explain_title", user="1", tmdb_id=101)
    assert loved["verdict"].startswith("Not in the stored feed")
    assert [(s["source"], s["reaction"]) for s in loved["user_sources"]] == [("app", "loved")]
    remake = tool(client, key, "explain_title", user="riya", tmdb_id=301)
    assert "hidden: not on Jellyfin" in remake["verdict"]
    assert remake["availability"]["offers"] == [
        "Amazon Prime Video (flatrate)", "JioHotstar (flatrate)", "Apple TV (rent)",
    ]  # fmt: skip
    assert [f["tmdb_id"] for f in tool(client, key, "find_title", query="premam")] == [401, 402]

    missing = rpc(client, key, "tools/call", {"name": "feed", "arguments": {"user": "nobody"}})
    assert missing["isError"] and "Users: riya" in missing["content"][0]["text"]

    # A new key replaces the old one, and removing it turns the server off.
    newer = client.post("/api/v1/settings/mcp").json()["key"]
    assert client.post("/mcp", json=hello, headers=auth).status_code == 401
    client.delete("/api/v1/settings/mcp")
    assert (
        client.post("/mcp", json=hello, headers={"Authorization": f"Bearer {newer}"}).status_code
        == 401
    )
