from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from iwanttowatch.models import Title

LanguageCode = Annotated[str, Field(pattern=r"^[a-z]{2,3}$")]


class Me(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    display_name: str
    is_admin: bool
    region: str
    languages: list[str]
    # TMDb provider IDs of the streaming services the user subscribes to.
    subscriptions: list[int]
    birth_year: int | None
    # Set on child profiles, pointing to the parent account that manages them.
    parent_id: int | None = None
    # Maximum film certificate in the user's region, e.g. "U/A 7+" or "PG".
    max_certificate: str | None = None


# Optional; films from before it count a little against the user's matches.
BirthYear = Annotated[int, Field(ge=1900, le=2100)]


class ProfileUpdate(BaseModel):
    birth_year: BirthYear | None


class SetupStatus(BaseModel):
    complete: bool
    # Whether people can sign in with their Jellyfin username and password.
    jellyfin_login: bool


class NewAccount(BaseModel):
    username: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    display_name: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=8, max_length=256)


class SetupRequest(NewAccount):
    # ISO 3166-1 alpha-2 country, used for streaming availability.
    region: str = Field(pattern=r"^[A-Z]{2}$")
    # ISO 639-1 codes of languages the user watches, e.g. ["ml", "en"].
    languages: list[LanguageCode] = Field(default_factory=list, max_length=20)


class LoginRequest(BaseModel):
    username: str
    password: str


class ImdbScore(BaseModel):
    """IMDb's rating of a film, shown when an admin turned IMDb ratings on."""

    # For linking to the film's IMDb page.
    id: str
    rating: float
    votes: int


def imdb_score(title: Title) -> ImdbScore | None:
    if title.imdb_id is None or title.imdb_rating is None or not title.imdb_votes:
        return None
    return ImdbScore(id=title.imdb_id, rating=title.imdb_rating, votes=title.imdb_votes)
