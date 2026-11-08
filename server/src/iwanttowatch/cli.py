import argparse
import dataclasses
import json
import random
import sys
import tempfile
from pathlib import Path

import numpy as np
import uvicorn
from sqlalchemy import select
from sqlalchemy.orm import Session

from iwanttowatch.config import Settings
from iwanttowatch.db import create_db_engine
from iwanttowatch.feed import user_labels
from iwanttowatch.llm import LlmError, provider_from_settings
from iwanttowatch.main import create_app
from iwanttowatch.models import Title, User
from iwanttowatch.recommender import evaluate, percentile_of, percentiles, score, spearman
from iwanttowatch.taste import effective_ratings, review_films


def main() -> None:
    parser = argparse.ArgumentParser(prog="iwanttowatch")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("serve", help="run the web server")
    commands.add_parser("openapi", help="print the OpenAPI schema as JSON")
    evaluate_parser = commands.add_parser(
        "eval", help="compare a user's recommendations with a popularity baseline"
    )
    evaluate_parser.add_argument("username")
    llm_parser = commands.add_parser(
        "eval-llm",
        help="check the configured LLM's predicted ratings against held-out ratings",
    )
    llm_parser.add_argument("username")
    llm_parser.add_argument("--films", type=int, default=30)
    llm_parser.add_argument("--seed", type=int, default=0, help="which films to hold out")
    args = parser.parse_args()

    if args.command == "serve":
        settings = Settings()
        uvicorn.run(create_app(settings), host=settings.host, port=settings.port)
    elif args.command == "openapi":
        with tempfile.TemporaryDirectory() as data_dir:
            app = create_app(Settings(data_dir=Path(data_dir), static_dir=None))
            json.dump(app.openapi(), sys.stdout, indent=2)
            sys.stdout.write("\n")
            app.state.engine.dispose()
    elif args.command == "eval":
        _evaluate(Settings(), args.username)
    elif args.command == "eval-llm":
        _evaluate_llm(Settings(), args.username, args.films, args.seed)


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


def _evaluate_llm(settings: Settings, username: str, films: int, seed: int) -> None:
    """Hide some of the user's ratings from both the recommender and the LLM, have each
    predict them, and report how well each, and blends of the two, match the truth:
    Spearman correlation (1.0 is perfect) and mean error in percentile points."""
    engine = create_db_engine(settings.database_url)
    with Session(engine) as session:
        user = session.scalar(select(User).where(User.username == username))
        if user is None:
            sys.exit(f"No user named {username!r}")
        llm = provider_from_settings(session, "check", user.id)
        if llm is None:
            sys.exit("Connect Ollama or Gemini in Settings first")
        effective = effective_ratings(user.id)
        ratings = dict(session.execute(select(effective.c.tmdb_id, effective.c.rating)).all())
        labels = user_labels(session, user.id)
        titles = {
            t.tmdb_id: t
            for t in session.scalars(
                select(Title).where(Title.tmdb_id.in_([label.tmdb_id for label in labels]))
            )
        }
        rated = sorted(i for i in ratings if i in titles)
        if len(rated) < films + 10:
            sys.exit(f"Rate at least {films + 10} films first")
        held = random.Random(seed).sample(rated, films)
        train = [label for label in labels if label.tmdb_id not in held]
        model = {s.tmdb_id: s.score for s in score(titles, train, held)}
        try:
            review = review_films(session, user.id, llm, [titles[i] for i in held], exclude=held)
        except LlmError as error:
            sys.exit(str(error))
        if review is None:
            sys.exit("Too few ratings for the LLM")
    rest = [r for i, r in ratings.items() if i not in held]
    truth = percentiles(ratings)
    answered = [i for i in held if i in review.ratings]
    ai = {i: percentile_of(rest, review.ratings[i].rating) for i in answered}
    actual = np.array([truth[i] for i in answered])

    def report(predicted: list[float]) -> dict[str, float]:
        values = np.array(predicted)
        return {
            "spearman": round(spearman(values, actual), 3),
            "mean_error": round(float(np.abs(values - actual).mean()) * 100, 1),
        }

    result: dict[str, object] = {
        "held_out": films,
        "answered": len(answered),
        "ai_rating_mean_error": round(
            float(np.mean([abs(review.ratings[i].rating - ratings[i]) for i in answered])), 2
        ),
        "recommender": report([model[i] for i in answered]),
        "ai": report([ai[i] for i in answered]),
        "always_median": report([0.5] * len(answered)),
    }
    for weight in (0.25, 0.5, 0.75):
        result[f"blend_ai_{weight}"] = report(
            [(1 - weight) * model[i] + weight * ai[i] for i in answered]
        )
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
