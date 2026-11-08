"""Exporting everything a user has told iWantToWatch, and restoring it from that file.

The file is JSON. It holds the user's region, languages, streaming services, and birth
year, every rating, watch, and favourite per source, and their feedback on suggestions. Films are
identified by TMDb ID; titles and years are included only so people can read the file.
Restoring merges it into the account: the file wins for each film and source it has.
"""

from datetime import date, datetime
from typing import Literal, Self, cast

from fastapi import APIRouter, HTTPException, Request, Response, UploadFile, status
from pydantic import BaseModel, Field, ValidationError, model_validator
from sqlalchemy import select

from iwanttowatch.api.deps import AdultUser, DbSession, Tmdb
from iwanttowatch.api.imports import MAX_UPLOAD_BYTES
from iwanttowatch.api.reactions import Reaction
from iwanttowatch.api.schemas import BirthYear, LanguageCode
from iwanttowatch.catalog import ensure_titles
from iwanttowatch.db import utcnow
from iwanttowatch.models import Feedback, ShortlistItem, Title, UserTitle
from iwanttowatch.tags import BY_ID, MAX_NOTE, MAX_TAGS

router = APIRouter(prefix="/api/v1/me")

Source = Literal["imdb", "letterboxd", "netflix", "app", "jellyfin", "trakt"]
FeedbackKind = Literal["up", "down", "dismissed", "snoozed"]


class ExportedProfile(BaseModel):
    region: str = Field(pattern=r"^[A-Z]{2}$")
    languages: list[LanguageCode] = Field(max_length=20)
    subscriptions: list[int]
    birth_year: BirthYear | None = None


class ExportedEntry(BaseModel):
    tmdb_id: int
    title: str = ""
    year: int | None = None
    source: Source
    rating: float | None = Field(None, ge=0, le=10)
    rated_at: date | None = None
    watched: bool = False
    watched_at: date | None = None
    favorite: bool = False
    reaction: Reaction | None = None
    tags: list[str] = Field(default_factory=list, max_length=MAX_TAGS)
    note: str | None = Field(None, max_length=MAX_NOTE)

    @model_validator(mode="after")
    def tags_match_reaction(self) -> Self:
        positive = self.reaction != "disliked"
        for tag in self.tags:
            if self.reaction is None or tag not in BY_ID or BY_ID[tag].positive != positive:
                raise ValueError(f"{tag!r} isn't a tag for {self.reaction!r}")
        return self


class ExportedFeedback(BaseModel):
    tmdb_id: int
    title: str = ""
    kind: FeedbackKind
    until: datetime | None = None
    created_at: datetime


class ExportedShortlistItem(BaseModel):
    tmdb_id: int
    title: str = ""
    added_at: datetime


class DataExport(BaseModel):
    format: Literal["iwanttowatch"] = "iwanttowatch"
    version: Literal[1] = 1
    exported_at: datetime
    profile: ExportedProfile
    entries: list[ExportedEntry]
    feedback: list[ExportedFeedback]
    # Missing from exports made before shortlists.
    shortlist: list[ExportedShortlistItem] = []


class RestoreSummary(BaseModel):
    entries: int
    feedback: int
    # Films TMDb no longer has, left out.
    skipped: int


