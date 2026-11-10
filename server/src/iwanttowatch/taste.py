"""What a user's ratings say about them, including the LLM-written persona and the
LLM's review of their recommendations."""

import json
import logging
import math
from collections import Counter, defaultdict
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from statistics import mean
from typing import Any

from sqlalchemy import Subquery, func, select
from sqlalchemy.orm import Session

from iwanttowatch.children import user_watched_titles
from iwanttowatch.db import utcnow
from iwanttowatch.llm import LlmError, LlmProvider, llm_order, provider_from_settings
from iwanttowatch.models import Explanation, OpinionClash, Persona, Title, UserTitle
from iwanttowatch.moods import MAX_MOODS, MOODS, moods_for, parse_moods
from iwanttowatch.tags import BY_ID

log = logging.getLogger(__name__)

MIN_RATINGS_FOR_PERSONA = 5
REACTION_LABELS = {"disliked": "didn't like", "liked": "liked", "loved": "loved"}

PERSONA_SYSTEM = """You sum up someone's taste in films for them, from a summary of their
movie ratings. Write two or three short sentences, at most 60 words, speaking to them as
"you": what they love, what they tend to avoid, and what a film needs to win them over.
Be concrete: name languages, genres, eras, and qualities they respond to, and mention at
most two film titles or names, taken only from the summary. Use plain, everyday words:
no metaphors, no jokes, no invented habits or scenes. Plain text only: no lists, no
markdown, no quotation marks around the answer."""

# Films the LLM may add beyond the recommender's list.
MAX_ADDITIONS = 5
# Seen films listed in the prompt so the LLM doesn't add them; the rest are filtered
# out after matching anyway.
MAX_SEEN_IN_PROMPT = 200
MAX_WHY_LENGTH = 140

REVIEW_SYSTEM = f"""You are a well-read film critic helping one person choose what to watch.
You get a summary of their movie ratings, including what they loved or disliked about
films in their own words, a numbered list of films they have not seen, and films they
have already seen. For every numbered film, predict the rating out of 10 they would
give it on their own scale (their average is in the summary; use the whole scale, low
for films they would dislike), with one short sentence on why, and up to {MAX_MOODS}
moods that describe how the film feels to watch, only from: {", ".join(m.label for m in MOODS)}
(an empty list when none fits; judge the film itself, not its genre alone; prefer moods that
tell the viewer something beyond the obvious genre). Then add up to
{MAX_ADDITIONS} real, released feature films that are not in the list or already seen and
that they are likely to rate higher than most of the list, each with a predicted rating
and why. Answer with only JSON, no markdown, in this form:
{{"ratings": [{{"n": 1, "rating": 7.5, "why": "...", "moods": ["Heartfelt"]}}],
 "new": [{{"title": "...", "year": 2019, "rating": 8.5, "why": "..."}}]}}"""


# Room for two long sentences; a longer answer is cut after its last full sentence.
MAX_EXPLANATION_LENGTH = 600

WHY_SYSTEM = """You tell one person how well a film fits their taste in one or two \
short sentences (under 50 words), judging from their rating history and the recommender's \
match reasons. Synthesize and critique, never repeat: do not restate the match reasons \
or genres verbatim (never say "You like films starring..." or "Because it is like..."). \
Instead, explain what makes the execution click (performance, inventive set pieces, \
or concept) and give an honest reality check (runtime, tonal detours, or pacing lag). \
Mention at most one film title or name, taken only from the summary: never invent names. \
Speak to them as "you".

Also provide structured "themes and values" notes in three bullet points:
- Values: <maximum of 3 or 4 keywords>
- Remake: <is this a remake of any of the films they watched already or any popular movies \
from another language? answer under 15 words>
- Other famous films: <famous other films by the same director or writer, as a comma-separated \
list under 20 words>

Format your entire reply as:
<one or two short sentences on fit>

- Values: <keywords>
- Remake: <answer>
- Other famous films: <comma-separated titles>

Plain text only: no markdown headings, no intro or outro, no quotes around the answer."""


