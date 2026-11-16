"""What a user's ratings say about them, including the LLM-written persona and the
LLM's review of their recommendations."""

import json
import logging
import math
from collections import Counter, defaultdict
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from statistics import mean
from typing import Any

from sqlalchemy import Subquery, func, select
from sqlalchemy.orm import Session

from iwanttowatch.children import user_watched_titles
from iwanttowatch.db import utcnow
from iwanttowatch.llm import LlmError, LlmProvider, llm_order, provider_from_settings
from iwanttowatch.models import Explanation, OpinionClash, Persona, Title, UserTitle
from iwanttowatch.moods import MAX_MOODS, MOODS, moods_for, parse_moods
from iwanttowatch.recommender import _features
from iwanttowatch.tags import BY_ID, MAX_TAGS, TAGS

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

WHY_SYSTEM = """You tell one person how well a film fits their taste using bullet points, \
judging from their rating history and the recommender's match reasons.

Give between 2 and 4 bullet points in total for fit:
- Use "+ " for strengths that match what they love.
- Use "- " for honest caveats, flaws, or drawbacks.
- Adapt the ratio of "+ " and "- " to reality: use more "+ " if the film genuinely fits \
their taste (e.g. 3 pluses and 1 minus), balanced if mixed (e.g. 2 pluses and 2 minuses), \
or more "- " if it is a poor or risky match (e.g. 1 plus and 3 minuses).
- Keep each bullet point under 20 words, speaking to them as "you".
- Use simple, everyday words: avoid critic jargon (no "neo-noir", "third act", "tonal detours", \
"mise-en-scène", "pacing lag", "set pieces", or film-school terms). Write like a knowledgeable \
friend recommending a film.
- Never repeat genres or match reasons verbatim.
- Focus caveats on real viewing hurdles and common audience criticisms of this specific film \
(such as slow pacing, weak story/second half, flat characters, contrived twists, emotionally \
heavy/bleak tone, jarring humor, or weak dialogue), and explicitly compare them against \
what puts this user off in their summary and notes.
- A long runtime is not automatically a negative if the film keeps the viewer engaged: \
only cite length if the film genuinely drags, has slow filler, or tests patience. When \
mentioning runtime, always express it in hours and minutes (e.g. 2h 15m), never raw minutes.
- Pay special attention to where they break from the crowd in their summary: if they tend \
to love or hate traits that divide general audiences, weigh that heavily.
- Mention at most one film title or name, taken only from the summary: never invent names.

Also provide structured "themes and values" notes in four bullet points:
- Values: <maximum of 3 or 4 keywords>
- Real story: <is this based on a real story or true events? answer under 15 words, or "No">
- Remake: <is this a remake of any of the films they watched already or any popular movies \
from another language? answer under 15 words, or "No">
- Other famous films: <famous other films by the same director or writer, as a comma-separated \
list under 20 words, or "No">

Format your entire reply as:
+ <strength>
+ <strength>
- <caveat>
- <caveat>

- Values: <keywords>
- Real story: <answer>
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


def rating_to_reaction(rating: float) -> str:
    """Map a 0–10 numeric rating (e.g. from IMDb or Letterboxd) to the 3-point reaction scale."""
    if rating >= 9.0:
        return "loved"
    if rating >= 6.0:
        return "liked"
    return "disliked"


# Target percentiles for the recommender labels:
REACTION_PERCENTILES = {"disliked": 0.15, "liked": 0.70, "loved": 0.95}
# Nominal 0–10 scores for divergence and persona summaries:
REACTION_FALLBACK = {"disliked": 3.0, "liked": 8.0, "loved": 9.5}
MIN_RATINGS_FOR_DISTRIBUTION = 10


def numeric_ratings(session: Session, user_id: int) -> list[float]:
    """The user's imported 1–10 ratings, lowest first."""
    return sorted(
        rating
        for rating in session.scalars(
            select(UserTitle.rating).where(
                UserTitle.user_id == user_id, UserTitle.rating.is_not(None)
            )
        )
        if rating is not None
    )


def reaction_score(numeric: Sequence[float], reaction: str) -> float:
    """The nominal 0–10 score a reaction stands for."""
    return REACTION_FALLBACK.get(reaction, 8.0)


