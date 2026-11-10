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
    # Show rent and buy options in movie details (off by default).
    show_rent_buy: Mapped[bool] = mapped_column(default=False)
    # Optional on adults (films from before it count a little against their matches);
    # required on child profiles, where it sets their certificate age limit.
    birth_year: Mapped[int | None]
    # Household-level child profile, without a password; any adult can switch to it.
    is_child: Mapped[bool] = mapped_column(default=False)
    # Age limit for a child profile, as a certificate in their region (e.g. "U/A 7+" or "PG"),
    # worked out from their birth year.
    max_certificate: Mapped[str | None] = mapped_column(String(16))
    # Child profiles only: the upper-cased certificate codes at or below the limit in their
    # region, worked out when their birth year or region is set. Null means no age limit.
    allowed_certificates: Mapped[list[str] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Invite(Base):
    """A one-time link an admin sends so a new household member can set up an account."""

    __tablename__ = "invites"

    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[str] = mapped_column(String(64), unique=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    # Who it's for, as the admin wrote it; suggested as the new member's display name.
    name: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


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
    # {"IN": "U/A 7+", "US": "PG"}: film certificates per country from TMDb release dates.
    certifications: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    # Optional LLM-written note on a film's themes and values for parents.
    themes_note: Mapped[str | None] = mapped_column(Text)
    # Moods the LLM picked from iwanttowatch.moods; None until it has tagged the film.
    ai_moods: Mapped[list[str] | None] = mapped_column(JSON)
    vote_average: Mapped[float | None]
    vote_count: Mapped[int | None]
    popularity: Mapped[float | None]
    # IMDb's weighted rating and vote count, when an admin turned IMDb ratings on.
    imdb_rating: Mapped[float | None]
    imdb_votes: Mapped[int | None]
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
    # "imdb", "letterboxd", "netflix", "app" (rated in iWantToWatch), "jellyfin"; later "trakt".
    source: Mapped[str] = mapped_column(String(16))
    # Normalised to 0–10.
    rating: Mapped[float | None]
    rated_at: Mapped[date | None]
    watched: Mapped[bool] = mapped_column(default=False)
    watched_at: Mapped[date | None]
    favorite: Mapped[bool] = mapped_column(default=False)
    # In-app ratings only: "disliked", "liked", or "loved", and up to three tag IDs
    # from iwanttowatch.tags saying what the user liked most or what didn't work, and
    # an optional note in their own words.
    reaction: Mapped[str | None] = mapped_column(String(16))
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    note: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Persona(Base):
    """An LLM-written summary of a user's taste, in plain words, from their ratings."""

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


class Feedback(Base):
    """What a user said about a suggestion from a feed card: "up" or "down" (more or
    less like this), "dismissed" (not interested), or "snoozed" (not now)."""

    __tablename__ = "feedback"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    tmdb_id: Mapped[int] = mapped_column(ForeignKey("titles.tmdb_id"), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    # When a snoozed film comes back.
    until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ShortlistItem(Base):
    """A film the user saved to choose from later."""

    __tablename__ = "shortlist"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    tmdb_id: Mapped[int] = mapped_column(ForeignKey("titles.tmdb_id"), primary_key=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GroupShortlistItem(Base):
    """A film someone saved for the household to choose from on Watch together."""

    __tablename__ = "group_shortlist"

    tmdb_id: Mapped[int] = mapped_column(ForeignKey("titles.tmdb_id"), primary_key=True)
    added_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class VoteSession(Base):
    """A host's guest vote: a ballot of films that anyone with the link can vote on,
    without an account, until it expires or the host closes it."""

    __tablename__ = "vote_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[str] = mapped_column(String(64), unique=True)
    host_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    # Household members watching, whose match counts as one more voter.
    user_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    # [{"tmdb_id": 1, "match": 0.71}], in ballot order; match is the household's.
    ballot: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Voter(Base):
    """A guest who joined a vote with a first name; the token lets them change votes."""

    __tablename__ = "voters"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("vote_sessions.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(32))
    token: Mapped[str] = mapped_column(String(64), unique=True)


class Vote(Base):
    __tablename__ = "votes"

    voter_id: Mapped[int] = mapped_column(
        ForeignKey("voters.id", ondelete="CASCADE"), primary_key=True
    )
    tmdb_id: Mapped[int] = mapped_column(primary_key=True)
    # "yes", "maybe", "no", or "seen".
    choice: Mapped[str] = mapped_column(String(8))


class TasteShare(Base):
    """A secret link through which friends on other servers add a user's taste to
    their group picks. Deleting it revokes the link."""

    __tablename__ = "taste_shares"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    token: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Guest(Base):
    """A friend from another server whose shared taste a user added for group picks."""

    __tablename__ = "guests"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # What the owner calls them; shared profiles carry no names.
    name: Mapped[str] = mapped_column(String(64))
    # The share link, refetched hourly; None for a taste card file, which never updates.
    link: Mapped[str | None] = mapped_column(Text)
    # [{"tmdb_id": 1, "value": 0.8, "weight": 1.0, "explicit": true}], as in the share.
    labels: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    seen: Mapped[list[int]] = mapped_column(JSON, default=list)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # The last refresh's error; the last good copy is kept until the link is revoked.
    error: Mapped[str | None]


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


class AiPick(Base):
    """The configured LLM's view of a film for a user at their last feed build: one it
    reviewed from the top of their feed, or one it added."""

    __tablename__ = "ai_picks"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    tmdb_id: Mapped[int] = mapped_column(ForeignKey("titles.tmdb_id"), primary_key=True)
    # The LLM's one-line reason, shown on the card.
    why: Mapped[str] = mapped_column(Text)
    # The rating out of 10 the LLM expects the user to give; None on picks from before
    # it was asked for one.
    rating: Mapped[float | None]
    # Suggested by the LLM rather than picked by the recommender.
    added: Mapped[bool] = mapped_column(default=True)


class Explanation(Base):
    """The LLM's answer to "Why this?" for one user and film, asked from the title dialog."""

    __tablename__ = "explanations"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    tmdb_id: Mapped[int] = mapped_column(ForeignKey("titles.tmdb_id"), primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LlmCall(Base):
    """One call to the configured LLM, kept so an admin can see how often it's called
    and exactly what was sent and answered. Only the most recent calls are kept."""

    __tablename__ = "llm_calls"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    # What it was for: "suggestions", "persona", "themes", "moods", "why", "check"
    # (eval-llm), or "test".
    purpose: Mapped[str] = mapped_column(String(32))
    provider: Mapped[str] = mapped_column(String(16))
    model: Mapped[str] = mapped_column(String(200))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    system: Mapped[str] = mapped_column(Text)
    prompt: Mapped[str] = mapped_column(Text)
    # The answer, or None when the call failed.
    reply: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int]
