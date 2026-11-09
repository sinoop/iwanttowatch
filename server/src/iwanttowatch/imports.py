"""Importing ratings and watch history from IMDb, Letterboxd, and Netflix exports."""

import csv
import io
import logging
import queue
import re
import threading
import zipfile
from collections.abc import Callable
from datetime import date, datetime
from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from iwanttowatch.catalog import LOOKUP_CACHE, ensure_title, find_by_title, is_tv_show
from iwanttowatch.db import utcnow
from iwanttowatch.models import ImportJob, ImportRow, UserTitle
from iwanttowatch.taste import (
    mark_persona_stale,
    refresh_persona_quietly,
    refresh_reaction_ratings,
)
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
    if {"Title", "Date"} <= header:
        return "netflix", _parse_netflix(rows)
    raise ImportFormatError(
        f"{filename} doesn't look like an IMDb ratings export, a Letterboxd export, "
        "or a Netflix viewing history (Viewing activity → Download all)"
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


# A part of a Netflix title that marks an episode, as in "Dark: Season 1: Secrets".
# Not "Part" or "Chapter" alone: films such as "Dune: Part Two" and "KGF: Chapter 2" use them.
NETFLIX_SERIES_MARK = re.compile(
    r"^(season|series|volume|collection|book) \d+$|^(limited series|miniseries)$", re.I
)


def _parse_netflix(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    """One row per film from NetflixViewingHistory.csv, with each series as one skipped row.

    The file has only a title and the last date it was watched, so films are matched by
    title, made no later than that date.
    """
    dates = _netflix_dates([r.get("Date", "") for r in rows])
    films: dict[str, dict[str, Any]] = {}
    for r, watched in zip(rows, dates, strict=True):
        title = (r.get("Title") or "").strip()
        if not title:
            continue
        parts = title.split(": ")
        marks = [i for i, part in enumerate(parts) if i and NETFLIX_SERIES_MARK.match(part)]
        series = bool(marks) or len(parts) >= 3
        name = ": ".join(parts[: marks[0]]) if marks else parts[0] if series else title
        film = films.setdefault(
            f"{series}|{name}",
            {
                "title": name,
                "year": None,
                "rating": None,
                "rated_at": None,
                "watched_at": None,
                "liked": False,
                "title_type": "TV series" if series else "movie",
            },
        )
        if watched and (film["watched_at"] is None or watched > film["watched_at"]):
            film["watched_at"] = watched
    return list(films.values())


def _netflix_dates(values: list[str]) -> list[str | None]:
    """Parse dates written in the account's locale, such as 12/31/24, 31/12/2024, or 31.12.24.

    Day-first and month-first look alike until the day passes 12, so pick the reading that
    keeps the file in its newest-first order.
    """

    def parse(value: str, day_first: bool) -> str | None:
        try:
            a, b, c = (int(p) for p in re.split(r"[./-]", value.strip()))
            year, month, day = (a, b, c) if a > 31 else (c, b, a) if day_first else (c, a, b)
            return date(year + 2000 if year < 100 else year, month, day).isoformat()
        except ValueError:
            return None

    def disorder(parsed: list[str | None]) -> int:
        known = [d for d in parsed if d]
        rises = sum(newer < older for newer, older in zip(known, known[1:], strict=False))
        return rises + len(parsed) - len(known)

    month_first = [parse(v, False) for v in values]
    day_first = [parse(v, True) for v in values]
    return day_first if disorder(day_first) < disorder(month_first) else month_first


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
    # A film can't have come out after it was watched; Netflix rows have no year besides.
    watched = data.get("watched_at")
    latest = int(watched[:4]) if watched else None
    tmdb_id, candidates = find_by_title(tmdb, data["title"], data.get("year"), latest)
    if tmdb_id is not None:
        apply_match(session, tmdb, job, row, tmdb_id)
    elif (
        job.source == "netflix"
        and ": " in data["title"]
        and is_tv_show(tmdb, data["title"].split(": ")[0])
    ):
        # An episode of a show without seasons, such as "Our Planet: Jungles".
        row.status, row.message = "skipped", "TV series: iWantToWatch only handles movies"
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

    def __init__(
        self,
        engine: Engine,
        tmdb_base_url: str,
        on_done: Callable[[int], None] | None = None,
    ) -> None:
        self._engine = engine
        self._tmdb_base_url = tmdb_base_url
        # Called with the user's ID when one of their imports completes.
        self._on_done = on_done
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
                with Session(self._engine) as session:
                    job = session.get(ImportJob, job_id)
                    if job is not None and job.status == "done":
                        # New ratings can change the scale that reactions are read against.
                        if refresh_reaction_ratings(session, job.user_id):
                            session.commit()
                        if self._on_done:
                            self._on_done(job.user_id)
            except Exception:
                log.exception("Import job %s crashed", job_id)
                with Session(self._engine) as session:
                    job = session.get(ImportJob, job_id)
                    if job is not None:
                        job.status, job.error = "failed", "Unexpected error; see the server log"
                        session.commit()
            finally:
                self._queue.task_done()
