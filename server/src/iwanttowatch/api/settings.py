from typing import Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from iwanttowatch.api.deps import AdminUser, CurrentUser, DbSession
from iwanttowatch.llm import (
    DEFAULT_GEMINI_MODEL,
    GEMINI_KEY_SETTING,
    MODEL_SETTING,
    OLLAMA_URL_SETTING,
    PROVIDER_SETTING,
    LlmError,
    make_provider,
)
from iwanttowatch.models import get_setting, set_setting
from iwanttowatch.tmdb import API_KEY_SETTING, TmdbAuthError, TmdbClient, TmdbError

router = APIRouter(prefix="/api/v1/settings")

LlmChoice = Literal["none", "ollama", "gemini"]


class LlmSettings(BaseModel):
    provider: LlmChoice
    model: str | None
    ollama_url: str | None
    gemini_configured: bool
    default_gemini_model: str = DEFAULT_GEMINI_MODEL


class ServerSettings(BaseModel):
    tmdb_configured: bool
    llm: LlmSettings


class TmdbKey(BaseModel):
    # A v3 API key or a v4 API Read Access Token from themoviedb.org/settings/api.
    api_key: str = Field(min_length=16, max_length=1024)


class LlmUpdate(BaseModel):
    provider: LlmChoice
    model: str | None = Field(default=None, max_length=200)
    ollama_url: str | None = Field(default=None, max_length=500)
    # Omit to keep the stored Gemini key.
    gemini_api_key: str | None = Field(default=None, max_length=500)


def _settings_out(session: Session) -> ServerSettings:
    # Secrets are never returned, only whether they are set.
    provider = get_setting(session, PROVIDER_SETTING)
    return ServerSettings(
        tmdb_configured=get_setting(session, API_KEY_SETTING) is not None,
        llm=LlmSettings(
            provider="ollama"
            if provider == "ollama"
            else "gemini"
            if provider == "gemini"
            else "none",
            model=get_setting(session, MODEL_SETTING),
            ollama_url=get_setting(session, OLLAMA_URL_SETTING),
            gemini_configured=get_setting(session, GEMINI_KEY_SETTING) is not None,
        ),
    )


@router.get("")
def read_settings(_user: CurrentUser, session: DbSession) -> ServerSettings:
    return _settings_out(session)


@router.put("/tmdb")
def set_tmdb_key(
    body: TmdbKey, _admin: AdminUser, request: Request, session: DbSession
) -> ServerSettings:
    api_key = body.api_key.strip()
    client = TmdbClient(api_key, request.app.state.engine, request.app.state.tmdb_base_url)
    try:
        client.get("/configuration")
    except TmdbAuthError as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "TMDb rejected this key") from error
    except TmdbError as error:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "Couldn't reach TMDb to check the key; try again"
        ) from error
    set_setting(session, API_KEY_SETTING, api_key)
    session.commit()
    return _settings_out(session)


@router.put("/llm")
def set_llm(body: LlmUpdate, _admin: AdminUser, session: DbSession) -> ServerSettings:
    """Choose Ollama, Gemini, or no LLM. A short test prompt checks the choice first."""
    if body.provider == "none":
        set_setting(session, PROVIDER_SETTING, None)
        session.commit()
        return _settings_out(session)

    gemini_key = (body.gemini_api_key or "").strip() or get_setting(session, GEMINI_KEY_SETTING)
    ollama_url = (body.ollama_url or "").strip() or None
    model = (body.model or "").strip() or (
        DEFAULT_GEMINI_MODEL if body.provider == "gemini" else ""
    )
    if body.provider == "ollama" and not (ollama_url and model):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Enter the Ollama URL and a model name")
    if body.provider == "gemini" and not gemini_key:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Enter a Gemini API key")
    try:
        llm = make_provider(body.provider, model, ollama_url, gemini_key)
        if not llm.generate("Answer with one word.", "Say OK."):
            raise LlmError("The model returned an empty answer")
    except LlmError as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Test failed: {error}") from error

    set_setting(session, PROVIDER_SETTING, body.provider)
    set_setting(session, MODEL_SETTING, model)
    if body.provider == "ollama":
        set_setting(session, OLLAMA_URL_SETTING, ollama_url)
    else:
        set_setting(session, GEMINI_KEY_SETTING, gemini_key)
    session.commit()
    return _settings_out(session)