def refresh_reaction_ratings(session: Session, user_id: int) -> int:
    """Ensure every rated entry has its 3-point reaction and nominal score set.
    The caller commits. Returns how many rows changed."""
    changed = 0
    for entry in session.scalars(select(UserTitle).where(UserTitle.user_id == user_id)):
        if entry.reaction is None and entry.rating is not None:
            entry.reaction = rating_to_reaction(entry.rating)
            changed += 1
        elif (
            entry.reaction is not None
            and entry.rating is None
            and entry.reaction in REACTION_FALLBACK
        ):
            entry.rating = REACTION_FALLBACK[entry.reaction]
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
    # Surface where this user strongly breaks from general audience consensus.
    divergent_pos: list[tuple[float, str]] = []
    divergent_neg: list[tuple[float, str]] = []
    for r in rows:
        cons = consensus_for(r.Title)
        if cons is None:
            continue
        diff = r.rating - cons[0]
        if diff >= 1.5:
            divergent_pos.append((diff, f"{r.Title.title} ({r.rating:g} vs {cons[0]:.1f} avg)"))
        elif diff <= -1.5:
            divergent_neg.append((-diff, f"{r.Title.title} ({r.rating:g} vs {cons[0]:.1f} avg)"))
    divergent_pos.sort(reverse=True)
    divergent_neg.sort(reverse=True)
    if divergent_pos or divergent_neg:
        parts = []
        if divergent_pos:
            parts.append("loved vs crowd: " + ", ".join(s for _, s in divergent_pos[:3]))
        if divergent_neg:
            parts.append("disliked vs crowd: " + ", ".join(s for _, s in divergent_neg[:3]))
        lines.append("Where they break from the crowd: " + "; ".join(parts))
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
    force: bool = False,
) -> str:
    """The LLM's answer to "Why this?" for a film, written once per user and film."""
    cached = session.get(Explanation, (user_id, title.tmdb_id))
    if cached is not None and not force:
        return cached.text
    about = [str(title.year or "?"), title.original_language, *title.genres]
    if title.runtime:
        hours = title.runtime // 60
        mins = title.runtime % 60
        about.append(f"{hours}h {mins}m" if hours else f"{mins}m")
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
        end = max(cut.rfind(mark) for mark in (". ", "! ", "? ", "\n"))
        fit = cut[: end + 1] if end > 0 else cut.rsplit(" ", 1)[0] + "…"
    if cached is not None:
        cached.text = fit
    else:
        session.add(Explanation(user_id=user_id, tmdb_id=title.tmdb_id, text=fit))
    if themes_note:
        title.themes_note = themes_note
    session.commit()
    return fit


CLASH_SYSTEM = """You help a movie recommender learn from a rating that strongly conflicts \
with general audience consensus. Instead of lecturing the user about why they liked or \
disliked the film, propose 2 or 3 concrete, testable yes/no hypotheses that the recommender \
can learn from when the user answers Yes or No.

Do NOT repeat tags or notes the user already gave.
Return a single JSON object (no markdown fences, no extra text) with this shape:
{
  "summary": "One short sentence (under 25 words) framing the divergence.",
  "hypotheses": [
    {"question": "Short yes/no question", "kind": "tag", "tag_id": "<allowed_tag_id>"},
    {"question": "Short yes/no question", "kind": "feature", "feature_key": "<feature_key>"},
    {"question": "Short yes/no question", "kind": "outlier"}
  ]
}
Rules:
- Propose 2 or 3 distinct hypotheses total, each under 14 words.
- For "tag", pick an exact tag_id from the allowed tag list not already in the user's tags.
- For "feature", pick an exact feature_key from the film's provided feature list.
- Optionally include at most one "outlier" hypothesis (expectation mismatch / wrong mood)."""


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
    hypotheses: list[dict[str, Any]] = field(default_factory=list)


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
        user_rating = (
            float(r.rating)
            if r.rating is not None
            else (REACTION_FALLBACK.get(r.reaction, 7.5) if r.reaction else None)
        )
        if user_rating is None:
            continue
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
        c.tmdb_id: c
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
            clash=clashes[item.tmdb_id].text if item.tmdb_id in clashes else None,
            hypotheses=(
                list(clashes[item.tmdb_id].hypotheses or []) if item.tmdb_id in clashes else []
            ),
        )
        for item in top_items
    ]


@dataclass(frozen=True)
class AgainstTheGrainProfile:
    score: int
    archetype: str
    summary: str
    total_compared: int
    divergent_count: int
    items: list[DivergentItem]


