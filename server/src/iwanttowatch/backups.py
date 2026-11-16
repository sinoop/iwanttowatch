"""Copies of the whole database, taken every day and before each upgrade.

SQLite's backup API copies a consistent snapshot while the app keeps running. The
copies go to `backups/` in the data folder, or to IWANTTOWATCH_BACKUP_DIR (say, a
share on another disk); the newest few are kept. Restoring is manual: stop the
container and put a copy in place of iwanttowatch.db.
"""

import logging
import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from iwanttowatch.db import utcnow
from iwanttowatch.models import (
    AiPick,
    ApiCache,
    Availability,
    Explanation,
    Feedback,
    GroupShortlistItem,
    Invite,
    LibraryItem,
    OpinionClash,
    OutlierReview,
    RatingPrompt,
    Recommendation,
    ScopedFeedItem,
    ShortlistItem,
    Title,
    UserTitle,
    VoteSession,
    get_setting,
    set_setting,
)

log = logging.getLogger(__name__)

KEEP = 7
EVERY = timedelta(days=1)
CHECK_EVERY_SECONDS = 3600
# iwanttowatch-20261108-093000.db, or …-before-upgrade.db for the copy taken before migrations.
NAME = re.compile(r"^iwanttowatch-(\d{8}-\d{6})(-before-upgrade)?\.db$")


@dataclass(frozen=True)
class Backup:
    name: str
    created_at: datetime
    size: int


def list_backups(folder: Path) -> list[Backup]:
    """The backups in the folder, newest first."""
    found = []
    for path in folder.glob("iwanttowatch-*.db"):
        if match := NAME.match(path.name):
            created = datetime.strptime(match[1], "%Y%m%d-%H%M%S").replace(tzinfo=UTC)
            found.append(Backup(path.name, created, path.stat().st_size))
    return sorted(found, key=lambda b: b.name, reverse=True)


def back_up(engine: Engine, folder: Path, before_upgrade: bool = False) -> Backup:
    """Copy the database into the folder, then delete all but the newest KEEP copies."""
    folder.mkdir(parents=True, exist_ok=True)
    suffix = "-before-upgrade" if before_upgrade else ""
    name = f"iwanttowatch-{utcnow():%Y%m%d-%H%M%S}{suffix}.db"
    partial = folder / f".{name}.partial"
    raw = engine.raw_connection()
    try:
        target = sqlite3.connect(partial)
        try:
            raw.driver_connection.backup(target)  # type: ignore[union-attr]
        finally:
            target.close()
    finally:
        raw.close()
    # Renamed only once complete, so a crash never leaves a half-written backup.
    partial.replace(folder / name)
    for old in list_backups(folder)[KEEP:]:
        (folder / old.name).unlink(missing_ok=True)
    return next(b for b in list_backups(folder) if b.name == name)


DB_COMPACT_ENABLED_SETTING = "db_compact_enabled"
DB_COMPACT_DAYS_SETTING = "db_compact_days"
DB_COMPACT_LAST_AT_SETTING = "db_compact_last_at"
DEFAULT_COMPACT_DAYS = 30


@dataclass(frozen=True)
class CompactionResult:
    titles_removed: int
    availability_removed: int
    cache_removed: int
    size_before: int
    size_after: int


def db_size_bytes(engine: Engine) -> int:
    """Return the current SQLite database size in bytes."""
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        page_count = int(cur.execute("PRAGMA page_count").fetchone()[0])
        page_size = int(cur.execute("PRAGMA page_size").fetchone()[0])
        return page_count * page_size
    finally:
        raw.close()


