from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, UniqueConstraint, delete
from sqlalchemy.orm import Mapped, Session, mapped_column

from iwanttowatch.db import Base, utcnow


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    display_name: Mapped[str] = mapped_column(String(128))
    # Null for users who sign in through Jellyfin instead of a local password.
    password_hash: Mapped[str | None]
    jellyfin_user_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    is_admin: Mapped[bool] = mapped_column(default=False)
    region: Mapped[str] = mapped_column(String(2))
    languages: Mapped[list[str]] = mapped_column(JSON, default=list)
    # TMDb provider IDs of the streaming services the user pays for, e.g. 8 for Netflix.
    subscriptions: Mapped[list[int]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AppSetting(Base):
    """Server-wide settings an admin edits in the UI, such as connector credentials."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


def get_setting(session: Session, key: str) -> str | None:
    setting = session.get(AppSetting, key)
    return setting.value if setting else None


def set_setting(session: Session, key: str, value: str | None) -> None:
    """Store a setting; None removes it."""
    if value is None:
        session.execute(delete(AppSetting).where(AppSetting.key == key))
    else:
        session.merge(AppSetting(key=key, value=value))


class Title(Base):
    """A movie, keyed by its TMDb ID, with the metadata the recommender uses."""

    __tablename__ = "titles"

    tmdb_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    imdb_id: Mapped[str | None] = mapped_column(String(16), index=True)
    title: Mapped[str]
    original_title: Mapped[str]
    original_language: Mapped[str] = mapped_column(String(8))
    spoken_languages: Mapped[list[str]] = mapped_column(JSON, default=list)
    origin_countries: Mapped[list[str]] = mapped_column(JSON, default=list)
    release_date: Mapped[date | None]
    year: Mapped[int | None]
    runtime: Mapped[int | None]
    overview: Mapped[str] = mapped_column(Text, default="")
    tagline: Mapped[str] = mapped_column(Text, default="")
    genres: Mapped[list[str]] = mapped_column(JSON, default=list)
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    # [{"id": 123, "name": "..."}], top-billed first.
    cast: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    directors: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    writers: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    alternative_titles: Mapped[list[str]] = mapped_column(JSON, default=list)
    # {"ml": {"title": "...", "overview": "..."}}: non-English metadata for multilingual models.
    translations: Mapped[dict[str, dict[str, str]]] = mapped_column(JSON, default=dict)
    vote_average: Mapped[float | None]
    vote_count: Mapped[int | None]
    popularity: Mapped[float | None]
    poster_path: Mapped[str | None]
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UserTitle(Base):
    """What one source says about a user and a title: a rating, a watch, a favourite.

    Sources are kept apart (one row per user, title, and source) so re-importing one
    source never overwrites another; the effective state merges them.
    """

    __tablename__ = "user_titles"
    __table_args__ = (UniqueConstraint("user_id", "tmdb_id", "source"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    tmdb_id: Mapped[int] = mapped_column(ForeignKey("titles.tmdb_id"), index=True)
    # "imdb", "letterboxd", "app" (rated in iWantToWatch), "jellyfin"; later "trakt".
    source: Mapped[str] = mapped_column(String(16))
    # Normalised to 0–10.
    rating: Mapped[float | None]
    rated_at: Mapped[date | None]
    watched: Mapped[bool] = mapped_column(default=False)
    watched_at: Mapped[date | None]
    favorite: Mapped[bool] = mapped_column(default=False)
    # In-app ratings only: "disliked", "liked", or "loved", and up to three tag IDs
    # from iwanttowatch.tags saying what the user liked most or what didn't work.
    reaction: Mapped[str | None] = mapped_column(String(16))
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Persona(Base):
    """An LLM-written sketch of the imaginary person whose taste matches a user's ratings."""

    __tablename__ = "personas"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    text: Mapped[str] = mapped_column(Text)
    # How many ratings it was written from, to tell when it is out of date.
    rating_count: Mapped[int]
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ImportJob(Base):
    __tablename__ = "import_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(16))
    filename: Mapped[str]
    # "pending" → "running" → "done", or "failed" with an error (retryable).
    status: Mapped[str] = mapped_column(String(16), default="pending")
    error: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ImportRow(Base):
    __tablename__ = "import_rows"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("import_jobs.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int]
    # The parsed row: title, year, rating (0–10), rated_at, watched_at, liked, imdb_id.
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    # "pending", "matched", "review" (needs the user to pick), or "skipped".
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    tmdb_id: Mapped[int | None]
    candidates: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    message: Mapped[str | None]


class LibraryItem(Base):
    """A movie in the Jellyfin libraries a linked user can see, with their play state.

    Jellyfin can hold several items for one film (editions, duplicates); the user's
    "jellyfin" UserTitle row merges them.
    """

    __tablename__ = "library_items"
    __table_args__ = (UniqueConstraint("user_id", "item_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    # Jellyfin's item ID, as 32 lowercase hex digits.
    item_id: Mapped[str] = mapped_column(String(32), index=True)
    # Null when the item couldn't be matched to a TMDb movie.
    tmdb_id: Mapped[int | None] = mapped_column(index=True)
    name: Mapped[str]
    year: Mapped[int | None]
    played: Mapped[bool] = mapped_column(default=False)
    last_played: Mapped[date | None]
    favorite: Mapped[bool] = mapped_column(default=False)


class ConnectorStatus(Base):
    """Health of a background connector, shown in Settings."""

    __tablename__ = "connector_status"

    connector: Mapped[str] = mapped_column(String(32), primary_key=True)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The last sync's error; cleared by the next successful sync.
    error: Mapped[str | None]
    webhook_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Availability(Base):
    """Where a title can be watched in one region, from TMDb (data by JustWatch)."""

    __tablename__ = "availability"

    tmdb_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    region: Mapped[str] = mapped_column(String(2), primary_key=True)
    # [{"provider_id": 8, "name": "Netflix", "logo_path": "/x.jpg", "kind": "flatrate"}];
    # kind is "flatrate", "free", "ads", "rent", or "buy".
    offers: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    # TMDb's watch page for the title in this region, which links on to each service.
    link: Mapped[str | None]
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Recommendation(Base):
    """A scored film in a user's discovery feed."""

    __tablename__ = "recommendations"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    tmdb_id: Mapped[int] = mapped_column(ForeignKey("titles.tmdb_id"), primary_key=True)
    # Calibrated predicted percentile of the user's ratings, 0–1.
    score: Mapped[float]
    # Position in the feed after diversity re-ranking.
    rank: Mapped[int]
    reasons: Mapped[list[str]] = mapped_column(JSON, default=list)


class FeedBuild(Base):
    """Progress of building a user's feed in the background."""

    __tablename__ = "feed_builds"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    # "queued", "building", "ready", or "failed".
    status: Mapped[str] = mapped_column(String(16))
    # What a running build is doing, for the progress message.
    step: Mapped[str | None]
    error: Mapped[str | None]
    built_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApiCache(Base):
    """Cached responses from external APIs, so re-imports and retries don't refetch."""

    __tablename__ = "api_cache"

    key: Mapped[str] = mapped_column(primary_key=True)
    body: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