def against_the_grain_profile(
    session: Session,
    user_id: int,
    *,
    threshold: float = 1.5,
    limit: int = 50,
) -> AgainstTheGrainProfile:
    """Compute the user's Against-the-Grain score, taste archetype, and divergent films."""
    effective = effective_ratings(user_id)
    rows = session.execute(
        select(effective, Title).join(Title, Title.tmdb_id == effective.c.tmdb_id)
    ).all()

    total_compared = 0
    divergent_total = 0
    pos_count = 0
    neg_count = 0
    real_story_hits = 0
    tag_counter: Counter[str] = Counter()
    genre_counter: Counter[str] = Counter()

    for r in rows:
        t: Title = r.Title
        cons = consensus_for(t)
        if cons is None:
            continue
        user_rating = (
            float(r.rating)
            if r.rating is not None
            else (REACTION_FALLBACK.get(r.reaction, 7.5) if r.reaction else None)
        )
        if user_rating is None:
            continue
        total_compared += 1
        diff = user_rating - cons[0]
        if abs(diff) >= threshold:
            divergent_total += 1
            if diff > 0:
                pos_count += 1
            else:
                neg_count += 1
        if user_rating >= 7.5:
            kws = {k.lower() for k in (t.keywords or [])}
            if kws & {"based on true story", "based on a true story", "biography", "true story"}:
                real_story_hits += 1
            for g in t.genres or []:
                genre_counter[g] += 1
        for tag in r.tags or []:
            tag_counter[tag] += 1

    items = find_divergent_ratings(session, user_id, threshold=threshold, limit=limit)
    score = round((divergent_total / total_compared) * 100) if total_compared > 0 else 0

    if total_compared < 5:
        archetype = "Movie Explorer"
        summary = "Rate more films to unlock your contrarian taste profile."
    elif real_story_hits >= 5 and real_story_hits / max(total_compared, 1) >= 0.15:
        archetype = "Real Story Lover"
        summary = (
            "You gravitate strongly toward true events, biographies, "
            "and grounded real-world stories."
        )
    elif score >= 35 and neg_count > pos_count * 1.4:
        archetype = "Contrarian Critic"
        summary = (
            f"You break from the crowd on {score}% of films, "
            "holding high standards even for crowd favorites."
        )
    elif score >= 35 and pos_count > neg_count * 1.4:
        archetype = "Hidden Gem Hunter"
        summary = (
            f"You disagree with consensus on {score}% of films, "
            "often championing underrated picks others overlook."
        )
    elif score >= 30:
        archetype = "Maverick Cinephile"
        summary = (
            f"Independent taste: {score}% of your ratings diverge sharply from mainstream scores."
        )
    elif score >= 15:
        archetype = "Selective Movie Enthusiast"
        summary = (
            f"Mostly aligned with consensus, with strong personal convictions on {score}% of films."
        )
    else:
        archetype = "Crowd-Aligned Viewer"
        summary = "Your ratings closely track mainstream audience consensus."

    return AgainstTheGrainProfile(
        score=score,
        archetype=archetype,
        summary=summary,
        total_compared=total_compared,
        divergent_count=divergent_total,
        items=items,
    )


def _truncate_text(text: str, limit: int = MAX_EXPLANATION_LENGTH) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(mark) for mark in (". ", "! ", "? ", "\n"))
    return cut[: end + 1] if end > 0 else cut.rsplit(" ", 1)[0] + "…"


