import json

import httpx
import respx
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from iwanttowatch.llm import (
    CLAUDE_KEY_SETTING,
    OLLAMA_WEB_SEARCH_URL,
    OPENAI_KEY_SETTING,
    OPENAI_URL_SETTING,
    ClaudeProvider,
    OllamaProvider,
    OpenAICompatibleProvider,
    llm_order,
    provider_from_settings,
)
from iwanttowatch.models import set_setting


def test_openai_compatible_and_claude_providers(mock: respx.MockRouter) -> None:
    mock.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"ok": true}'}}]},
        )
    )
    mock.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            200,
            json={"content": [{"type": "text", "text": '{"claude": "yes"}'}]},
        )
    )

    openai = OpenAICompatibleProvider(
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        model="gpt-4o-mini",
    )
    assert openai.generate("system", "hello") == '{"ok": true}'

    claude = ClaudeProvider(api_key="sk-ant-test", model="claude-3-5-haiku-latest")
    assert claude.generate("system", "hello") == '{"claude": "yes"}'


def test_llm_settings_endpoints_support_openai_and_claude(
    client: TestClient, mock: respx.MockRouter
) -> None:
    mock.post("https://api.groq.com/openai/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={"choices": [{"message": {"content": "OK"}}]},
        )
    )
    mock.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            200,
            json={"content": [{"type": "text", "text": "OK"}]},
        )
    )

    res_openai = client.put(
        "/api/v1/settings/llm",
        json={
            "provider": "openai",
            "openai_base_url": "https://api.groq.com/openai/v1",
            "openai_api_key": "gsk-test",
            "model": "llama-3.3-70b-versatile",
        },
    )
    assert res_openai.status_code == 200, res_openai.text
    llm_state = res_openai.json()["llm"]
    assert llm_state["openai_configured"] is True
    assert llm_state["openai_model"] == "llama-3.3-70b-versatile"
    assert "openai" in llm_state["order"]

    res_claude = client.put(
        "/api/v1/settings/llm",
        json={
            "provider": "claude",
            "claude_api_key": "sk-ant-test",
            "model": "claude-3-5-haiku-latest",
        },
    )
    assert res_claude.status_code == 200, res_claude.text
    llm_state = res_claude.json()["llm"]
    assert llm_state["claude_configured"] is True
    assert "claude" in llm_state["order"]

    with Session(client.app.state.engine) as session:  # type: ignore[attr-defined]
        assert llm_order(session) == ["openai", "claude"]
        provider = provider_from_settings(session, "test")
        assert provider is not None
        set_setting(session, OPENAI_URL_SETTING, "https://api.groq.com/openai/v1")
        set_setting(session, OPENAI_KEY_SETTING, "gsk-test")
        set_setting(session, CLAUDE_KEY_SETTING, "sk-ant-test")
        session.commit()


def test_ollama_web_search_with_ollama_api(mock: respx.MockRouter) -> None:
    chat_route = mock.post("http://ollama.local:11434/api/chat")
    chat_route.side_effect = [
        httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "web_search",
                                "arguments": {"query": "Empuraan 2025 director"},
                            }
                        }
                    ],
                }
            },
        ),
        httpx.Response(
            200,
            json={"message": {"role": "assistant", "content": "Directed by Prithviraj Sukumaran."}},
        ),
    ]
    search_route = mock.post(OLLAMA_WEB_SEARCH_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "L2: Empuraan",
                        "url": "https://example.com/empuraan",
                        "content": "L2: Empuraan is directed by Prithviraj Sukumaran.",
                    }
                ]
            },
        )
    )

    ollama = OllamaProvider(
        "http://ollama.local:11434",
        "gemma4",
        web_search_api_key="oll-secret-key",
    )
    reply = ollama.generate("You are a movie expert.", "Who directed Empuraan?")
    assert reply == "Directed by Prithviraj Sukumaran."
    assert search_route.called
    assert search_route.calls.last.request.headers["authorization"] == "Bearer oll-secret-key"
    assert json.loads(search_route.calls.last.request.content)["query"] == "Empuraan 2025 director"

    first_chat_body = json.loads(chat_route.calls[0].request.content)
    assert first_chat_body["tools"][0]["function"]["name"] == "web_search"
    second_chat_body = json.loads(chat_route.calls[1].request.content)
    assert second_chat_body["messages"][-1]["role"] == "tool"
    assert "Prithviraj Sukumaran" in second_chat_body["messages"][-1]["content"]