@router.get("/export")
def export_data(user: AdultUser, session: DbSession, response: Response) -> DataExport:
    """Download everything you've told iWantToWatch as a JSON file."""
    entries = session.execute(
        select(UserTitle, Title)
        .join(Title, Title.tmdb_id == UserTitle.tmdb_id)
        .where(UserTitle.user_id == user.id)
        .order_by(UserTitle.tmdb_id, UserTitle.source)
    ).all()
    feedback = session.execute(
        select(Feedback, Title)
        .join(Title, Title.tmdb_id == Feedback.tmdb_id)
        .where(Feedback.user_id == user.id)
        .order_by(Feedback.tmdb_id)
    ).all()
    shortlist = session.execute(
        select(ShortlistItem, Title)
        .join(Title, Title.tmdb_id == ShortlistItem.tmdb_id)
        .where(ShortlistItem.user_id == user.id)
        .order_by(ShortlistItem.added_at)
    ).all()
    data = DataExport(
        exported_at=utcnow(),
        profile=ExportedProfile(
            region=user.region,
            languages=user.languages,
            subscriptions=user.subscriptions,
            birth_year=user.birth_year,
        ),
        entries=[
            ExportedEntry(
                tmdb_id=e.tmdb_id,
                title=t.title,
                year=t.year,
                source=cast(Source, e.source),
                rating=e.rating,
                rated_at=e.rated_at,
                watched=e.watched,
                watched_at=e.watched_at,
                favorite=e.favorite,
                reaction=cast(Reaction | None, e.reaction),
                tags=e.tags,
                note=e.note,
            )
            for e, t in entries
        ],
        feedback=[
            ExportedFeedback(
                tmdb_id=f.tmdb_id,
                title=t.title,
                kind=cast(FeedbackKind, f.kind),
                until=f.until,
                created_at=f.created_at,
            )
            for f, t in feedback
        ],
        shortlist=[
            ExportedShortlistItem(tmdb_id=s.tmdb_id, title=t.title, added_at=s.added_at)
            for s, t in shortlist
        ],
    )
    name = f"iwanttowatch-{user.username}-{data.exported_at:%Y-%m-%d}.json"
    response.headers["Content-Disposition"] = f'attachment; filename="{name}"'
    return data


@router.post("/import")
def restore_data(
    file: UploadFile, user: AdultUser, session: DbSession, request: Request, tmdb: Tmdb
) -> RestoreSummary:
    """Restore an iWantToWatch export into your account, merging with what's there."""
    content = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "The file is larger than 20 MB")
    try:
        data = DataExport.model_validate_json(content)
    except ValidationError as error:
        problem = error.errors()[0]
        where = ".".join(str(part) for part in problem["loc"])
        name = file.filename or "The file"
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"{name} isn't an iWantToWatch export ({where}: {problem['msg']})",
        ) from error

    titles = ensure_titles(
        session,
        tmdb,
        [
            *(e.tmdb_id for e in data.entries),
            *(f.tmdb_id for f in data.feedback),
            *(s.tmdb_id for s in data.shortlist),
        ],
    )
    existing = {
        (e.tmdb_id, e.source): e
        for e in session.scalars(select(UserTitle).where(UserTitle.user_id == user.id))
    }
    entries = [e for e in data.entries if e.tmdb_id in titles]
    for item in entries:
        entry = existing.get((item.tmdb_id, item.source))
        if entry is None:
            entry = UserTitle(user_id=user.id, tmdb_id=item.tmdb_id, source=item.source)
            session.add(entry)
        entry.rating, entry.rated_at = item.rating, item.rated_at
        entry.watched, entry.watched_at = item.watched, item.watched_at
        entry.favorite, entry.reaction, entry.tags = item.favorite, item.reaction, item.tags
        entry.note = item.note
    feedback = [f for f in data.feedback if f.tmdb_id in titles]
    for said in feedback:
        row = session.get(Feedback, (user.id, said.tmdb_id)) or Feedback(
            user_id=user.id, tmdb_id=said.tmdb_id
        )
        row.kind, row.until, row.created_at = said.kind, said.until, said.created_at
        session.add(row)
    for saved in data.shortlist:
        if saved.tmdb_id in titles:
            session.merge(
                ShortlistItem(user_id=user.id, tmdb_id=saved.tmdb_id, added_at=saved.added_at)
            )
    user.region = data.profile.region
    user.languages = data.profile.languages
    user.subscriptions = data.profile.subscriptions
    # Older exports have no birth year; keep the one set here.
    if data.profile.birth_year is not None:
        user.birth_year = data.profile.birth_year
    session.commit()
    request.app.state.feed_worker.request(user.id)
    skipped = len(data.entries) - len(entries) + len(data.feedback) - len(feedback)
    return RestoreSummary(entries=len(entries), feedback=len(feedback), skipped=skipped)