def _protected_tmdb_ids(session: Session) -> set[int]:
    """All TMDb IDs actively referenced by user ratings, feeds, libraries, or AI notes."""
    ids: set[int] = set()
    queries = (
        select(UserTitle.tmdb_id),
        select(LibraryItem.tmdb_id).where(LibraryItem.tmdb_id.is_not(None)),
        select(RatingPrompt.tmdb_id),
        select(Recommendation.tmdb_id),
        select(ScopedFeedItem.tmdb_id),
        select(Feedback.tmdb_id),
        select(ShortlistItem.tmdb_id),
        select(GroupShortlistItem.tmdb_id),
        select(AiPick.tmdb_id),
        select(OutlierReview.tmdb_id),
        select(Explanation.tmdb_id),
        select(OpinionClash.tmdb_id),
    )
    for q in queries:
        for val in session.scalars(q):
            if val is not None:
                ids.add(int(val))
    return ids


def compact_database(
    engine: Engine, retention_days: int = DEFAULT_COMPACT_DAYS
) -> CompactionResult:
    """Prune unreferenced cached titles/availability/expired cache rows and VACUUM SQLite."""
    days = max(1, min(365, retention_days))
    cutoff = utcnow() - timedelta(days=days)
    size_before = db_size_bytes(engine)

    with Session(engine) as session:
        protected = _protected_tmdb_ids(session)
        title_cond = Title.fetched_at < cutoff
        if protected:
            title_cond = title_cond & Title.tmdb_id.not_in(protected)
        titles_res = session.execute(delete(Title).where(title_cond))
        titles_removed = int(getattr(titles_res, "rowcount", 0) or 0)

        # Re-read remaining titles so orphaned availability rows are also cleaned up.
        remaining_titles = select(Title.tmdb_id)
        avail_cond = (Availability.tmdb_id.not_in(remaining_titles)) | (
            (Availability.checked_at < cutoff)
            & (Availability.tmdb_id.not_in(protected) if protected else True)
        )
        avail_res = session.execute(delete(Availability).where(avail_cond))
        availability_removed = int(getattr(avail_res, "rowcount", 0) or 0)

        now = utcnow()
        cache_res = session.execute(delete(ApiCache).where(ApiCache.expires_at <= now))
        invite_res = session.execute(delete(Invite).where(Invite.expires_at < now))
        vote_res = session.execute(delete(VoteSession).where(VoteSession.expires_at < now))
        cache_removed = (
            int(getattr(cache_res, "rowcount", 0) or 0)
            + int(getattr(invite_res, "rowcount", 0) or 0)
            + int(getattr(vote_res, "rowcount", 0) or 0)
        )
        set_setting(session, DB_COMPACT_LAST_AT_SETTING, now.isoformat())
        session.commit()

    raw = engine.raw_connection()
    try:
        driver = raw.driver_connection
        if driver is not None:
            prev_isolation = getattr(driver, "isolation_level", None)
            try:
                driver.isolation_level = None
                driver.execute("VACUUM")
            finally:
                driver.isolation_level = prev_isolation
    finally:
        raw.close()

    size_after = db_size_bytes(engine)
    return CompactionResult(
        titles_removed=titles_removed,
        availability_removed=availability_removed,
        cache_removed=cache_removed,
        size_before=size_before,
        size_after=size_after,
    )


class BackupWorker:
    """Takes a backup when the newest is a day old, checking every hour."""

    def __init__(self, engine: Engine, folder: Path) -> None:
        self._engine = engine
        self._folder = folder

    def start(self) -> None:
        threading.Thread(target=self._loop, name="backups", daemon=True).start()

    def _loop(self) -> None:
        while True:
            try:
                newest = next(iter(list_backups(self._folder)), None)
                if newest is None or utcnow() - newest.created_at >= EVERY:
                    with Session(self._engine) as session:
                        auto_compact = get_setting(session, DB_COMPACT_ENABLED_SETTING) == "on"
                        raw_days = get_setting(session, DB_COMPACT_DAYS_SETTING)
                        days = (
                            int(raw_days)
                            if raw_days and raw_days.isdigit()
                            else DEFAULT_COMPACT_DAYS
                        )
                    if auto_compact:
                        compact_database(self._engine, days)
                    back_up(self._engine, self._folder)
            except (OSError, sqlite3.Error):
                log.exception("Couldn't back up the database to %s", self._folder)
            time.sleep(CHECK_EVERY_SECONDS)