def test_ollama_web_search_searxng_and_fallback_and_json_reply(mock: respx.MockRouter) -> None:
    chat_route = mock.post("http://ollama.local:11434/api/chat")
    chat_route.side_effect = [
        # First generate() call: uses SearXNG directly
        httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "web_search",
                                "arguments": '{"query": "Bramayugam cast"}',
                            }
                        }
                    ],
                }
            },
        ),
        httpx.Response(
            200,
            json={"message": {"role": "assistant", "content": '{"lead": "Mammootty"}'}},
        ),
        # Second generate() call: SearXNG fails with 502, falls back to Ollama Web Search API
        httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "web_search",
                                "arguments": {"query": "Aavesham director"},
                            }
                        }
                    ],
                }
            },
        ),
        httpx.Response(
            200,
            json={"message": {"role": "assistant", "content": '{"director": "Jithu Madhavan"}'}},
        ),
    ]
    searxng_route = mock.get("http://searxng.local:8080/search")
    searxng_route.side_effect = [
        httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "Bramayugam",
                        "url": "https://example.com/bramayugam",
                        "content": "Stars Mammootty in the lead role.",
                    }
                ]
            },
        ),
        httpx.Response(502, text="Bad Gateway"),
    ]
    ollama_search_route = mock.post(OLLAMA_WEB_SEARCH_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "Aavesham",
                        "url": "https://example.com/aavesham",
                        "content": "Directed by Jithu Madhavan.",
                    }
                ]
            },
        )
    )

    ollama = OllamaProvider(
        "http://ollama.local:11434",
        "gemma4",
        web_search_api_key="oll-fallback-key",
        searxng_url="http://searxng.local:8080/",
    )

    first = ollama.generate("Return JSON.", "Who leads Bramayugam?", json_reply=True)
    assert json.loads(first) == {"lead": "Mammootty"}
    assert searxng_route.call_count == 1
    assert not ollama_search_route.called

    second = ollama.generate("Return JSON.", "Who directed Aavesham?", json_reply=True)
    assert json.loads(second) == {"director": "Jithu Madhavan"}
    assert searxng_route.call_count == 2
    assert ollama_search_route.call_count == 1


def test_ollama_web_search_settings_persistence_and_clearing(
    client: TestClient, mock: respx.MockRouter
) -> None:
    mock.post("http://ollama.local:11434/api/chat").mock(
        return_value=httpx.Response(200, json={"message": {"content": "OK"}})
    )
    res = client.put(
        "/api/v1/settings/llm",
        json={
            "provider": "ollama",
            "ollama_url": "http://ollama.local:11434",
            "model": "gemma4",
            "ollama_web_search_api_key": "oll-key-123",
            "ollama_searxng_url": "http://searxng.local:8080/",
        },
    )
    assert res.status_code == 200, res.text
    llm_state = res.json()["llm"]
    assert llm_state["ollama_web_search_configured"] is True
    assert llm_state["ollama_searxng_url"] == "http://searxng.local:8080"
    assert "oll-key-123" not in res.text

    res_clear = client.put(
        "/api/v1/settings/llm",
        json={
            "provider": "ollama",
            "ollama_url": "http://ollama.local:11434",
            "model": "gemma4",
            "clear_ollama_web_search_api_key": True,
            "ollama_searxng_url": "",
        },
    )
    assert res_clear.status_code == 200, res_clear.text
    cleared_state = res_clear.json()["llm"]
    assert cleared_state["ollama_web_search_configured"] is False
    assert cleared_state["ollama_searxng_url"] is None


def test_openrouter_auth_and_url_normalization(client: TestClient, mock: respx.MockRouter) -> None:
    mock.post("https://api.groq.com/openai/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={"choices": [{"message": {"content": "OK"}}]},
        )
    )
    openrouter_route = mock.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={"choices": [{"message": {"content": None, "reasoning": "OK"}}]},
        )
    )

    # First configure Groq with a gsk- key.
    res_groq = client.put(
        "/api/v1/settings/llm",
        json={
            "provider": "openai",
            "openai_base_url": "https://api.groq.com/openai/v1",
            "openai_api_key": "gsk-test",
            "model": "llama-3.3-70b-versatile",
        },
    )
    assert res_groq.status_code == 200

    # Switching Base URL to OpenRouter without entering a new key must not reuse the Groq key.
    res_missing_key = client.put(
        "/api/v1/settings/llm",
        json={
            "provider": "openai",
            "openai_base_url": "https://openrouter.ai/api/v1",
            "openai_api_key": None,
        },
    )
    assert res_missing_key.status_code == 400
    assert "OpenRouter API key" in res_missing_key.json()["detail"]

    # Entering a non-OpenRouter key for OpenRouter returns a clear message.
    res_wrong_key = client.put(
        "/api/v1/settings/llm",
        json={
            "provider": "openai",
            "openai_base_url": "https://openrouter.ai/api/v1",
            "openai_api_key": "gsk-wrong",
        },
    )
    assert res_wrong_key.status_code == 400
    assert "sk-or-" in res_wrong_key.json()["detail"]

    # Pasting 'Bearer "sk-or-v1-abc"' and a '/chat/completions' URL is normalized cleanly,
    # and leaving model blank defaults to 'openrouter/free'.
    res_ok = client.put(
        "/api/v1/settings/llm",
        json={
            "provider": "openai",
            "openai_base_url": "https://openrouter.ai/api/v1/chat/completions",
            "openai_api_key": 'Bearer "sk-or-v1-abc"',
            "model": "",
        },
    )
    assert res_ok.status_code == 200, res_ok.text
    assert openrouter_route.called
    assert openrouter_route.calls.last.request.headers["authorization"] == "Bearer sk-or-v1-abc"
    llm_state = res_ok.json()["llm"]
    assert llm_state["openai_base_url"] == "https://openrouter.ai/api/v1"
    assert llm_state["openai_model"] == "openrouter/free"
