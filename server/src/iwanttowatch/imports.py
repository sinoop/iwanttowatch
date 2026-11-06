"""Importing ratings and watch history from IMDb and Letterboxd exports."""

import csv
import io
import logging
import queue
import threading
import zipfile
from datetime import date, datetime
from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from iwanttowatch.catalog import LOOKUP_CACHE, ensure_title, find_by_title
from iwanttowatch.db import utcnow
from iwanttowatch.models import ImportJob, ImportRow, UserTitle
from iwanttowatch.taste import mark_persona_stale, refresh_persona_quietly
from iwanttowatch.tmdb import TmdbAuthError, TmdbClient, TmdbError, client_from_settings

log = logging.getLogger(__name__)

# IMDb "Title Type" values that are movies; series, episodes, and games are skipped.
# Older exports use camelCase ("tvMovie"), newer ones words ("TV Movie").
IMDB_MOVIE_TYPES = {"movie", "tvmovie", "video", "short"}


class ImportFormatError(ValueError):
    pass


def parse_export(filename: str, content: bytes) -> tuple[str, list[dict[str, Any]]]:
    """Recognise an export file and return its source and normalised rows.

    Each row has: title, year, rating (0–10 or None), rated_at, watched_at, liked,
    and for IMDb imdb_id and title_type.
    """
    if zipfile.is_zipfile(io.BytesIO(content)):
        return "letterboxd", _parse_letterboxd_zip(content)
    rows = _read_csv(content)
    header = set(rows[0].keys()) if rows else set()
    if {"Const", "Your Rating"} <= header:
        return "imdb", [_imdb_row(r) for r in rows if r.get("Const")]
    if "Letterboxd URI" in header:
        return "letterboxd", _merge_letterboxd({"upload": rows})
    raise ImportFormatError(
        f"{filename} doesn't look like an IMDb ratings export or a Letterboxd export"
    )


def _read_csv(content: bytes) -> list[dict[str, str]]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("latin-1")
    return list(csv.DictReader(io.StringIO(text)))


def _imdb_row(r: dict[str, str]) -> dict[str, Any]:
    return {
        "imdb_id": r["Const"].strip(),
        "title": r.get("Title", ""),
        "year": _int(r.get("Year")),
        "rating": _float(r.get("Your Rating")),
        "rated_at": _date(r.get("Date Rated")),
        "watched_at": None,
        "liked": False,
        "title_type": r.get("Title Type", "movie"),
    }


def _parse_letterboxd_zip(content: bytes) -> list[dict[str, Any]]:
    files: dict[str, list[dict[str, str]]] = {}
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        for name in ("ratings.csv", "watched.csv", "diary.csv", "likes/films.csv"):
            if name in archive.namelist():
                files[name] = _read_csv(archive.read(name))
    if not files:
        raise ImportFormatError("This ZIP file doesn't look like a Letterboxd export")
    return _merge_letterboxd(files)


def _merge_letterboxd(files: dict[str, list[dict[str, str]]]) -> list[dict[str, Any]]:
    """Combine Letterboxd's files into one row per film."""
    films: dict[str, dict[str, Any]] = {}
    for name, rows in files.items():
        for r in rows:
            # Not the URI: in diary.csv it links to the diary entry, not the film.
            key = f"{r.get('Name')}|{r.get('Year')}"
            film = films.setdefault(
                key,
                {
                    "title": r.get("Name", ""),
                    "year": _int(r.get("Year")),
                    "rating": None,
                    "rated_at": None,
                    "watched_at": None,
                    "liked": False,
                },
            )
            if name == "likes/films.csv":
                film["liked"] = True
                continue
            stars = _float(r.get("Rating"))
            if stars is not None and name != "diary.csv":
                # Letterboxd rates 0.5–5 stars. ratings.csv holds the current rating;
                # diary ratings are as logged at the time.
                film["rating"] = stars * 2
                film["rated_at"] = _date(r.get("Date"))
            # diary.csv has the watch date; in watched.csv "Date" is when it was logged;
            # in ratings.csv "Date" is when it was rated, not watched.
            watched = _date(r.get("Watched Date")) or (
                None if "Rating" in r else _date(r.get("Date"))
            )
            if watched and (film["watched_at"] is None or watched > film["watched_at"]):
                film["watched_at"] = watched
    return list(films.values())


def _int(value: str | None) -> int | None:
    try:
        return int(value) if value else None
    except ValueError:
        return None


def _float(value: str | None) -> float | None:
    try:
        return float(value) if value else None
    except ValueError:
        return None


def _date(value: str | None) -> str | None:
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date().isoformat() if value else None
    except ValueError:
        return None