def parse_why_reply(text: str) -> tuple[str, str | None]:
    """Split the LLM reply into the taste explanation and the themes note."""
    cleaned = text.strip().strip('"“”').strip()
    idx = -1
    for marker in ("- Values:", "- values:", "* Values:", "• Values:"):
        idx = cleaned.find(marker)
        if idx != -1:
            break
    if idx != -1:
        fit = cleaned[:idx].strip()
        themes = cleaned[idx:].strip()
        if fit.lower().startswith("fit:"):
            fit = fit[4:].strip()
        return (fit, themes)
    return (cleaned, None)


@dataclass(frozen=True)
class FilmReview:
    # The rating out of 10 the LLM expects the user to give.
    rating: float
    why: str
    # Moods it picked from iwanttowatch.moods, or None when it didn't answer.
    moods: list[str] | None = None


@dataclass(frozen=True)
class Suggestion:
    title: str
    year: int | None
    rating: float
    why: str


@dataclass(frozen=True)
class Review:
    # TMDb ID → the LLM's prediction, for the films it was shown.
    ratings: dict[int, FilmReview]
    # Films it added, still to be matched to TMDb.
    additions: list[Suggestion]


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


# Where each reaction sits in the user's own rating distribution (Criticker-style), and
# the score used until there are enough numeric ratings to read that distribution from.
REACTION_PERCENTILES = {"disliked": 0.15, "liked": 0.65, "loved": 0.90}
# The fallback scores sit near a typical rater's 5th, 65th and 90th percentiles.
REACTION_FALLBACK = {"disliked": 3.0, "liked": 8.0, "loved": 9.5}
MIN_RATINGS_FOR_DISTRIBUTION = 10


def numeric_ratings(session: Session, user_id: int) -> list[float]:
    """The user's imported 1–10 ratings, lowest first. In-app reactions are left out so
    they never shape the scale they are read against."""
    return sorted(
        rating
        for rating in session.scalars(
            select(UserTitle.rating).where(
                UserTitle.user_id == user_id, UserTitle.reaction.is_(None)
            )
        )
        if rating is not None
    )


def reaction_score(numeric: Sequence[float], reaction: str) -> float:
    """The 0–10 score a reaction stands for, given the user's sorted numeric ratings."""
    if len(numeric) < MIN_RATINGS_FOR_DISTRIBUTION:
        return REACTION_FALLBACK[reaction]
    return float(numeric[round(REACTION_PERCENTILES[reaction] * (len(numeric) - 1))])


def refresh_reaction_ratings(session: Session, user_id: int) -> int:
    """Re-derive every in-app reaction's 0–10 score from the user's current numeric
    ratings, so reactions given before an import follow the scale it reveals. The caller
    commits. Returns how many scores changed."""
    numeric = numeric_ratings(session, user_id)
    changed = 0
    for entry in session.scalars(
        select(UserTitle).where(UserTitle.user_id == user_id, UserTitle.reaction.is_not(None))
    ):
        if entry.reaction not in REACTION_FALLBACK:
            continue
        score = reaction_score(numeric, entry.reaction)
        if entry.rating != score:
            entry.rating = score
            changed += 1
    return changed


def rating_count(session: Session, user_id: int) -> int:
    return session.scalar(select(func.count()).select_from(effective_ratings(user_id))) or 0


# The most recent notes the user wrote when rating, quoted for the LLM.
NOTES_IN_SUMMARY = 10


