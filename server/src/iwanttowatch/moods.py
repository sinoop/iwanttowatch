"""Mood tags for feed cards, from a film's TMDb genres and keywords.

A small curated vocabulary, like the rating tags: the same mood means the same
thing on every card, and no LLM is needed.
"""

from dataclasses import dataclass

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


def moods_for(title: Title) -> list[str]:
    """Up to two moods: keyword matches first, then genre matches, in vocabulary order."""
    genres, keywords = set(title.genres), set(title.keywords)
    scored = [
        (2 * len(mood.keywords & keywords) + len(mood.genres & genres), -n, mood.label)
        for n, mood in enumerate(MOODS)
    ]
    return [label for score, _, label in sorted(scored, reverse=True) if score > 0][:MAX_MOODS]
