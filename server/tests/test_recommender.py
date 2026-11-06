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


def test_percentiles_lean_on_a_typical_rater_until_the_user_has_rated_enough() -> None:
    # A new user who loved all seven films they rated: favourites, not their average.
    few = percentiles({i: 9.5 for i in range(7)})
    assert len(set(few.values())) == 1 and few[0] > 0.75
    # A generous rater with many ratings: their 9s are their ordinary films.
    generous = percentiles({i: 9.0 if i < 100 else 10.0 for i in range(200)})
    assert 0.2 < generous[0] < 0.35 and generous[150] > 0.7


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


def test_quality_is_judged_within_a_language_only_when_it_has_enough_films() -> None:
    def voted(tmdb_id: int, lang: str, average: float, votes: int) -> Title:
        return Title(
            tmdb_id=tmdb_id, title=str(tmdb_id), original_title=str(tmdb_id),
            original_language=lang, genres=[], keywords=[], directors=[], writers=[], cast=[],
            vote_average=average, vote_count=votes,
        )  # fmt: skip

    # English films rated 6.0–7.95 with 150 to 3,000 votes, Malayalam ones with about 50.
    titles = {i: voted(i, "en", 6.0 + i / 20, 150 + (i * 397) % 2850) for i in range(40)}
    titles[100] = voted(100, "en", 8.5, 30000)
    titles |= {200 + i: voted(200 + i, "ml", 6.5 + i / 20, 40 + i) for i in range(20)}
    titles[300] = voted(300, "ml", 8.2, 60)
    titles[400] = voted(400, "nl", 8.6, 334)  # the only Dutch film
    rank = [s.tmdb_id for s in sorted(score(titles, [], list(titles)), key=lambda s: -s.score)]

    # A well-loved Malayalam film with few votes still ranks high among many films...
    assert rank.index(300) < 3
    # ...but a lone Dutch film isn't judged against Dutch norms made of itself alone,
    # which would put its 334 votes' average above an established 8.5.
    assert rank.index(100) < rank.index(400)


def test_evaluation_compares_with_popularity() -> None:
    titles, ratings = catalogue()
    labels = [Label(i, p) for i, p in percentiles(ratings).items()]
    result = evaluate(titles, labels)
    assert result.held_out == 15
    assert result.model_spearman > 0.7 > result.baseline_spearman
    assert result.model_ndcg > result.baseline_ndcg
