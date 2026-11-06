"""Optional text generation through a local Ollama server or the Google Gemini API.

Nothing in iWantToWatch requires an LLM; features that use one are skipped when
none is configured.
"""

from typing import Any, Protocol

import httpx
from sqlalchemy.orm import Session

from iwanttowatch.models import get_setting

PROVIDER_SETTING = "llm_provider"  # "ollama" or "gemini"; absent means none
MODEL_SETTING = "llm_model"
OLLAMA_URL_SETTING = "ollama_url"
GEMINI_KEY_SETTING = "gemini_api_key"

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
# An alias Google moves to its current Flash model, so the default survives renames.
DEFAULT_GEMINI_MODEL = "gemini-flash-latest"
# Small CPU models on a home server can take a while.
TIMEOUT_SECONDS = 180


class LlmError(Exception):
    pass


class LlmProvider(Protocol):
    def generate(self, system: str, prompt: str) -> str: ...


class OllamaProvider:
    def __init__(self, base_url: str, model: str) -> None:
        self._http = httpx.Client(base_url=base_url.rstrip("/"), timeout=TIMEOUT_SECONDS)
        self._model = model

    def generate(self, system: str, prompt: str) -> str:
        body = {
            "model": self._model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }
        data = _post(self._http, "/api/chat", body, "Ollama")
        return str(data.get("message", {}).get("content", "")).strip()


class GeminiProvider:
    def __init__(self, api_key: str, model: str, base_url: str = GEMINI_BASE_URL) -> None:
        self._http = httpx.Client(
            base_url=base_url, timeout=TIMEOUT_SECONDS, headers={"x-goog-api-key": api_key}
        )
        self._model = model

    def generate(self, system: str, prompt: str) -> str:
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        }
        data = _post(self._http, f"/models/{self._model}:generateContent", body, "Gemini")
        candidates = data.get("candidates") or []
        parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
        return "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()


def _post(http: httpx.Client, path: str, body: dict[str, Any], name: str) -> dict[str, Any]:
    try:
        response = http.post(path, json=body)
    except httpx.TransportError as error:
        raise LlmError(f"Couldn't reach {name}: {error}") from error
    if response.status_code >= 400:
        try:
            detail = response.json().get("error")
            detail = detail.get("message") if isinstance(detail, dict) else detail
        except ValueError:
            detail = None
        raise LlmError(
            f"{name} returned HTTP {response.status_code}: {detail or response.text[:200]}"
        )
    result: dict[str, Any] = response.json()
    return result


def make_provider(
    provider: str, model: str, ollama_url: str | None, gemini_api_key: str | None
) -> LlmProvider:
    if provider == "ollama" and ollama_url:
        return OllamaProvider(ollama_url, model)
    if provider == "gemini" and gemini_api_key:
        return GeminiProvider(gemini_api_key, model)
    raise LlmError(f"{provider} is not fully configured")


def provider_from_settings(session: Session) -> LlmProvider | None:
    """The LLM chosen in Settings, or None when no LLM is configured."""
    provider = get_setting(session, PROVIDER_SETTING)
    if provider is None:
        return None
    return make_provider(
        provider,
        get_setting(session, MODEL_SETTING) or "",
        get_setting(session, OLLAMA_URL_SETTING),
        get_setting(session, GEMINI_KEY_SETTING),
    )