def taste_summary(session: Session, user_id: int, exclude: Collection[int] = ()) -> str:
    """A compact, factual description of a user's ratings for the LLM prompt, leaving
    out the `exclude` films.

    It holds titles, genres, languages, decades, and people, but nothing that
    identifies the user.
    """
    effective = effective_ratings(user_id)
    rows = session.execute(
        select(
            effective.c.rating, effective.c.rated_at, effective.c.reaction, effective.c.tags, Title
        )
        .join(Title, Title.tmdb_id == effective.c.tmdb_id)
        .where(effective.c.tmdb_id.not_in(exclude))
    ).all()
    favorites = set(
        session.scalars(
            select(UserTitle.tmdb_id).where(UserTitle.user_id == user_id, UserTitle.favorite)
        )
    )
    ratings = [r.rating for r in rows]
    if not ratings:
        return "Rated films: 0."
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

    # Averages need enough films to mean something: a genre needs 10% of the ratings.
    genre_scores = by_average(genres, minimum=min(max(3, len(rows) // 10), len(rows)))
    most_rated = sorted(genres.items(), key=lambda item: len(item[1]), reverse=True)
    ranked = sorted(rows, key=lambda r: (r.rating, r.rated_at or utcnow().date()), reverse=True)

    def film(r: Any) -> str:
        t: Title = r.Title
        original = f" / {t.original_title}" if t.original_title != t.title else ""
        liked = ", liked" if t.tmdb_id in favorites else ""
        score = REACTION_LABELS[r.reaction] if r.reaction else f"{r.rating:g}/10"
        why = [BY_ID[tag].label.lower() for tag in r.tags or [] if tag in BY_ID]
        reasons = f" ({', '.join(why)})" if why else ""
        return f"{t.title}{original} ({t.year}, {t.original_language}): {score}{reasons}{liked}"

    total = len(rows)
    lines = [
        f"Rated films: {total}; average rating {average:.1f}/10.",
        "Original languages: "
        + ", ".join(f"{lang} {count * 100 // total}%" for lang, count in languages.most_common(5)),
        "Decades: " + ", ".join(f"{d}s ({n})" for d, n in decades.most_common(4)),
        "Most rated genres: " + ", ".join(f"{g} ({len(v)} films)" for g, v in most_rated[:4]),
        "Favourite genres (average rating): "
        + ", ".join(f"{g} {s:.1f} ({n} films)" for g, s, n in genre_scores[:4]),
    ]
    if len(genre_scores) > 4:
        lines.append(
            "Least liked genres: "
            + ", ".join(f"{g} {s:.1f} ({n} films)" for g, s, n in genre_scores[-2:])
        )
    if top_directors := by_average(directors, minimum=2)[:3]:
        lines.append(
            "Favourite directors: " + ", ".join(f"{n} ({c} films)" for n, _, c in top_directors)
        )
    if top_actors := by_average(actors, minimum=3)[:3]:
        names = ", ".join(f"{n} ({c} films)" for n, _, c in top_actors)
        lines.append(f"Favourite actors: {names}")
    tag_counts = Counter(tag for r in rows for tag in r.tags or [] if tag in BY_ID)
    for positive, heading in ((True, "What they enjoy most"), (False, "What puts them off")):
        counted = [(t, n) for t, n in tag_counts.most_common() if BY_ID[t].positive == positive]
        if counted:
            items = ", ".join(f"{BY_ID[t].label.lower()} ({n} films)" for t, n in counted[:5])
            lines.append(f"{heading}, in their own words: {items}")
    top = "; ".join(film(r) for r in ranked[:12] if r.rating >= average)
    lines.append(f"Highest rated: {top}")
    lowest = [r for r in ranked[-5:] if r.rating <= average - 1.5]
    if lowest:
        lines.append("Lowest rated: " + "; ".join(film(r) for r in reversed(lowest)))
    noted = session.execute(
        select(UserTitle.reaction, UserTitle.note, Title.title, Title.year)
        .join(Title, Title.tmdb_id == UserTitle.tmdb_id)
        .where(
            UserTitle.user_id == user_id,
            UserTitle.note.is_not(None),
            UserTitle.tmdb_id.not_in(exclude),
        )
        .order_by(UserTitle.rated_at.desc(), UserTitle.id.desc())
        .limit(NOTES_IN_SUMMARY)
    ).all()
    if noted:
        notes = "; ".join(
            f"{n.title} ({n.year}, {REACTION_LABELS.get(n.reaction or '', 'rated')}): "
            f'"{" ".join((n.note or "").split())}"'
            for n in noted
        )
        lines.append(f"Their notes on recent films: {notes}")
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
    if not llm_order(session):
        return False
    _refreshing.add(user_id)
    return True


def refresh_persona_quietly(session: Session, user_id: int) -> None:
    """Rewrite the persona after new ratings arrive; failures are logged, not raised."""
    try:
        llm = provider_from_settings(session, "persona", user_id)
        if llm is not None:
            generate_persona(session, user_id, llm)
    except LlmError:
        log.warning("Couldn't refresh the persona for user %s", user_id, exc_info=True)
    finally:
        _refreshing.discard(user_id)


def review_films(
    session: Session,
    user_id: int,
    llm: LlmProvider,
    films: Sequence[Title],
    exclude: Collection[int] = (),
) -> Review | None:
    """The LLM's predicted rating for each film, plus up to MAX_ADDITIONS films of its
    own; None when the user has too few ratings. `exclude` hides rated films from it."""
    if rating_count(session, user_id) - len(exclude) < MIN_RATINGS_FOR_PERSONA:
        return None
    seen = session.execute(
        select(Title.title, Title.year)
        .join(UserTitle, UserTitle.tmdb_id == Title.tmdb_id)
        .where(UserTitle.user_id == user_id, UserTitle.tmdb_id.not_in(exclude))
        .distinct()
        .limit(MAX_SEEN_IN_PROMPT)
    ).all()

    def line(n: int, t: Title) -> str:
        original = f" / {t.original_title}" if t.original_title != t.title else ""
        about = [str(t.year or "?"), t.original_language, *t.genres[:3]]
        if t.directors:
            about.append("dir. " + t.directors[0]["name"])
        return f"{n}. {t.title}{original} ({', '.join(about)})"

    prompt = "\n".join(
        [
            taste_summary(session, user_id, exclude),
            "Films to rate:",
            *(line(n, t) for n, t in enumerate(films, 1)),
            "Already seen: "
            + "; ".join(f"{title} ({year})" if year else title for title, year in seen),
        ]
    )
    text = llm.generate(REVIEW_SYSTEM, prompt, json_reply=True)
    try:
        answer = json.loads(text[text.index("{") : text.rindex("}") + 1])
    except ValueError as error:
        raise LlmError("The LLM's answer wasn't JSON") from error
    if not isinstance(answer, dict):
        raise LlmError("The LLM's answer wasn't a JSON object")

    def rating(value: Any) -> float | None:
        ok = isinstance(value, int | float) and not isinstance(value, bool)
        return min(max(float(value), 0.0), 10.0) if ok else None

    def why(value: Any) -> str:
        return value.strip()[:MAX_WHY_LENGTH] if isinstance(value, str) else ""

    ratings: dict[int, FilmReview] = {}
    for item in answer.get("ratings") or []:
        if not isinstance(item, dict):
            continue
        n, predicted = item.get("n"), rating(item.get("rating"))
        if isinstance(n, int) and 1 <= n <= len(films) and predicted is not None:
            ratings[films[n - 1].tmdb_id] = FilmReview(
                predicted, why(item.get("why")), parse_moods(item.get("moods"))
            )
    additions = []
    for item in answer.get("new") or []:
        if not isinstance(item, dict) or not isinstance(item.get("title"), str):
            continue
        predicted, year = rating(item.get("rating")), item.get("year")
        if predicted is not None:
            additions.append(
                Suggestion(
                    title=item["title"].strip(),
                    year=year if isinstance(year, int) else None,
                    rating=predicted,
                    why=why(item.get("why")),
                )
            )
    return Review(ratings, additions[:MAX_ADDITIONS])


def explain_match(
    session: Session,
    user_id: int,
    title: Title,
    llm: LlmProvider,
    reasons: Sequence[str] | None = None,
) -> str:
    """The LLM's answer to "Why this?" for a film, written once per user and film."""
    cached = session.get(Explanation, (user_id, title.tmdb_id))
    if cached is not None:
        return cached.text
    about = [str(title.year or "?"), title.original_language, *title.genres]
    if title.runtime:
        about.append(f"{title.runtime} min")
    lines = [
        taste_summary(session, user_id),
        f"Film: {title.title} ({', '.join(about)})",
    ]
    if moods := moods_for(title):
        lines.append(f"Mood / Feel: {', '.join(moods)}")
    if title.tagline:
        lines.append(f'Tagline: "{title.tagline}"')
    if title.keywords:
        lines.append("Keywords: " + ", ".join(title.keywords[:15]))
    if title.directors:
        directors = [p["name"] for p in title.directors if isinstance(p, dict) and p.get("name")]
        if directors:
            lines.append("Directed by " + ", ".join(directors[:2]))
    if title.writers:
        writers = [w["name"] for w in title.writers if isinstance(w, dict) and w.get("name")]
        if writers:
            lines.append("Written by " + ", ".join(writers[:2]))
    if title.cast:
        cast = [p["name"] for p in title.cast if isinstance(p, dict) and p.get("name")]
        if cast:
            lines.append("Starring " + ", ".join(cast[:4]))
    if title.overview:
        lines.append(f"Overview: {title.overview}")
    if reasons:
        non_ai = [r for r in reasons if not r.startswith("AI")]
        if non_ai:
            lines.append("Recommender match reasons: " + "; ".join(non_ai))
    watched = user_watched_titles(session, user_id)
    if watched:
        lines.append(f"Films I watched already: {', '.join(watched)}")
    else:
        lines.append("Films I watched already: None")
    raw_text = llm.generate(WHY_SYSTEM, "\n".join(lines)).strip().strip('"“”').strip()
    if not raw_text:
        raise LlmError("The LLM returned an empty answer")
    fit, themes_note = parse_why_reply(raw_text)
    if not fit:
        fit = raw_text
    if len(fit) > MAX_EXPLANATION_LENGTH:
        cut = fit[:MAX_EXPLANATION_LENGTH]
        end = max(cut.rfind(mark) for mark in (". ", "! ", "? "))
        fit = cut[: end + 1] if end > 0 else cut.rsplit(" ", 1)[0] + "…"
    session.add(Explanation(user_id=user_id, tmdb_id=title.tmdb_id, text=fit))
    if themes_note:
        title.themes_note = themes_note
    session.commit()
    return fit


CLASH_SYSTEM = """You analyze why one person's opinion of a film strongly conflicts \
with the general audience consensus. You get a summary of their movie taste, their \
rating, reaction, tags, and note on the film, and the film's details with its \
consensus score. In two or three short sentences (under 90 words), explain the conflict: \
(1) what resonated with or divided the general audience, (2) where this person's view \
sharply diverged based on their tags, notes, or reaction, and (3) why this disagreement fits \
their overall taste profile. Be concrete, insightful, and validating: speak to them as \
"you". Plain text only: no markdown headings, no bullet points, no intro or outro, no \
quotes around the answer."""


def consensus_for(title: Title) -> tuple[float, int] | None:
    """The consensus rating (0–10) and vote count from IMDb or TMDb, or None if too few votes."""
    if title.imdb_rating is not None and title.imdb_votes and title.imdb_votes >= 100:
        return (title.imdb_rating, title.imdb_votes)
    if title.vote_average is not None and title.vote_count and title.vote_count >= 50:
        return (title.vote_average, title.vote_count)
    return None


@dataclass(frozen=True)
class DivergentItem:
    tmdb_id: int
    title: str
    original_title: str
    original_language: str
    year: int | None
    poster_path: str | None
    user_rating: float
    consensus_rating: float
    vote_count: int
    divergence: float
    reaction: str | None
    tags: list[str]
    note: str | None
    clash: str | None = None


def find_divergent_ratings(
    session: Session,
    user_id: int,
    *,
    threshold: float = 1.5,
    limit: int = 50,
) -> list[DivergentItem]:
    """Finds films the user rated where their rating strongly differed from the general audience."""
    effective = effective_ratings(user_id)
    rows = session.execute(
        select(effective, Title).join(Title, Title.tmdb_id == effective.c.tmdb_id)
    ).all()
    candidates: list[tuple[float, DivergentItem]] = []
    for r in rows:
        t: Title = r.Title
        consensus = consensus_for(t)
        if consensus is None:
            continue
        c_rating, votes = consensus
        user_rating = float(r.rating)
        diff = round(user_rating - c_rating, 1)
        if abs(diff) < threshold:
            continue
        weight = abs(diff) * math.log10(max(votes, 10))
        item = DivergentItem(
            tmdb_id=t.tmdb_id,
            title=t.title,
            original_title=t.original_title,
            original_language=t.original_language,
            year=t.year,
            poster_path=t.poster_path,
            user_rating=user_rating,
            consensus_rating=round(c_rating, 1),
            vote_count=votes,
            divergence=diff,
            reaction=r.reaction,
            tags=list(r.tags or []),
            note=r.note,
        )
        candidates.append((weight, item))

    candidates.sort(key=lambda pair: pair[0], reverse=True)
    top_items = [item for _, item in candidates[:limit]]
    if not top_items:
        return []

    clashes = {
        c.tmdb_id: c.text
        for c in session.scalars(
            select(OpinionClash).where(
                OpinionClash.user_id == user_id,
                OpinionClash.tmdb_id.in_([item.tmdb_id for item in top_items]),
            )
        )
    }

    return [
        DivergentItem(
            tmdb_id=item.tmdb_id,
            title=item.title,
            original_title=item.original_title,
            original_language=item.original_language,
            year=item.year,
            poster_path=item.poster_path,
            user_rating=item.user_rating,
            consensus_rating=item.consensus_rating,
            vote_count=item.vote_count,
            divergence=item.divergence,
            reaction=item.reaction,
            tags=item.tags,
            note=item.note,
            clash=clashes.get(item.tmdb_id),
        )
        for item in top_items
    ]


def explain_clash(
    session: Session,
    user_id: int,
    title: Title,
    user_rating: float,
    reaction: str | None,
    tags: list[str],
    note: str | None,
    llm: LlmProvider,
) -> str:
    """The LLM's explanation of conflicting opinions between the user and general audience."""
    cached = session.get(OpinionClash, (user_id, title.tmdb_id))
    if cached is not None:
        return cached.text

    consensus = consensus_for(title)
    consensus_text = (
        f"{consensus[0]:.1f}/10 ({consensus[1]:,} votes)"
        if consensus
        else (f"{title.vote_average:.1f}/10" if title.vote_average else "unknown")
    )
    user_score_str = f"{user_rating:g}/10"
    if reaction:
        user_score_str += f" ({REACTION_LABELS.get(reaction, reaction)})"

    about = [str(title.year or "?"), title.original_language, *title.genres]
    if title.runtime:
        about.append(f"{title.runtime} min")

    lines = [
        taste_summary(session, user_id),
        f"Film: {title.title} ({', '.join(about)})",
        f"Audience consensus rating: {consensus_text}",
        f"This user's rating: {user_score_str}",
    ]
    tag_labels = [BY_ID[t].label for t in tags if t in BY_ID]
    if tag_labels:
        lines.append(f"What the user noted: {', '.join(tag_labels)}")
    if note:
        lines.append(f'User note: "{note.strip()}"')
    if title.tagline:
        lines.append(f'Tagline: "{title.tagline}"')
    if title.directors:
        directors = [p["name"] for p in title.directors if isinstance(p, dict) and p.get("name")]
        if directors:
            lines.append("Directed by " + ", ".join(directors[:2]))
    if title.cast:
        cast = [p["name"] for p in title.cast if isinstance(p, dict) and p.get("name")]
        if cast:
            lines.append("Starring " + ", ".join(cast[:4]))
    if title.overview:
        lines.append(f"Overview: {title.overview}")

    raw_text = llm.generate(CLASH_SYSTEM, "\n".join(lines)).strip().strip('"“”').strip()
    if not raw_text:
        raise LlmError("The LLM returned an empty answer")

    clash = raw_text
    if len(clash) > MAX_EXPLANATION_LENGTH:
        cut = clash[:MAX_EXPLANATION_LENGTH]
        end = max(cut.rfind(mark) for mark in (". ", "! ", "? "))
        clash = cut[: end + 1] if end > 0 else cut.rsplit(" ", 1)[0] + "…"

    session.add(OpinionClash(user_id=user_id, tmdb_id=title.tmdb_id, text=clash))
    session.commit()
    return clash