def create_job(
    session: Session, user_id: int, source: str, filename: str, rows: list[dict[str, Any]]
) -> ImportJob:
    job = ImportJob(user_id=user_id, source=source, filename=filename)
    session.add(job)
    session.flush()
    for position, data in enumerate(rows):
        row = ImportRow(job_id=job.id, position=position, data=data)
        title_type = str(data.get("title_type", "movie")).replace(" ", "").lower()
        if title_type not in IMDB_MOVIE_TYPES:
            row.status = "skipped"
            row.message = f"{data['title_type']}: iWantToWatch only handles movies"
        session.add(row)
    session.commit()
    return job


def run_job(engine: Engine, tmdb_base_url: str, job_id: int) -> None:
    with Session(engine) as session:
        job = session.get(ImportJob, job_id)
        if job is None or job.status == "done":
            return
        tmdb = client_from_settings(session, engine, tmdb_base_url)
        if tmdb is None:
            job.status, job.error = "failed", "Add a TMDb API key in Settings, then retry"
            session.commit()
            return
        job.status, job.error = "running", None
        session.commit()
        pending = session.scalars(
            select(ImportRow)
            .where(ImportRow.job_id == job_id, ImportRow.status == "pending")
            .order_by(ImportRow.position)
        ).all()
        try:
            for row in pending:
                _match_row(session, tmdb, job, row)
                session.commit()
        except TmdbError as error:
            session.rollback()
            job.status = "failed"
            job.error = (
                "TMDb rejected the API key; update it in Settings, then retry"
                if isinstance(error, TmdbAuthError)
                else f"{error}. Retry to continue where it stopped."
            )
            session.commit()
            return
        # Flag the persona before the job reads as done, so the UI keeps waiting for it.
        rewrite = mark_persona_stale(session, job.user_id)
        job.status, job.finished_at = "done", utcnow()
        session.commit()
        if rewrite:
            refresh_persona_quietly(session, job.user_id)


def _match_row(session: Session, tmdb: TmdbClient, job: ImportJob, row: ImportRow) -> None:
    data = row.data
    if data.get("imdb_id"):
        found = tmdb.get(f"/find/{data['imdb_id']}", {"external_source": "imdb_id"}, LOOKUP_CACHE)
        if found["movie_results"]:
            apply_match(session, tmdb, job, row, found["movie_results"][0]["id"])
            return
        if found["tv_results"]:
            row.status, row.message = "skipped", "TV title: iWantToWatch only handles movies"
            return
    tmdb_id, candidates = find_by_title(tmdb, data["title"], data.get("year"))
    if tmdb_id is not None:
        apply_match(session, tmdb, job, row, tmdb_id)
    else:
        row.status, row.candidates = "review", candidates
        row.message = "Several possible matches" if candidates else "Not found on TMDb"


def apply_match(
    session: Session, tmdb: TmdbClient, job: ImportJob, row: ImportRow, tmdb_id: int
) -> None:
    """Record the row's rating, watch, and like against the matched title."""
    ensure_title(session, tmdb, tmdb_id)
    entry = session.scalar(
        select(UserTitle).where(
            UserTitle.user_id == job.user_id,
            UserTitle.tmdb_id == tmdb_id,
            UserTitle.source == job.source,
        )
    )
    if entry is None:
        entry = UserTitle(user_id=job.user_id, tmdb_id=tmdb_id, source=job.source)
        session.add(entry)
    data = row.data
    if data.get("rating") is not None:
        entry.rating = data["rating"]
        entry.rated_at = _to_date(data.get("rated_at"))
    # A rating, diary entry, or like in either service means the user has seen it.
    entry.watched = True
    watched_at = _to_date(data.get("watched_at"))
    if watched_at and (entry.watched_at is None or watched_at > entry.watched_at):
        entry.watched_at = watched_at
    entry.favorite = entry.favorite or bool(data.get("liked"))
    row.status, row.tmdb_id, row.message = "matched", tmdb_id, None


def _to_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


class ImportWorker:
    """Runs import jobs one at a time on a background thread."""

    def __init__(self, engine: Engine, tmdb_base_url: str) -> None:
        self._engine = engine
        self._tmdb_base_url = tmdb_base_url
        self._queue: queue.Queue[int] = queue.Queue()

    def start(self) -> None:
        with Session(self._engine) as session:
            unfinished = session.scalars(
                select(ImportJob.id).where(ImportJob.status.in_(["pending", "running"]))
            ).all()
        for job_id in unfinished:
            self.submit(job_id)
        threading.Thread(target=self._loop, name="imports", daemon=True).start()

    def submit(self, job_id: int) -> None:
        self._queue.put(job_id)

    def wait_until_idle(self) -> None:
        self._queue.join()

    def _loop(self) -> None:
        while True:
            job_id = self._queue.get()
            try:
                run_job(self._engine, self._tmdb_base_url, job_id)
            except Exception:
                log.exception("Import job %s crashed", job_id)
                with Session(self._engine) as session:
                    job = session.get(ImportJob, job_id)
                    if job is not None:
                        job.status, job.error = "failed", "Unexpected error; see the server log"
                        session.commit()
            finally:
                self._queue.task_done()
