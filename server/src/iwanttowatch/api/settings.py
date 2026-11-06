from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from iwanttowatch.api.deps import AdminUser, CurrentUser, DbSession
from iwanttowatch.models import get_setting, set_setting
from iwanttowatch.tmdb import API_KEY_SETTING, TmdbAuthError, TmdbClient, TmdbError

router = APIRouter(prefix="/api/v1/settings")


class ServerSettings(BaseModel):
    tmdb_configured: bool


class TmdbKey(BaseModel):
    # A v3 API key or a v4 API Read Access Token from themoviedb.org/settings/api.
    api_key: str = Field(min_length=16, max_length=1024)


@router.get("")
def read_settings(_user: CurrentUser, session: DbSession) -> ServerSettings:
    # Secrets are never returned, only whether they are set.
    return ServerSettings(tmdb_configured=get_setting(session, API_KEY_SETTING) is not None)


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
    return ServerSettings(tmdb_configured=True)
