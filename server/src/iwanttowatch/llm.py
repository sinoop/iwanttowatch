"""Optional text generation through a local Ollama server or the Google Gemini API.

Nothing in iWantToWatch requires an LLM; features that use one are skipped when
none is configured. With both set up, the admin's order decides which is asked
first; the other answers when it fails, say at Gemini's daily limit or with Ollama
switched off. Every call is logged, with its prompt and reply, so an admin can
see in Settings how often it's called and what it was sent.
"""

import logging
import time
from datetime import timedelta
from typing import Any, Literal, Protocol

import httpx
from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from iwanttowatch.db import utcnow
from iwanttowatch.models import LlmCall, get_setting

log = logging.getLogger(__name__)

# The providers in use, first choice first, comma-separated: "gemini,ollama".
ORDER_SETTING = "llm_order"
OLLAMA_URL_SETTING = "ollama_url"
OLLAMA_MODEL_SETTING = "ollama_model"
GEMINI_KEY_SETTING = "gemini_api_key"
GEMINI_MODEL_SETTING = "gemini_model"
OPENAI_URL_SETTING = "openai_base_url"
OPENAI_KEY_SETTING = "openai_api_key"
OPENAI_MODEL_SETTING = "openai_model"
CLAUDE_KEY_SETTING = "claude_api_key"
CLAUDE_MODEL_SETTING = "claude_model"

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
# An alias Google moves to its current Flash model, so the default survives renames.
DEFAULT_GEMINI_MODEL = "gemini-flash-latest"
DEFAULT_OPENAI_URL = "https://api.openai.com/v1"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
CLAUDE_BASE_URL = "https://api.anthropic.com/v1"
DEFAULT_CLAUDE_MODEL = "claude-3-5-haiku-latest"
# Small CPU models on a home server can take a while.
TIMEOUT_SECONDS = 180
# Gemini answers 503 when overloaded and 429 at its free-tier limit, usually briefly.
RETRY_STATUSES = {429, 500, 503}
RETRY_DELAYS = (2.0, 5.0)
# Calls kept in the log; older than 24 hours or beyond 200 are deleted as new ones arrive.
KEEP_CALLS = 200

Purpose = Literal[
    "suggestions", "persona", "themes", "moods", "why", "ask", "check", "test", "clash"
]
ProviderName = Literal["ollama", "gemini", "openai", "claude"]
PROVIDERS: tuple[ProviderName, ...] = ("ollama", "gemini", "openai", "claude")


class LlmError(Exception):
    pass


class LlmProvider(Protocol):
    # json_reply asks for a reply that is only a JSON object, for prompts that want one.
    def generate(self, system: str, prompt: str, *, json_reply: bool = False) -> str: ...


class OllamaProvider:
    def __init__(self, base_url: str, model: str) -> None:
        self._http = httpx.Client(base_url=base_url.rstrip("/"), timeout=TIMEOUT_SECONDS)
        self._model = model

    def generate(self, system: str, prompt: str, *, json_reply: bool = False) -> str:
        body: dict[str, Any] = {
            "model": self._model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }
        if json_reply:
            body["format"] = "json"
        data = _post(self._http, "/api/chat", body, "Ollama")
        return str(data.get("message", {}).get("content", "")).strip()


class GeminiProvider:
    def __init__(self, api_key: str, model: str, base_url: str = GEMINI_BASE_URL) -> None:
        self._http = httpx.Client(
            base_url=base_url, timeout=TIMEOUT_SECONDS, headers={"x-goog-api-key": api_key}
        )
        self._model = model

    def generate(self, system: str, prompt: str, *, json_reply: bool = False) -> str:
        body: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        }
        if json_reply:
            # Constrains the reply to well-formed JSON.
            body["generationConfig"] = {"responseMimeType": "application/json"}
        data = _post(self._http, f"/models/{self._model}:generateContent", body, "Gemini")
        candidates = data.get("candidates") or []
        parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
        return "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()


class OpenAICompatibleProvider:
    """Any OpenAI-compatible chat completions API (OpenAI, Groq, OpenRouter, Mistral, LM Studio)."""

    def __init__(self, api_key: str, model: str, base_url: str = DEFAULT_OPENAI_URL) -> None:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"), timeout=TIMEOUT_SECONDS, headers=headers
        )
        self._model = model

    def generate(self, system: str, prompt: str, *, json_reply: bool = False) -> str:
        body: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }
        if json_reply:
            body["response_format"] = {"type": "json_object"}
        data = _post(self._http, "/chat/completions", body, "OpenAI-compatible")
        choices = data.get("choices") or []
        if not choices:
            return ""
        content = choices[0].get("message", {}).get("content", "")
        return str(content).strip()


class ClaudeProvider:
    """Anthropic Messages API provider."""

    def __init__(self, api_key: str, model: str, base_url: str = CLAUDE_BASE_URL) -> None:
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=TIMEOUT_SECONDS,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
        )
        self._model = model

    def generate(self, system: str, prompt: str, *, json_reply: bool = False) -> str:
        sys_prompt = f"{system}\nReturn only valid JSON." if json_reply else system
        body: dict[str, Any] = {
            "model": self._model,
            "max_tokens": 2048,
            "system": sys_prompt,
            "messages": [{"role": "user", "content": prompt}],
        }
        data = _post(self._http, "/messages", body, "Claude")
        parts = data.get("content") or []
        return "".join(
            p.get("text", "") for p in parts if isinstance(p, dict) and p.get("type") == "text"
        ).strip()


