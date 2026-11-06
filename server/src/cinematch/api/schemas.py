from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

LanguageCode = Annotated[str, Field(pattern=r"^[a-z]{2,3}$")]


class Me(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    display_name: str
    is_admin: bool
    region: str
    languages: list[str]


class SetupStatus(BaseModel):
    complete: bool


class SetupRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    display_name: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=8, max_length=256)
    # ISO 3166-1 alpha-2 country, used for streaming availability.
    region: str = Field(pattern=r"^[A-Z]{2}$")
    # ISO 639-1 codes of languages the user watches, e.g. ["ml", "en"].
    languages: list[LanguageCode] = Field(default_factory=list, max_length=20)


class LoginRequest(BaseModel):
    username: str
    password: str
