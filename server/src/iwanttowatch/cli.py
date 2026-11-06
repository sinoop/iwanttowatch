import argparse
import dataclasses
import json
import sys
import tempfile
from pathlib import Path

import uvicorn
from sqlalchemy import select
from sqlalchemy.orm import Session

from iwanttowatch.config import Settings
from iwanttowatch.db import create_db_engine
from iwanttowatch.feed import user_labels
from iwanttowatch.main import create_app
from iwanttowatch.models import Title, User
from iwanttowatch.recommender import evaluate


def main() -> None:
    parser = argparse.ArgumentParser(prog="iwanttowatch")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("serve", help="run the web server")
    commands.add_parser("openapi", help="print the OpenAPI schema as JSON")
    evaluate_parser = commands.add_parser(
        "eval", help="compare a user's recommendations with a popularity baseline"
    )
    evaluate_parser.add_argument("username")
    args = parser.parse_args()

    if args.command == "serve":
        settings = Settings()
        uvicorn.run(create_app(settings), host=settings.host, port=settings.port)
    elif args.command == "openapi":
        with tempfile.TemporaryDirectory() as data_dir:
            app = create_app(Settings(data_dir=Path(data_dir), static_dir=None))
            json.dump(app.openapi(), sys.stdout, indent=2)
            sys.stdout.write("\n")
    elif args.command == "eval":
        _evaluate(Settings(), args.username)


def _evaluate(settings: Settings, username: str) -> None:
    """Hold out 20% of the user's ratings and report how well each ranking predicts them:
    Spearman correlation and NDCG@20 (1.0 is perfect)."""
    engine = create_db_engine(settings.database_url)
    with Session(engine) as session:
        user = session.scalar(select(User).where(User.username == username))
        if user is None:
            sys.exit(f"No user named {username!r}")
        labels = user_labels(session, user.id)
        titles = {
            t.tmdb_id: t
            for t in session.scalars(
                select(Title).where(Title.tmdb_id.in_([label.tmdb_id for label in labels]))
            )
        }
        if sum(label.explicit for label in labels) < 10:
            sys.exit("Rate at least 10 films first")
        result = evaluate(titles, labels)
    json.dump(dataclasses.asdict(result), sys.stdout, indent=2)
    sys.stdout.write("\n")