def _post(http: httpx.Client, path: str, body: dict[str, Any], name: str) -> dict[str, Any]:
    for delay in (*RETRY_DELAYS, None):
        try:
            response = http.post(path, json=body)
        except httpx.TransportError as error:
            raise LlmError(f"Couldn't reach {name}: {error}") from error
        if response.status_code not in RETRY_STATUSES or delay is None:
            break
        time.sleep(delay)
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


class LoggedProvider:
    """Records each call in the LLM log, in its own transaction, so a call is logged
    even when the caller's work is rolled back."""

    def __init__(
        self,
        inner: LlmProvider,
        session: Session,
        purpose: Purpose,
        provider: str,
        model: str,
        user_id: int | None,
    ) -> None:
        self._inner, self._engine = inner, session.get_bind()
        self._fields = {"purpose": purpose, "provider": provider, "model": model}
        self._user_id = user_id

    def generate(self, system: str, prompt: str, *, json_reply: bool = False) -> str:
        start = time.monotonic()
        reply: str | None = None
        error: str | None = None
        try:
            reply = self._inner.generate(system, prompt, json_reply=json_reply)
            return reply
        except LlmError as failure:
            error = str(failure)
            raise
        finally:
            call = LlmCall(
                **self._fields,
                user_id=self._user_id,
                system=system,
                prompt=prompt,
                reply=reply,
                error=error,
                duration_ms=round((time.monotonic() - start) * 1000),
            )
            try:
                with Session(self._engine) as session:
                    session.add(call)
                    session.flush()
                    keep = select(LlmCall.id).order_by(LlmCall.id.desc()).limit(KEEP_CALLS)
                    session.execute(
                        delete(LlmCall).where(
                            (LlmCall.id.not_in(keep))
                            | (LlmCall.created_at < utcnow() - timedelta(days=1))
                        )
                    )
                    session.commit()
            except SQLAlchemyError:
                # The log is for debugging; never fail the call over it.
                log.warning("Couldn't log an LLM call", exc_info=True)


def make_provider(
    session: Session,
    purpose: Purpose,
    provider: str,
    model: str,
    ollama_url: str | None,
    gemini_api_key: str | None,
    user_id: int | None = None,
    *,
    openai_url: str | None = None,
    openai_api_key: str | None = None,
    claude_api_key: str | None = None,
) -> LlmProvider:
    inner: LlmProvider
    if provider == "ollama" and ollama_url:
        inner = OllamaProvider(ollama_url, model)
    elif provider == "gemini" and gemini_api_key:
        inner = GeminiProvider(gemini_api_key, model)
    elif provider == "openai" and (openai_api_key or openai_url):
        inner = OpenAICompatibleProvider(
            openai_api_key or "", model, openai_url or DEFAULT_OPENAI_URL
        )
    elif provider == "claude" and claude_api_key:
        inner = ClaudeProvider(claude_api_key, model)
    else:
        raise LlmError(f"{provider} is not fully configured")
    return LoggedProvider(inner, session, purpose, provider, model, user_id)


class FallbackProvider:
    """Asks each provider in turn until one answers."""

    def __init__(self, providers: list[LlmProvider]) -> None:
        self._providers = providers

    def generate(self, system: str, prompt: str, *, json_reply: bool = False) -> str:
        failure = LlmError("No LLM is configured")
        for provider in self._providers:
            try:
                return provider.generate(system, prompt, json_reply=json_reply)
            except LlmError as error:
                failure = error
        raise failure


def llm_order(session: Session) -> list[ProviderName]:
    """The providers in use, first choice first."""
    names = (get_setting(session, ORDER_SETTING) or "").split(",")
    return sorted((name for name in PROVIDERS if name in names), key=names.index)


def model_for(session: Session, name: ProviderName) -> str:
    if name == "ollama":
        return get_setting(session, OLLAMA_MODEL_SETTING) or ""
    if name == "openai":
        return get_setting(session, OPENAI_MODEL_SETTING) or DEFAULT_OPENAI_MODEL
    if name == "claude":
        return get_setting(session, CLAUDE_MODEL_SETTING) or DEFAULT_CLAUDE_MODEL
    return get_setting(session, GEMINI_MODEL_SETTING) or DEFAULT_GEMINI_MODEL


def provider_from_settings(
    session: Session, purpose: Purpose, user_id: int | None = None
) -> LlmProvider | None:
    """The LLMs set up in Settings, in the admin's order, or None when there are none."""
    providers = [
        make_provider(
            session,
            purpose,
            name,
            model_for(session, name),
            get_setting(session, OLLAMA_URL_SETTING),
            get_setting(session, GEMINI_KEY_SETTING),
            user_id,
            openai_url=get_setting(session, OPENAI_URL_SETTING),
            openai_api_key=get_setting(session, OPENAI_KEY_SETTING),
            claude_api_key=get_setting(session, CLAUDE_KEY_SETTING),
        )
        for name in llm_order(session)
    ]
    if not providers:
        return None
    return providers[0] if len(providers) == 1 else FallbackProvider(providers)
