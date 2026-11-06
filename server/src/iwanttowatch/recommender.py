"""Taste scoring: predicting how much a user will like films they haven't seen.

Every film becomes a sparse vector of what it is made of: genres, TMDb keywords,
directors, writers, lead cast, original language, and decade, weighted by how rare
each feature is. Labels are the user's own ratings as percentiles of how they rate,
so a generous and a harsh rater are comparable (Criticker-style). Three signals
score a candidate:

- neighbours: the similarity-weighted average label of the user's most similar
  rated films, which explains itself ("like X, which you rated highly");
- ridge regression over the features, which learns preferences such as a director
  or a disliked theme;
- a quality prior: TMDb's vote average judged within the film's own language, so a
  well-loved regional film with few votes isn't treated as obscure.

Cross-validation on the user's ratings picks how to blend the three and calibrates
the blend, so a match of 80% means "likely in the top 20% of what you've rated".
"""

import math
import random
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from statistics import median

import numpy as np
from numpy.typing import NDArray

from iwanttowatch.models import Title

Floats = NDArray[np.float64]

MAX_FEATURES = 2000
FEATURE_WEIGHTS = {
    "genre": 1.0,
    "keyword": 1.0,
    "director": 1.5,
    "writer": 1.0,
    "cast": 1.0,
    "language": 1.0,
    "decade": 0.5,
}
NEIGHBOURS = 20
# Pulls predictions from few or weak neighbours towards the user's average.
NEIGHBOUR_SHRINK = 1.0
RIDGE_ALPHA = 1.0
BASELINE_WEIGHT = 5.0
FOLDS = 5
MIN_RATINGS_FOR_CV = 15
# (neighbours, ridge, quality) weights tried by cross-validation.
BLENDS = [(1, 0, 0), (0, 1, 0), (0.5, 0.5, 0), (0.4, 0.4, 0.2), (0.3, 0.3, 0.4), (0.2, 0.2, 0.6)]
COLD_START_BLEND = (0.3, 0.3, 0.4)
MAX_REASONS = 2
DIVERSIFY_TOP = 200
# How much diversity re-ranking trades score for variety (1 = none).
DIVERSITY_LAMBDA = 0.8
PERSON_VERBS = {"director": "directed by", "writer": "written by", "cast": "starring"}


@dataclass(frozen=True)
class Label:
    tmdb_id: int
    # Percentile among the user's ratings, 0–1.
    value: float
    # 1 for ratings; less for implicit signals such as a favourite or a watch.
    weight: float = 1.0
    explicit: bool = True


@dataclass(frozen=True)
class Scored:
    tmdb_id: int
    # Calibrated predicted percentile, 0–1: the match percentage divided by 100.
    score: float
    reasons: list[str] = field(default_factory=list)


# How a typical person spreads ratings over 1–10 (roughly IMDb's), standing in for
# the user's own spread until they have rated enough films. Without it, a new user
# who loved all seven films they rated would have them all at the 50th percentile.
TYPICAL_RATINGS = {
    1: 0.01, 2: 0.01, 3: 0.02, 4: 0.04, 5: 0.07, 6: 0.13, 7: 0.22, 8: 0.25, 9: 0.15, 10: 0.10
}  # fmt: skip
TYPICAL_WEIGHT = 20


def percentiles(ratings: dict[int, float]) -> dict[int, float]:
    """Each rating's percentile among the user's ratings (ties count half), blended
    with a typical rater's spread worth TYPICAL_WEIGHT ratings."""
    values = np.array(list(ratings.values()), dtype=np.float64)

    def below(r: float) -> float:
        own = (values < r).sum() + 0.5 * (values == r).sum()
        typical = sum(w if v < r else w / 2 if v == r else 0.0 for v, w in TYPICAL_RATINGS.items())
        return float((own + TYPICAL_WEIGHT * typical) / (len(values) + TYPICAL_WEIGHT))

    return {i: below(r) for i, r in ratings.items()}


