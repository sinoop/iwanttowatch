import httpx
import respx
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from iwanttowatch.llm import (
    CLAUDE_KEY_SETTING,
    OPENAI_KEY_SETTING,
    OPENAI_URL_SETTING,
    ClaudeProvider,
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
