from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import func, select

from iwanttowatch.api.deps import AdultUser, CurrentUser, DbSession, Tmdb
from iwanttowatch.imports import ImportFormatError, apply_match, create_job, parse_export
from iwanttowatch.models import ImportJob, ImportRow

router = APIRouter(prefix="/api/v1/imports")
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


class Candidate(BaseModel):
    tmdb_id: int
    title: str
    original_title: str
    original_language: str
    year: int | None
    poster_path: str | None
    why: str | None = None


class ImportCounts(BaseModel):
    pending: int = 0
    matched: int = 0
    review: int = 0
    skipped: int = 0


class ImportJobOut(BaseModel):
    id: int
    source: str
    filename: str
    status: str
    error: str | None
    created_at: datetime
    finished_at: datetime | None
    counts: ImportCounts


class ImportRowOut(BaseModel):
    id: int
    title: str
    year: int | None
    rating: float | None
    status: str
    tmdb_id: int | None
    candidates: list[Candidate]
    message: str | None


class Resolution(BaseModel):
    # The chosen TMDb movie, or null to skip the row.
    tmdb_id: int | None


def _job_out(session: DbSession, job: ImportJob) -> ImportJobOut:
    counts = dict(
        session.execute(
            select(ImportRow.status, func.count())
            .where(ImportRow.job_id == job.id)
            .group_by(ImportRow.status)
        ).all()
    )
    return ImportJobOut(
        id=job.id,
        source=job.source,
        filename=job.filename,
        status=job.status,
        error=job.error,
        created_at=job.created_at,
        finished_at=job.finished_at,
        counts=ImportCounts(**counts),
    )


def _own_job(session: DbSession, user: CurrentUser, job_id: int) -> ImportJob:
    job = session.get(ImportJob, job_id)
    if job is None or job.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Import not found")
    return job


@router.post("", status_code=status.HTTP_201_CREATED)
def upload_export(
    file: UploadFile, user: AdultUser, session: DbSession, request: Request, _tmdb: Tmdb
) -> ImportJobOut:
    """Upload an IMDb ratings.csv, a Letterboxd export ZIP or CSV, or NetflixViewingHistory.csv."""
    content = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "The file is larger than 20 MB")
    filename = file.filename or "upload"
    try:
        source, rows = parse_export(filename, content)
    except ImportFormatError as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(error)) from error
    if not rows:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{filename} has no ratings or films")
    job = create_job(session, user.id, source, filename, rows)
    request.app.state.import_worker.submit(job.id)
    return _job_out(session, job)


@router.get("")
def list_imports(user: CurrentUser, session: DbSession) -> list[ImportJobOut]:
    jobs = session.scalars(
        select(ImportJob).where(ImportJob.user_id == user.id).order_by(ImportJob.id.desc())
    ).all()
    return [_job_out(session, job) for job in jobs]


@router.get("/{job_id}/rows")
def list_rows(
    job_id: int,
    user: CurrentUser,
    session: DbSession,
    status_filter: str = Query("review", alias="status"),
) -> list[ImportRowOut]:
    _own_job(session, user, job_id)
    rows = session.scalars(
        select(ImportRow)
        .where(ImportRow.job_id == job_id, ImportRow.status == status_filter)
        .order_by(ImportRow.position)
    ).all()
    return [_row_out(row) for row in rows]


def _row_out(row: ImportRow) -> ImportRowOut:
    data: dict[str, Any] = row.data
    return ImportRowOut(
        id=row.id,
        title=data.get("title", ""),
        year=data.get("year"),
        rating=data.get("rating"),
        status=row.status,
        tmdb_id=row.tmdb_id,
        candidates=[Candidate(**c) for c in row.candidates],
        message=row.message,
    )


@router.post("/{job_id}/retry")
def retry_import(
    job_id: int, user: CurrentUser, session: DbSession, request: Request
) -> ImportJobOut:
    job = _own_job(session, user, job_id)
    if job.status != "failed":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only a failed import can be retried")
    job.status, job.error = "pending", None
    session.commit()
    request.app.state.import_worker.submit(job.id)
    return _job_out(session, job)


@router.post("/{job_id}/rows/{row_id}/resolve")
def resolve_row(
    job_id: int, row_id: int, body: Resolution, user: CurrentUser, session: DbSession, tmdb: Tmdb
) -> ImportRowOut:
    """Pick the right movie for a row the importer couldn't match, or skip it."""
    job = _own_job(session, user, job_id)
    row = session.get(ImportRow, row_id)
    if row is None or row.job_id != job.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Row not found")
    if row.status != "review":
        raise HTTPException(status.HTTP_409_CONFLICT, "This row doesn't need review")
    if body.tmdb_id is None:
        row.status, row.message = "skipped", "Skipped by you"
    else:
        apply_match(session, tmdb, job, row, body.tmdb_id)
    session.commit()
    return _row_out(row)