def _features(title: Title) -> dict[str, str]:
    """Feature key → how to name it in a reason."""
    found = {f"genre:{g}": g for g in title.genres}
    found |= {f"keyword:{k}": k for k in title.keywords[:25]}
    for kind, people in (
        ("director", title.directors[:2]),
        ("writer", title.writers[:3]),
        ("cast", title.cast[:5]),
    ):
        found |= {f"{kind}:{p['id']}": p["name"] for p in people}
    found[f"language:{title.original_language}"] = title.original_language
    if title.year:
        found[f"decade:{title.year // 10 * 10}"] = f"{title.year // 10 * 10}s"
    return found


class Vectors:
    """TF-IDF vectors of films over the features at least two of them share."""

    def __init__(self, titles: Sequence[Title]) -> None:
        found = [_features(t) for t in titles]
        counts = Counter(key for f in found for key in f)
        vocab = [key for key, n in counts.most_common() if n >= 2][:MAX_FEATURES]
        self.index = {key: i for i, key in enumerate(vocab)}
        self.vocab = vocab
        self.names = {key: name for f in found for key, name in f.items() if key in self.index}
        self.rows = {t.tmdb_id: row for row, t in enumerate(titles)}
        n = len(titles)
        idf = np.array([math.log((n + 1) / (counts[k] + 1)) + 1 for k in vocab])
        weight = np.array([FEATURE_WEIGHTS[k.split(":")[0]] for k in vocab])
        matrix = np.zeros((n, len(vocab)), dtype=np.float32)
        for row, f in enumerate(found):
            for key in f:
                if (column := self.index.get(key)) is not None:
                    matrix[row, column] = 1
        matrix *= (idf * weight).astype(np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        self.matrix = matrix / np.where(norms > 0, norms, 1)


def _quality(titles: Sequence[Title]) -> Floats:
    """Each film's percentile by Bayesian-averaged vote, within its own language."""
    by_language: dict[str, list[Title]] = defaultdict(list)
    for t in titles:
        by_language[t.original_language].append(t)
    averages: dict[int, float] = {}
    for group in by_language.values():
        voted = [t for t in group if t.vote_count and t.vote_average is not None]
        mean_vote = sum(t.vote_average or 0 for t in voted) / len(voted) if voted else 6.0
        prior_votes = median(t.vote_count or 0 for t in voted) if voted else 1
        for t in group:
            votes = t.vote_count or 0
            averages[t.tmdb_id] = (votes * (t.vote_average or 0) + prior_votes * mean_vote) / (
                votes + prior_votes or 1
            )
    values = np.array([averages[t.tmdb_id] for t in titles])
    return (_ranks(values) + 0.5) / len(titles)


@dataclass
class _Prediction:
    neighbours: Floats
    ridge: Floats
    # Per target: indices into the training labels of its nearest rated films.
    nearest: NDArray[np.intp]
    similarity: Floats
    coef: Floats


def _predict(vectors: Vectors, train: Sequence[Label], targets: Sequence[int]) -> _Prediction:
    rows = np.array([vectors.rows[label.tmdb_id] for label in train])
    x_train = vectors.matrix[rows].astype(np.float64)
    x_target = vectors.matrix[[vectors.rows[i] for i in targets]].astype(np.float64)
    y = np.array([label.value for label in train])
    w = np.array([label.weight for label in train])
    # Where films unlike anything rated start: the user's average, pulled toward the
    # middle while they have few labels. Otherwise someone who has only rated
    # favourites would see every film start out as a favourite.
    mean = float((w @ y + BASELINE_WEIGHT * 0.5) / (w.sum() + BASELINE_WEIGHT))

    similarity = x_target @ x_train.T
    k = min(NEIGHBOURS, len(train))
    nearest = np.argpartition(-similarity, k - 1, axis=1)[:, :k]
    strength = np.take_along_axis(similarity, nearest, axis=1).clip(min=0) * w[nearest]
    neighbours = ((strength * y[nearest]).sum(axis=1) + NEIGHBOUR_SHRINK * mean) / (
        strength.sum(axis=1) + NEIGHBOUR_SHRINK
    )

    # Weighted ridge regression; solved in whichever of the primal (features) or
    # dual (ratings) form is smaller.
    centred = y - mean
    if len(train) < x_train.shape[1]:
        gram = (x_train @ x_train.T) * w[:, None] + RIDGE_ALPHA * np.eye(len(train))
        coef = x_train.T @ np.linalg.solve(gram, w * centred)
    else:
        weighted = x_train * w[:, None]
        system = x_train.T @ weighted + RIDGE_ALPHA * np.eye(x_train.shape[1])
        coef = np.linalg.solve(system, weighted.T @ centred)
    ridge = mean + x_target @ coef
    return _Prediction(neighbours, ridge, nearest, similarity, coef)


def _choose_blend(
    vectors: Vectors, labels: Sequence[Label], quality: Floats
) -> tuple[tuple[float, float, float], tuple[float, float]]:
    """Blend weights and linear calibration chosen by cross-validation on the ratings."""
    explicit = [label for label in labels if label.explicit]
    if len(explicit) < MIN_RATINGS_FOR_CV:
        return COLD_START_BLEND, (0.0, 1.0)
    order = list(explicit)
    random.Random(0).shuffle(order)
    actual: list[float] = []
    parts: list[Floats] = []
    for fold in range(FOLDS):
        held_out = order[fold::FOLDS]
        held_ids = {label.tmdb_id for label in held_out}
        train = [label for label in labels if label.tmdb_id not in held_ids]
        targets = [label.tmdb_id for label in held_out]
        p = _predict(vectors, train, targets)
        q = quality[[vectors.rows[i] for i in targets]]
        parts.append(np.column_stack([p.neighbours, p.ridge, q]))
        actual.extend(label.value for label in held_out)
    components, truth = np.vstack(parts), np.array(actual)
    blend = max(BLENDS, key=lambda b: spearman(components @ np.array(b), truth))
    predicted = components @ np.array(blend)
    slope, intercept = np.polyfit(predicted, truth, 1) if predicted.std() > 0 else (1.0, 0.0)
    if slope <= 0:
        return blend, (0.0, 1.0)
    return blend, (float(intercept), float(slope))


def score(
    titles: dict[int, Title], labels: Sequence[Label], candidates: Sequence[int]
) -> list[Scored]:
    """Score candidates for a user, most promising first, diversified at the top."""
    labels = [label for label in labels if label.tmdb_id in titles]
    candidates = [i for i in dict.fromkeys(candidates) if i in titles]
    if not candidates:
        return []
    pool = [titles[i] for i in dict.fromkeys([*(label.tmdb_id for label in labels), *candidates])]
    vectors = Vectors(pool)
    quality = _quality(pool)
    candidate_quality = quality[[vectors.rows[i] for i in candidates]]
    if not labels:
        return [Scored(i, float(q)) for i, q in zip(candidates, candidate_quality, strict=True)]

    blend, (intercept, slope) = _choose_blend(vectors, labels, quality)
    p = _predict(vectors, labels, candidates)
    blended = np.column_stack([p.neighbours, p.ridge, candidate_quality]) @ np.array(blend)
    scores = np.clip(intercept + slope * blended, 0.01, 0.99)
    reasons = _reasons(vectors, labels, titles, candidates, p)
    order = _diversify(vectors, candidates, scores)
    return [Scored(candidates[i], float(scores[i]), reasons[i]) for i in order]


def _reasons(
    vectors: Vectors,
    labels: Sequence[Label],
    titles: dict[int, Title],
    candidates: Sequence[int],
    p: _Prediction,
) -> list[list[str]]:
    rated = vectors.matrix[[vectors.rows[label.tmdb_id] for label in labels]] > 0
    liked = np.array([label.explicit and label.value >= 0.6 for label in labels])
    # People the user has rated well at least twice.
    favourite_people = {
        key
        for key, column in vectors.index.items()
        if key.split(":")[0] in PERSON_VERBS and (rated[:, column] & liked).sum() >= 2
    }
    out = []
    for n, tmdb_id in enumerate(candidates):
        x = vectors.matrix[vectors.rows[tmdb_id]]
        reasons = []
        people = [
            (float(x[vectors.index[key]] * p.coef[vectors.index[key]]), key)
            for key in favourite_people
            if x[vectors.index[key]] > 0
        ]
        for contribution, key in sorted(people, reverse=True)[:1]:
            if contribution > 0:
                kind = key.split(":")[0]
                reasons.append(f"You like films {PERSON_VERBS[kind]} {vectors.names[key]}")
        close = sorted(
            (
                (float(p.similarity[n, i]), labels[i].tmdb_id)
                for i in p.nearest[n]
                if labels[i].explicit and labels[i].value >= 0.75 and p.similarity[n, i] > 0.15
            ),
            reverse=True,
        )
        names = [titles[i].title for _, i in close[:2]]
        if names:
            reasons.append(f"Like {' and '.join(names)}, which you rated highly")
        out.append(reasons[:MAX_REASONS])
    return out


def _diversify(vectors: Vectors, candidates: Sequence[int], scores: Floats) -> list[int]:
    """Maximal marginal relevance over the top: each pick trades score for difference
    from the picks before it, so the first page isn't ten versions of one film."""
    order = [int(i) for i in np.argsort(-scores, kind="stable")]
    top = order[:DIVERSIFY_TOP]
    x = vectors.matrix[[vectors.rows[candidates[i]] for i in top]].astype(np.float64)
    closest = np.zeros(len(top))
    remaining = list(range(len(top)))
    picked: list[int] = []
    while remaining:
        values = [
            DIVERSITY_LAMBDA * scores[top[i]] - (1 - DIVERSITY_LAMBDA) * closest[i]
            for i in remaining
        ]
        best = remaining.pop(int(np.argmax(values)))
        picked.append(top[best])
        closest = np.maximum(closest, x @ x[best])
    return picked + order[DIVERSIFY_TOP:]


@dataclass(frozen=True)
class Evaluation:
    ratings: int
    held_out: int
    model_spearman: float
    model_ndcg: float
    baseline_spearman: float
    baseline_ndcg: float


def evaluate(
    titles: dict[int, Title], labels: Sequence[Label], holdout: float = 0.2, seed: int = 0
) -> Evaluation:
    """Hold out some ratings, score them from the rest, and compare with ranking the same
    films by TMDb popularity."""
    explicit = [label for label in labels if label.explicit and label.tmdb_id in titles]
    random.Random(seed).shuffle(explicit)
    test = explicit[: max(1, int(len(explicit) * holdout))]
    test_ids = {label.tmdb_id for label in test}
    train = [label for label in labels if label.tmdb_id not in test_ids]
    by_id = {s.tmdb_id: s.score for s in score(titles, train, [t.tmdb_id for t in test])}
    truth = np.array([label.value for label in test])
    model = np.array([by_id[label.tmdb_id] for label in test])
    baseline = np.array([titles[label.tmdb_id].popularity or 0 for label in test])
    return Evaluation(
        ratings=len(explicit),
        held_out=len(test),
        model_spearman=spearman(model, truth),
        model_ndcg=ndcg(model, truth),
        baseline_spearman=spearman(baseline, truth),
        baseline_ndcg=ndcg(baseline, truth),
    )


def _ranks(values: Floats) -> Floats:
    """0-based ranks, ties sharing their average rank."""
    order = np.argsort(values, kind="stable")
    ranks = np.empty(len(values))
    ranks[order] = np.arange(len(values))
    for value in np.unique(values):
        tied = values == value
        ranks[tied] = ranks[tied].mean()
    return ranks


def spearman(predicted: Floats, truth: Floats) -> float:
    a, b = _ranks(predicted), _ranks(truth)
    if a.std() == 0 or b.std() == 0:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def ndcg(predicted: Floats, truth: Floats, k: int = 20) -> float:
    """Normalised discounted cumulative gain of the top k, with the true percentile as gain."""
    discounts = 1 / np.log2(np.arange(2, min(k, len(truth)) + 2))
    top = truth[np.argsort(-predicted, kind="stable")][: len(discounts)]
    ideal = np.sort(truth)[::-1][: len(discounts)]
    return float((top * discounts).sum() / (ideal * discounts).sum())
