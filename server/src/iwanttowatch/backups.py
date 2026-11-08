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

from sqlalchemy import Engine

from iwanttowatch.db import utcnow

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
                    back_up(self._engine, self._folder)
            except (OSError, sqlite3.Error):
                log.exception("Couldn't back up the database to %s", self._folder)
            time.sleep(CHECK_EVERY_SECONDS)
