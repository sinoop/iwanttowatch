"""Mood tags for feed cards.

A small curated vocabulary, like the rating tags: the same mood means the same
thing on every card. When an LLM is configured it picks each film's moods from the
vocabulary, once per film; until then, or without one, they come from the film's TMDb
genres and keywords.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from iwanttowatch.llm import LlmError, LlmProvider
from iwanttowatch.models import Title

MAX_MOODS = 2


@dataclass(frozen=True)
class Mood:
    label: str
    genres: frozenset[str]
    keywords: frozenset[str]


def _mood(label: str, genres: str, keywords: str) -> Mood:
    def split(text: str) -> frozenset[str]:
        return frozenset(part.strip() for part in text.split(",") if part.strip())

    return Mood(label, split(genres), split(keywords))


MOODS: tuple[Mood, ...] = (
    _mood("Mind-bending", "", "time travel,dream,parallel world,twist ending,plot twist,nonlinear timeline,alternate reality,time loop"),
    _mood("Thrilling", "Thriller,Action", "suspense,chase,cat and mouse,heist,hostage"),
    _mood("Dark", "", "revenge,murder,serial killer,psychological thriller,dark comedy,corruption,gangster,violence"),
    _mood("Scary", "Horror", "supernatural,ghost,haunted house,possession,monster"),
    _mood("Feel-good", "Family,Animation,Music", "feel-good,friendship,heartwarming,coming of age,underdog"),
    _mood("Funny", "Comedy", "satire,parody,slapstick,spoof"),
    _mood("Romantic", "Romance", "love,romance,wedding,love triangle"),
    _mood("Heartfelt", "", "family relationships,grief,loss of loved one,father son relationship,mother daughter relationship,small town,village"),
    _mood("Epic", "War,History", "epic,battle,kingdom,war"),
    _mood("True story", "Documentary", "based on true story,biography,based on real events,historical figure"),
)  # fmt: skip


LABELS = {mood.label.casefold(): mood.label for mood in MOODS}

MOODS_SYSTEM = f"""You tag films with moods for a movie app. For each numbered film, pick
up to {MAX_MOODS} moods that best describe how it feels to watch, only from this list:
{", ".join(mood.label for mood in MOODS)}.
Judge the film itself, not its genre alone: a gentle prison drama is not Scary, and a
tragedy is not Feel-good. Use an empty list when none fits well. Answer with only JSON,
no markdown, in this form: {{"moods": [{{"n": 1, "moods": ["Dark", "Thrilling"]}}]}}"""


def moods_for(title: Title) -> list[str]:
    """Up to two moods: the LLM's when it has tagged the film, otherwise keyword matches
    first, then genre matches, in vocabulary order."""
    if title.ai_moods is not None:
        return title.ai_moods[:MAX_MOODS]
    genres, keywords = set(title.genres), set(title.keywords)
    scored = [
        (2 * len(mood.keywords & keywords) + len(mood.genres & genres), -n, mood.label)
        for n, mood in enumerate(MOODS)
    ]
    return [label for score, _, label in sorted(scored, reverse=True) if score > 0][:MAX_MOODS]


def parse_moods(value: Any) -> list[str] | None:
    """The vocabulary moods in an LLM's answer for one film; None when it gave none."""
    if not isinstance(value, list):
        return None
    labels = [LABELS.get(v.strip().casefold()) for v in value if isinstance(v, str)]
    return list(dict.fromkeys(label for label in labels if label))[:MAX_MOODS]


def tag_moods(llm: LlmProvider, titles: Sequence[Title]) -> int:
    """Ask the LLM for each film's moods and set them; returns how many it tagged.

    The prompt describes the films only, never who is watching.
    """

    def line(n: int, t: Title) -> str:
        original = f" / {t.original_title}" if t.original_title != t.title else ""
        about = ", ".join([str(t.year or "?"), t.original_language, *t.genres[:3]])
        keywords = f"; keywords: {', '.join(t.keywords[:8])}" if t.keywords else ""
        return f"{n}. {t.title}{original} ({about}{keywords}): {t.overview[:300]}"

    prompt = "\n".join(line(n, t) for n, t in enumerate(titles, 1))
    text = llm.generate(MOODS_SYSTEM, prompt, json_reply=True)
    try:
        answer = json.loads(text[text.index("{") : text.rindex("}") + 1])
    except ValueError as error:
        raise LlmError("The LLM's answer wasn't JSON") from error
    if not isinstance(answer, dict):
        raise LlmError("The LLM's answer wasn't a JSON object")
    tagged = 0
    for item in answer.get("moods") or []:
        if not isinstance(item, dict):
            continue
        n, moods = item.get("n"), parse_moods(item.get("moods"))
        if isinstance(n, int) and 1 <= n <= len(titles) and moods is not None:
            titles[n - 1].ai_moods = moods
            tagged += 1
    return tagged