def _strip_json_fences(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _parse_clash_response(
    raw_text: str,
    *,
    existing_tags: set[str],
    valid_features: dict[str, str],
    positive_clash: bool,
) -> tuple[str, list[dict[str, Any]]]:
    """Parse structured JSON hypotheses from the LLM, falling back to plain text."""
    cleaned = _strip_json_fences(raw_text)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        return _truncate_text(raw_text), []

    if not isinstance(parsed, dict) or not isinstance(parsed.get("hypotheses"), list):
        return _truncate_text(raw_text), []

    summary_raw = parsed.get("summary")
    summary = (
        _truncate_text(summary_raw.strip())
        if isinstance(summary_raw, str) and summary_raw.strip()
        else "Explore what drove this disagreement:"
    )

    hypotheses: list[dict[str, Any]] = []
    seen: set[tuple[str, str | None, str | None]] = set()
    for item in parsed["hypotheses"]:
        if not isinstance(item, dict):
            continue
        question = item.get("question")
        kind = item.get("kind")
        if not isinstance(question, str) or not question.strip():
            continue
        if kind not in ("tag", "feature", "outlier"):
            continue
        tag_id: str | None = None
        feature_key: str | None = None
        if kind == "tag":
            raw_tag = item.get("tag_id")
            if (
                not isinstance(raw_tag, str)
                or raw_tag not in BY_ID
                or raw_tag in existing_tags
                or BY_ID[raw_tag].positive != positive_clash
            ):
                continue
            tag_id = raw_tag
        elif kind == "feature":
            raw_feat = item.get("feature_key")
            if not isinstance(raw_feat, str) or raw_feat not in valid_features:
                continue
            feature_key = raw_feat

        dedup = (kind, tag_id, feature_key)
        if dedup in seen:
            continue
        seen.add(dedup)
        hypotheses.append(
            {
                "id": f"h{len(hypotheses) + 1}",
                "question": question.strip()[:140],
                "kind": kind,
                "tag_id": tag_id,
                "feature_key": feature_key,
                "answer": None,
                "effect": None,
            }
        )
        if len(hypotheses) >= 3:
            break

    return summary, hypotheses


def explain_clash(
    session: Session,
    user_id: int,
    title: Title,
    user_rating: float,
    reaction: str | None,
    tags: list[str],
    note: str | None,
    llm: LlmProvider,
    *,
    refresh: bool = False,
) -> str:
    """Generate (or return cached) hypotheses for why the user's rating clashed with consensus."""
    cached = session.get(OpinionClash, (user_id, title.tmdb_id))
    if cached is not None and not refresh:
        return cached.text

    consensus = consensus_for(title)
    consensus_val = consensus[0] if consensus else (title.vote_average or 6.5)
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
        hours = title.runtime // 60
        mins = title.runtime % 60
        about.append(f"{hours}h {mins}m" if hours else f"{mins}m")

    existing_tags = set(tags)
    positive_clash = user_rating >= consensus_val
    allowed_tags = [
        f"{t.id} ({t.label})"
        for t in TAGS
        if t.positive == positive_clash and t.id not in existing_tags
    ]
    valid_features = _features(title)
    feature_choices = [f"{k} ({v})" for k, v in list(valid_features.items())[:25]]

    lines = [
        taste_summary(session, user_id),
        f"Film: {title.title} ({', '.join(about)})",
        f"Audience consensus rating: {consensus_text}",
        f"This user's rating: {user_score_str}",
        f"Allowed tag_id values: {', '.join(allowed_tags)}",
        f"Film feature_key values: {', '.join(feature_choices)}",
    ]
    tag_labels = [BY_ID[t].label for t in tags if t in BY_ID]
    if tag_labels:
        lines.append(f"What the user already noted: {', '.join(tag_labels)}")
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
    other_divergent = [
        d for d in find_divergent_ratings(session, user_id, limit=6) if d.tmdb_id != title.tmdb_id
    ][:4]
    if other_divergent:
        lines.append(
            "Other films where they broke from consensus: "
            + "; ".join(
                f"{d.title} (you: {d.user_rating:g}, crowd: {d.consensus_rating:.1f})"
                for d in other_divergent
            )
        )

    raw_text = llm.generate(CLASH_SYSTEM, "\n".join(lines)).strip().strip('"“”').strip()
    if not raw_text:
        raise LlmError("The LLM returned an empty answer")

    clash, hypotheses = _parse_clash_response(
        raw_text,
        existing_tags=existing_tags,
        valid_features=valid_features,
        positive_clash=positive_clash,
    )

    if cached is not None:
        cached.text = clash
        cached.hypotheses = hypotheses or None
        cached.created_at = utcnow()
    else:
        session.add(
            OpinionClash(
                user_id=user_id,
                tmdb_id=title.tmdb_id,
                text=clash,
                hypotheses=hypotheses or None,
            )
        )
    session.commit()
    return clash


def _primary_rated_entry(session: Session, user_id: int, tmdb_id: int) -> UserTitle | None:
    entries = list(
        session.scalars(
            select(UserTitle).where(UserTitle.user_id == user_id, UserTitle.tmdb_id == tmdb_id)
        )
    )
    for source in ("app", "imdb", "letterboxd"):
        for entry in entries:
            if entry.source == source and (entry.rating is not None or entry.reaction is not None):
                return entry
    return entries[0] if entries else None


def answer_clash_hypothesis(
    session: Session,
    user_id: int,
    title: Title,
    hypothesis_id: str,
    answer: bool | None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Record a Yes/No/None answer on a clash hypothesis and sync tags/model signals."""
    clash = session.get(OpinionClash, (user_id, title.tmdb_id))
    if clash is None or not clash.hypotheses:
        raise LookupError("No clash hypotheses found for this film")

    feature_names = _features(title)
    updated: list[dict[str, Any]] = []
    matched: dict[str, Any] | None = None
    for item in clash.hypotheses:
        copy = dict(item)
        if copy.get("id") == hypothesis_id:
            copy["answer"] = answer
            matched = copy
        updated.append(copy)

    if matched is None:
        raise LookupError(f"Hypothesis {hypothesis_id!r} not found")

    effect: str | None = None
    kind = matched.get("kind")
    if answer is not None:
        if kind == "tag" and isinstance(matched.get("tag_id"), str) and matched["tag_id"] in BY_ID:
            tag_id = matched["tag_id"]
            tag_label = BY_ID[tag_id].label
            entry = _primary_rated_entry(session, user_id, title.tmdb_id)
            if entry is not None:
                tags = list(entry.tags or [])
                if answer is True:
                    if tag_id not in tags and len(tags) < MAX_TAGS:
                        tags.append(tag_id)
                        entry.tags = tags
                    effect = f"Added tag: {tag_label}"
                else:
                    if tag_id in tags:
                        tags.remove(tag_id)
                        entry.tags = tags
                    effect = f"Noted — didn't add {tag_label}"
            else:
                effect = f"Noted: {tag_label}" if answer else f"Noted — not {tag_label}"
        elif kind == "outlier":
            effect = (
                "Marked as outlier — down-weighted in your model"
                if answer
                else "Not an outlier — kept full taste weight"
            )
        elif kind == "feature" and isinstance(matched.get("feature_key"), str):
            feat_key = matched["feature_key"]
            feat_label = feature_names.get(feat_key, feat_key.split(":", 1)[-1])
            effect = (
                f"Adjusted model weight for {feat_label}"
                if answer
                else f"Protected {feat_label} from blame"
            )

    matched["effect"] = effect
    clash.hypotheses = updated
    session.commit()
    return updated, effect


def clash_model_signals(
    session: Session, user_id: int
) -> tuple[set[int], dict[str, float], dict[int, list[str]]]:
    """Return (dampened_outliers, feature_adjustments, rated_tags) for the recommender."""
    effective = effective_ratings(user_id)
    rating_rows = session.execute(
        select(effective.c.tmdb_id, effective.c.rating, effective.c.tags)
    ).all()
    ratings_by_id: dict[int, float] = {}
    rated_tags: dict[int, list[str]] = {}
    for row in rating_rows:
        if row.rating is not None:
            ratings_by_id[row.tmdb_id] = float(row.rating)
        if row.tags:
            rated_tags[row.tmdb_id] = list(row.tags)

    clashes = list(
        session.scalars(
            select(OpinionClash).where(
                OpinionClash.user_id == user_id,
                OpinionClash.hypotheses.is_not(None),
            )
        )
    )
    if not clashes:
        return set(), {}, rated_tags

    titles = {
        t.tmdb_id: t
        for t in session.scalars(
            select(Title).where(Title.tmdb_id.in_([c.tmdb_id for c in clashes]))
        )
    }

    dampened_outliers: set[int] = set()
    feature_adjustments: dict[str, float] = {}
    for clash in clashes:
        title = titles.get(clash.tmdb_id)
        cons = consensus_for(title) if title is not None else None
        cons_rating = cons[0] if cons else 6.5
        user_rating = ratings_by_id.get(clash.tmdb_id)
        positive = user_rating >= cons_rating if user_rating is not None else False
        for h in clash.hypotheses or []:
            if h.get("answer") is not True:
                continue
            if h.get("kind") == "outlier":
                dampened_outliers.add(clash.tmdb_id)
            elif h.get("kind") == "feature" and isinstance(h.get("feature_key"), str):
                key = h["feature_key"]
                delta = 0.05 if positive else -0.05
                feature_adjustments[key] = max(
                    -0.12, min(0.12, feature_adjustments.get(key, 0.0) + delta)
                )

    return dampened_outliers, feature_adjustments, rated_tags
