"""Backups of the whole server's database, for admins."""

from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel

from iwanttowatch.api.deps import AdminUser
from iwanttowatch.backups import EVERY, KEEP, NAME, Backup, back_up, list_backups

router = APIRouter(prefix="/api/v1/backups")


class BackupOut(BaseModel):
    name: str
    created_at: datetime
    size: int


class Backups(BaseModel):
    # The folder inside the container, such as /data/backups.
    folder: str
    keep: int
    every_hours: int
    backups: list[BackupOut]


def _out(backup: Backup) -> BackupOut:
    return BackupOut(name=backup.name, created_at=backup.created_at, size=backup.size)


def _backups(request: Request) -> Backups:
    folder = request.app.state.backup_dir
    return Backups(
        folder=str(folder.resolve()),
        keep=KEEP,
        every_hours=int(EVERY.total_seconds() // 3600),
        backups=[_out(b) for b in list_backups(folder)],
    )


@router.get("")
def read_backups(_admin: AdminUser, request: Request) -> Backups:
    """The database backups, newest first, taken every day and before each upgrade."""
    return _backups(request)


@router.post("")
def create_backup(_admin: AdminUser, request: Request) -> Backups:
    """Back up the database now; the oldest backup beyond the kept number is deleted."""
    try:
        back_up(request.app.state.engine, request.app.state.backup_dir)
    except OSError as error:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, f"Couldn't write the backup: {error}"
        ) from error
    return _backups(request)


@router.get("/{name}", response_class=FileResponse)
def download_backup(name: str, _admin: AdminUser, request: Request) -> FileResponse:
    """Download one backup. It holds every user's data, including password hashes."""
    path = request.app.state.backup_dir / name
    if not NAME.match(name) or not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such backup")
    return FileResponse(path, media_type="application/vnd.sqlite3", filename=name)
