import random
from typing import Any

from iwanttowatch.models import Title
from iwanttowatch.recommender import Label, evaluate, percentiles, score

# Three kinds of film. The user loves Malayalam family dramas by one director and
# dislikes slashers, which are the most popular and best voted on TMDb, so ranking
# by popularity or votes gets this user backwards.
KINDS: dict[str, dict[str, Any]] = {
    "drama": {"lang": "ml", "genres": ["Drama"], "keywords": ["family relationships", "village"],
              "director": (1, "Dileesh Pothan"), "rating": 9, "votes": (7.2, 40), "popularity": 5.0},
    "romcom": {"lang": "hi", "genres": ["Comedy", "Romance"], "keywords": ["wedding", "love"],
               "director": (2, "A Romcom Director"), "rating": 6, "votes": (6.5, 400), "popularity": 30.0},
    "slasher": {"lang": "en", "genres": ["Horror"], "keywords": ["slasher", "gore"],
                "director": (3, "A Horror Director"), "rating": 3, "votes": (7.8, 9000), "popularity": 90.0},
}  # fmt: skip


def film(tmdb_id: int, kind: str, rng: random.Random) -> Title:
    k = KINDS[kind]
    average, votes = k["votes"]
    director_id, director = k["director"]
    # Each film shares its kind's features plus one lead actor from a small pool.
    actor = rng.randrange(4)
    return Title(
        tmdb_id=tmdb_id, title=f"{kind.title()} {tmdb_id}", original_title=f"{kind} {tmdb_id}",
        original_language=k["lang"], genres=k["genres"], keywords=k["keywords"],
        directors=[{"id": director_id, "name": director}], writers=[],
        cast=[{"id": 100 * director_id + actor, "name": f"Actor {actor} of {kind}"}],
        year=2000 + rng.randrange(25), vote_average=average + rng.uniform(-0.3, 0.3),
        vote_count=votes, popularity=k["popularity"] * rng.uniform(0.8, 1.2),
    )  # fmt: skip


def catalogue() -> tuple[dict[int, Title], dict[int, float]]:
    rng = random.Random(1)
    titles: dict[int, Title] = {}
    ratings: dict[int, float] = {}
    for n in range(90):
        kind = ("drama", "romcom", "slasher")[n % 3]
        titles[n] = film(n, kind, rng)
        if n < 75:
            ratings[n] = KINDS[kind]["rating"] + rng.choice([-1, 0, 0, 1])
    return titles, ratings


def test_percentiles_share_ranks_for_ties() -> None:
    assert percentiles({1: 3.0, 2: 8.0, 3: 8.0, 4: 10.0}) == {1: 0.125, 2: 0.5, 3: 0.5, 4: 0.875}


def test_scores_follow_the_users_taste_not_popularity() -> None:
    titles, ratings = catalogue()
    labels = [Label(i, p) for i, p in percentiles(ratings).items()]
    unseen = [i for i in titles if i not in ratings]
    scored = score(titles, labels, unseen)

    by_kind: dict[str, list[float]] = {}
    for s in scored:
        by_kind.setdefault(titles[s.tmdb_id].original_title.split()[0], []).append(s.score)
    assert min(by_kind["drama"]) > max(by_kind["romcom"]) > 0
    assert min(by_kind["romcom"]) > max(by_kind["slasher"])
    drama = next(s for s in scored if s.tmdb_id in unseen and titles[s.tmdb_id].genres == ["Drama"])
    assert drama.score > 0.7
    assert drama.reasons[0] == "You like films directed by Dileesh Pothan"
    assert drama.reasons[1].startswith("Like Drama ") and drama.reasons[1].endswith(
        ", which you rated highly"
    )


def test_evaluation_compares_with_popularity() -> None:
    titles, ratings = catalogue()
    labels = [Label(i, p) for i, p in percentiles(ratings).items()]
    result = evaluate(titles, labels)
    assert result.held_out == 15
    assert result.model_spearman > 0.7 > result.baseline_spearman
    assert result.model_ndcg > result.baseline_ndcg
