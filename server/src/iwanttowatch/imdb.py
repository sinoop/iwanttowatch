"""IMDb ratings from IMDb's non-commercial datasets, for judging films' quality.

TMDb's own votes are few (a median of a few dozen for Malayalam films), so a handful
of fans can put a film at 8.8. IMDb publishes every title's weighted rating and vote
count as a daily file, free for personal and non-commercial use. An admin turns it on
in Settings; the file is downloaded at most daily, during feed builds, and only the
ratings of films in the catalogue are kept.
"""

import gzip
import logging
import os
from datetime import timedelta
from pathlib import Path

import httpx
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from iwanttowatch.db import utcnow
from iwanttowatch.models import ConnectorStatus, Title, get_setting

log = logging.getLogger(__name__)

RATINGS_URL = "https://datasets.imdbws.com/title.ratings.tsv.gz"
SETTING = "imdb_ratings"
STATUS_KEY = "imdb"
REFRESH_AFTER = timedelta(hours=20)
TIMEOUT_SECONDS = 120


def enabled(session: Session) -> bool:
    return get_setting(session, SETTING) == "on"


def ratings_file(data_dir: Path) -> Path:
    return data_dir / "imdb-title-ratings.tsv.gz"


def lookup_rating(data_dir: Path, imdb_id: str) -> tuple[float, int] | None:
    """Look up a single title's rating and votes from the local IMDb ratings dataset."""
    path = ratings_file(data_dir)
    if not path.exists():
        return None
    prefix = (imdb_id + "\t").encode("ascii")
    try:
        with gzip.open(path, "rb") as lines:
            for line in lines:
                if line.startswith(prefix):
                    parts = line.rstrip(b"\r\n").split(b"\t")
                    if len(parts) >= 3:
                        return float(parts[1]), int(parts[2])
                    break
    except (OSError, ValueError) as error:
        log.warning("Reading IMDb ratings file failed for %s: %s", imdb_id, error)
    return None


def ensure_title_rating(session: Session, data_dir: Path, title: Title) -> None:
    """If IMDb ratings are enabled and this title has an imdb_id but no rating yet,
    look it up in the dataset and store it on the title."""
    if (
        not enabled(session)
        or not title.imdb_id
        or title.imdb_rating is not None
        or title.imdb_votes is not None
    ):
        return
    path = ratings_file(data_dir)
    if not path.exists():
        try:
            _download(path)
        except (httpx.HTTPError, OSError) as error:
            log.warning("Downloading IMDb ratings failed: %s", error)
            return
    rating_info = lookup_rating(data_dir, title.imdb_id)
    if rating_info is not None:
        title.imdb_rating, title.imdb_votes = rating_info
        session.commit()
    else:
        # Mark as checked (0 votes) so we don't scan repeatedly for missing films.
        title.imdb_votes = 0
        session.commit()


def update_ratings(session: Session, data_dir: Path) -> None:
    """Download IMDb's ratings when the local copy is old, then copy the rating and
    vote count of every film in the catalogue onto its title."""
    path = ratings_file(data_dir)
    state = session.get(ConnectorStatus, STATUS_KEY) or ConnectorStatus(connector=STATUS_KEY)
    session.add(state)
    age = utcnow().timestamp() - path.stat().st_mtime if path.exists() else None
    if age is None or age > REFRESH_AFTER.total_seconds():
        try:
            _download(path)
            state.synced_at, state.error = utcnow(), None
        except (httpx.HTTPError, OSError) as error:
            log.warning("Downloading IMDb ratings failed: %s", error)
            state.error = "Couldn't download IMDb's ratings; using the last copy"
    if not path.exists():
        session.commit()
        return

    wanted = dict(
        session.execute(
            select(Title.imdb_id, Title.tmdb_id).where(Title.imdb_id.is_not(None))
        ).all()
    )
    found = []
    with gzip.open(path, "rt", encoding="utf-8") as lines:
        next(lines)  # tconst, averageRating, numVotes
        for line in lines:
            imdb_id, rating, votes = line.rstrip("\n").split("\t")
            if (tmdb_id := wanted.get(imdb_id)) is not None:
                found.append(
                    {"tmdb_id": tmdb_id, "imdb_rating": float(rating), "imdb_votes": int(votes)}
                )
    if found:
        session.execute(update(Title), found)
    session.commit()


def forget_ratings(session: Session, data_dir: Path) -> None:
    """Remove every IMDb rating, for when an admin turns them off."""
    session.execute(update(Title).values(imdb_rating=None, imdb_votes=None))
    if (state := session.get(ConnectorStatus, STATUS_KEY)) is not None:
        session.delete(state)
    session.commit()
    ratings_file(data_dir).unlink(missing_ok=True)


def _download(path: Path) -> None:
    partial = path.with_suffix(".part")
    with httpx.stream("GET", RATINGS_URL, timeout=TIMEOUT_SECONDS, follow_redirects=True) as r:
        r.raise_for_status()
        with partial.open("wb") as out:
            for chunk in r.iter_bytes():
                out.write(chunk)
    os.replace(partial, path)
