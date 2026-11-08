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


def test_quality_prefers_imdb_and_judges_a_language_only_with_enough_films() -> None:
    def voted(
        tmdb_id: int, lang: str, average: float, votes: int, imdb: tuple[float, int] | None = None
    ) -> Title:
        return Title(
            tmdb_id=tmdb_id, title=str(tmdb_id), original_title=str(tmdb_id),
            original_language=lang, genres=[], keywords=[], directors=[], writers=[], cast=[],
            vote_average=average, vote_count=votes,
            imdb_rating=imdb[0] if imdb else None, imdb_votes=imdb[1] if imdb else None,
        )  # fmt: skip

    # English films rated 6.0–7.95 with 150 to 3,000 votes, Malayalam ones with about 50.
    titles = {i: voted(i, "en", 6.0 + i / 20, 150 + (i * 397) % 2850) for i in range(40)}
    titles[100] = voted(100, "en", 8.5, 30000)
    titles |= {200 + i: voted(200 + i, "ml", 6.5 + i / 20, 40 + i) for i in range(20)}
    titles[300] = voted(300, "ml", 8.2, 60)
    titles[400] = voted(400, "nl", 8.6, 334)  # the only Dutch film
    # IMDb's far larger vote outweighs TMDb's: a few fans' 8.8 is IMDb's 6.7.
    titles[500] = voted(500, "en", 8.8, 975, imdb=(6.7, 9925))
    titles[501] = voted(501, "en", 7.0, 200, imdb=(8.6, 20000))
    rank = [s.tmdb_id for s in sorted(score(titles, [], list(titles)), key=lambda s: -s.score)]

    # A well-loved Malayalam film with few votes still ranks high among many films...
    assert rank.index(300) < 4
    # ...but a lone Dutch film isn't judged against Dutch norms made of itself alone,
    # which would put its 334 votes' average above an established 8.5.
    assert rank.index(100) < rank.index(400)
    assert rank.index(501) < 3 and rank.index(500) > 20


def test_films_from_before_the_birth_year_lose_match_unless_films_from_then_were_liked() -> None:
    titles, ratings = catalogue()  # films from 2000 to 2024
    born = 2012
    unseen = [i for i in titles if i not in ratings]
    every_label = [Label(i, p) for i, p in percentiles(ratings).items()]
    # The same ratings minus those of films from before the birth year.
    recent_labels = [x for x in every_label if (titles[x.tmdb_id].year or 0) >= born]

    def drops(labels: list[Label], born: int = born) -> dict[int, float]:
        before = {s.tmdb_id: s.score for s in score(titles, labels, unseen)}
        after = {s.tmdb_id: s.score for s in score(titles, labels, unseen, born)}
        return {i: before[i] - after[i] for i in unseen if before[i] > 0.2}

    recent = drops(recent_labels)
    by_age = sorted(recent, key=lambda i: titles[i].year or 0)
    assert all(recent[i] == 0 for i in by_age if (titles[i].year or 0) >= born)
    older = [i for i in by_age if (titles[i].year or 0) < born]
    assert older and all(0 < recent[i] <= 0.15 for i in older)
    # Older films lose more.
    assert all(recent[a] >= recent[b] - 1e-9 for a, b in zip(older, older[1:], strict=False))
    assert recent[older[0]] > recent[older[-1]]
    # Having liked films from before the birth year shrinks the penalty.
    liked = drops(every_label)
    assert all(liked[i] < recent[i] for i in older)

    # Born in 2024, having liked films from 2020 on: they soften the penalty for films
    # from the 2010s but not for films from twenty years before, which lose it all.
    late = [x for x in every_label if (titles[x.tmdb_id].year or 0) >= 2020]
    assert any(x.value >= 0.6 for x in late)
    with_late, without = drops(late, 2024), drops([], 2024)
    early = [i for i in with_late if (titles[i].year or 0) <= 2004 and i in without]
    assert early and all(abs(with_late[i] - 0.15) < 1e-9 for i in early)
    assert all(abs(without[i] - 0.15) < 1e-9 for i in early)
    near = [i for i in with_late if 2010 <= (titles[i].year or 0) <= 2019 and i in without]
    assert near and all(with_late[i] < without[i] - 1e-6 for i in near)


def test_evaluation_compares_with_popularity() -> None:
    titles, ratings = catalogue()
    labels = [Label(i, p) for i, p in percentiles(ratings).items()]
    result = evaluate(titles, labels)
    assert result.held_out == 15
    assert result.model_spearman > 0.7 > result.baseline_spearman
    assert result.model_ndcg > result.baseline_ndcg
