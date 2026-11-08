"""The fixed vocabulary for "what did you like most?" and "what didn't work?".

A fixed list, rather than free text or LLM-made tags, keeps tags comparable across
films and users, so they can be counted for the persona and used as recommender
features. Every film offers the same core tags in the same order, so a user finds
them in one place each time; then a few more that suit the film's genres and
keywords, and the rest of the list behind "More".
"""

from dataclasses import dataclass, field
from typing import Literal

from iwanttowatch.models import Title

MAX_TAGS = 3
MAX_NOTE = 200
SUGGESTED_PER_FILM = 3

Group = Literal["core", "suggested", "more"]


@dataclass(frozen=True)
class Tag:
    id: str
    label: str
    positive: bool
    genres: frozenset[str] = field(default_factory=frozenset)
    keywords: frozenset[str] = field(default_factory=frozenset)


def _split(text: str) -> frozenset[str]:
    return frozenset(part.strip() for part in text.split(",") if part.strip())


def _tag(id: str, label: str, positive: bool, genres: str = "", keywords: str = "") -> Tag:
    return Tag(id, label, positive, _split(genres), _split(keywords))


TAGS: tuple[Tag, ...] = (
    # Liked or loved.
    _tag("great_story", "Great story", True),
    _tag("great_acting", "Great acting", True),
    _tag("great_direction", "Great direction", True),
    _tag("beautiful_visuals", "Beautiful visuals", True, "Animation,Fantasy,Science Fiction,Adventure,War"),
    _tag("great_music", "Great music", True, "Music,Romance,Animation", "musical,song"),
    _tag("sharp_dialogue", "Sharp dialogue", True, "Comedy,Drama,Crime"),
    _tag("exciting", "Exciting", True, "Action,Adventure,Thriller"),
    _tag("great_action", "Great action scenes", True, "Action", "martial arts,car chase,fight"),
    _tag("unexpected_suspense", "Unexpected suspense", True, "Thriller,Mystery,Crime,Horror", "suspense"),
    _tag("clever_twist", "Clever twist", True, "Thriller,Mystery,Science Fiction", "twist ending,plot twist"),
    _tag("great_villain", "Great villain performance", True, "Thriller,Crime,Action,Horror", "villain,serial killer,psychopath"),
    _tag("genuinely_scary", "Genuinely scary", True, "Horror"),
    _tag("made_me_laugh", "Made me laugh", True, "Comedy", "satire,dark comedy"),
    _tag("feel_good", "Feel-good", True, "Comedy,Family,Romance,Animation,Music"),
    _tag("moved_me", "Moved me", True, "Drama,Romance,War", "grief,loss of loved one"),
    _tag("lovely_romance", "Lovely romance", True, "Romance", "love,wedding"),
    _tag("relatable_characters", "Relatable characters", True, "Drama,Comedy,Family"),
    _tag("slice_of_life", "Slice of life", True, "Drama,Comedy", "small town,family relationships,village"),
    _tag("felt_real", "Felt real", True, "Drama,Crime,History,Documentary", "based on true story,biography"),
    _tag("thought_provoking", "Thought-provoking", True, "Drama,Science Fiction,Documentary", "dystopia,philosophy,social issues"),
    _tag("mind_bending", "Mind-bending", True, "Science Fiction,Mystery,Fantasy", "time travel,dream,parallel world"),
    _tag("world_building", "Great world-building", True, "Fantasy,Science Fiction,Animation"),
    _tag("epic_scale", "Epic scale", True, "History,War,Adventure,Fantasy", "epic"),
    _tag("great_with_family", "Great with family", True, "Family,Animation"),
    _tag("learned_something", "Learned something", True, "Documentary,History", "biography,historical figure"),
    # Didn't like.
    _tag("weak_story", "Weak story", False),
    _tag("predictable", "Predictable", False),
    _tag("too_slow", "Too slow", False),
    _tag("too_long", "Too long", False),
    _tag("unconvincing_acting", "Unconvincing acting", False),
    _tag("disappointing_ending", "Disappointing ending", False, "Thriller,Mystery,Drama,Science Fiction"),
    _tag("cliched", "Clichéd", False, "Action,Romance,Horror,Comedy"),
    _tag("too_violent", "Too violent", False, "Action,Horror,Crime,War,Thriller", "gore,violence"),
    _tag("not_funny", "Not funny", False, "Comedy"),
    _tag("not_scary", "Not scary", False, "Horror"),
    _tag("confusing", "Confusing", False, "Science Fiction,Mystery,Fantasy", "time travel,nonlinear timeline"),
    _tag("overhyped", "Overhyped", False),
)  # fmt: skip

BY_ID = {tag.id: tag for tag in TAGS}

# Shown for every film, in this order.
CORE = {
    True: (
        "great_story", "great_acting", "great_direction", "great_music", "beautiful_visuals",
        "sharp_dialogue", "made_me_laugh", "moved_me", "unexpected_suspense", "exciting",
    ),
    False: (
        "weak_story", "predictable", "too_slow", "too_long", "unconvincing_acting",
        "disappointing_ending", "cliched", "overhyped",
    ),
}  # fmt: skip


def options_for(title: Title, positive: bool) -> list[tuple[Tag, Group]]:
    """Every tag of one polarity: the core row, then the best fits for the film's genres
    and keywords, then the rest in list order."""
    genres, keywords = set(title.genres), set(title.keywords)

    def fit(tag: Tag) -> int:
        return 2 * len(tag.keywords & keywords) + len(tag.genres & genres)

    core = [BY_ID[id] for id in CORE[positive]]
    others = [t for t in TAGS if t.positive == positive and t not in core]
    fitting = sorted((t for t in others if fit(t) > 0), key=fit, reverse=True)
    suggested = fitting[:SUGGESTED_PER_FILM]
    return (
        [(t, "core") for t in core]
        + [(t, "suggested") for t in suggested]
        + [(t, "more") for t in others if t not in suggested]
    )
