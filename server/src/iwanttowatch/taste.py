"""What a user's ratings say about them, including the LLM-written persona."""

import logging
from collections import Counter, defaultdict
from statistics import mean
from typing import Any

from sqlalchemy import Subquery, func, select
from sqlalchemy.orm import Session

from iwanttowatch.db import utcnow
from iwanttowatch.llm import PROVIDER_SETTING, LlmError, LlmProvider, provider_from_settings
from iwanttowatch.models import Persona, Title, UserTitle, get_setting

log = logging.getLogger(__name__)

MIN_RATINGS_FOR_PERSONA = 5

PERSONA_SYSTEM = """You write playful, specific character sketches.
You get a summary of someone's movie ratings. Imagine the person whose taste this is
and describe them in two or three sentences, at most 70 words, beginning with
"If your movie taste were a person,". Write about that imaginary person as "they";
do not give them a name. Describe their personality, habits, and the kind of evening
they would enjoy. Draw on the languages, genres, eras, and filmmakers they love or
avoid, and mention at most two film titles or names, taken only from the summary:
never invent names that are not in it. Be warm and a little witty, never mean.
Plain text only: no lists, no markdown, no quotation marks around the answer."""


def effective_ratings(user_id: int) -> Subquery:
    """One row per rated title: when sources disagree, the most recent rating wins."""
    ranked = (
        select(
            UserTitle,
            func.row_number()
            .over(
                partition_by=UserTitle.tmdb_id,
                order_by=(UserTitle.rated_at.desc().nulls_last(), UserTitle.id.desc()),
            )
            .label("rank"),
        )
        .where(UserTitle.user_id == user_id, UserTitle.rating.is_not(None))
        .subquery()
    )
    return select(ranked).where(ranked.c.rank == 1).subquery()


def rating_count(session: Session, user_id: int) -> int:
    return session.scalar(select(func.count()).select_from(effective_ratings(user_id))) or 0


def taste_summary(session: Session, user_id: int) -> str:
    """A compact, factual description of a user's ratings for the LLM prompt.

    It holds titles, genres, languages, decades, and people, but nothing that
    identifies the user.
    """
    effective = effective_ratings(user_id)
    rows = session.execute(
        select(effective.c.rating, effective.c.rated_at, Title).join(
            Title, Title.tmdb_id == effective.c.tmdb_id
        )
    ).all()
    favorites = set(
        session.scalars(
            select(UserTitle.tmdb_id).where(UserTitle.user_id == user_id, UserTitle.favorite)
        )
    )
    ratings = [r.rating for r in rows]
    average = mean(ratings)

    def by_average(groups: dict[str, list[float]], minimum: int) -> list[tuple[str, float, int]]:
        scored = [(k, mean(v), len(v)) for k, v in groups.items() if len(v) >= minimum]
        return sorted(scored, key=lambda item: item[1], reverse=True)

    genres: dict[str, list[float]] = defaultdict(list)
    directors: dict[str, list[float]] = defaultdict(list)
    actors: dict[str, list[float]] = defaultdict(list)
    languages: Counter[str] = Counter()
    decades: Counter[int] = Counter()
    for r in rows:
        t: Title = r.Title
        languages[t.original_language] += 1
        if t.year:
            decades[t.year // 10 * 10] += 1
        for genre in t.genres:
            genres[genre].append(r.rating)
        for person in t.directors:
            directors[person["name"]].append(r.rating)
        for person in t.cast[:5]:
            actors[person["name"]].append(r.rating)

    genre_scores = by_average(genres, minimum=min(3, len(rows)))
    ranked = sorted(rows, key=lambda r: (r.rating, r.rated_at or utcnow().date()), reverse=True)

    def film(r: Any) -> str:
        t: Title = r.Title
        original = f" / {t.original_title}" if t.original_title != t.title else ""
        liked = ", liked" if t.tmdb_id in favorites else ""
        return f"{t.title}{original} ({t.year}, {t.original_language}): {r.rating:g}/10{liked}"

    total = len(rows)
    lines = [
        f"Rated films: {total}; average rating {average:.1f}/10.",
        "Original languages: "
        + ", ".join(f"{lang} {count * 100 // total}%" for lang, count in languages.most_common(5)),
        "Decades: " + ", ".join(f"{d}s ({n})" for d, n in decades.most_common(4)),
        "Favourite genres (average rating): "
        + ", ".join(f"{g} {s:.1f}" for g, s, _ in genre_scores[:4]),
    ]
    if len(genre_scores) > 4:
        lines.append(
            "Least liked genres: " + ", ".join(f"{g} {s:.1f}" for g, s, _ in genre_scores[-2:])
        )
    if top_directors := by_average(directors, minimum=2)[:3]:
        lines.append(
            "Favourite directors: " + ", ".join(f"{n} ({c} films)" for n, _, c in top_directors)
        )
    if top_actors := by_average(actors, minimum=3)[:3]:
        lines.append("Favourite actors: " + ", ".join(f"{n} ({c} films)" for n, _, c in top_actors))
    lines.append("Highest rated: " + "; ".join(film(r) for r in ranked[:12] if r.rating >= average))
    lowest = [r for r in ranked[-5:] if r.rating <= average - 1.5]
    if lowest:
        lines.append("Lowest rated: " + "; ".join(film(r) for r in reversed(lowest)))
    return "\n".join(lines)


def generate_persona(session: Session, user_id: int, llm: LlmProvider) -> Persona | None:
    """Write and store a new persona; None when the user has too few ratings."""
    count = rating_count(session, user_id)
    if count < MIN_RATINGS_FOR_PERSONA:
        return None
    text = llm.generate(PERSONA_SYSTEM, taste_summary(session, user_id))
    text = text.strip().strip('"“”').strip()
    if not text:
        raise LlmError("The LLM returned an empty answer")
    persona = session.get(Persona, user_id) or Persona(user_id=user_id)
    persona.text, persona.rating_count, persona.generated_at = text, count, utcnow()
    session.merge(persona)
    session.commit()
    return persona


# Users whose persona a background job is about to rewrite, so the UI knows to wait.
_refreshing: set[int] = set()


def is_refreshing(user_id: int) -> bool:
    return user_id in _refreshing


def mark_persona_stale(session: Session, user_id: int) -> bool:
    """Flag the persona as being rewritten; False when no LLM is configured."""
    if get_setting(session, PROVIDER_SETTING) is None:
        return False
    _refreshing.add(user_id)
    return True


def refresh_persona_quietly(session: Session, user_id: int) -> None:
    """Rewrite the persona after new ratings arrive; failures are logged, not raised."""
    try:
        llm = provider_from_settings(session)
        if llm is not None:
            generate_persona(session, user_id, llm)
    except LlmError:
        log.warning("Couldn't refresh the persona for user %s", user_id, exc_info=True)
    finally:
        _refreshing.discard(user_id)
