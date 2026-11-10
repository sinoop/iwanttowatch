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

MAX_TAGS = 5
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


def _split_genres(text: str) -> frozenset[str]:
    return frozenset(part.strip() for part in text.split(",") if part.strip())


def _split_keywords(text: str) -> frozenset[str]:
    return frozenset(part.strip().lower() for part in text.split(",") if part.strip())


def _tag(id: str, label: str, positive: bool, genres: str = "", keywords: str = "") -> Tag:
    return Tag(id, label, positive, _split_genres(genres), _split_keywords(keywords))


TAGS: tuple[Tag, ...] = (
    # Liked or loved.
    _tag("great_story", "Great story", True),
    _tag("great_acting", "Great acting", True),
    _tag("great_direction", "Great direction", True),
    _tag("beautiful_visuals", "Beautiful visuals", True, "Animation,Fantasy,Science Fiction,Adventure,War", "cgi,visual effects,cinematography,animation"),
    _tag("great_music", "Great music", True, "Music,Romance,Animation", "musical,song,soundtrack,score"),
    _tag("sharp_dialogue", "Sharp dialogue", True, "Comedy,Drama,Crime", "witty,dialogue,banter"),
    _tag("exciting", "Exciting", True, "Action,Adventure,Thriller", "suspense,chase,action hero"),
    _tag("great_action", "Great action scenes", True, "Action,Adventure", "martial arts,car chase,fight,gunfight,superhero,shootout,battle,stunt"),
    _tag("unexpected_suspense", "Unexpected suspense", True, "Thriller,Mystery,Crime,Horror", "suspense,tension,investigation"),
    _tag("clever_twist", "Clever twist", True, "Thriller,Mystery,Science Fiction", "twist ending,plot twist,surprise ending"),
    _tag("great_villain", "Great villain performance", True, "Thriller,Crime,Action,Horror", "villain,serial killer,psychopath,antagonist"),
    _tag("genuinely_scary", "Genuinely scary", True, "Horror,Thriller", "ghost,haunted,jump scare,demon,monster,slasher,supernatural"),
    _tag("made_me_laugh", "Made me laugh", True, "Comedy", "satire,dark comedy,parody,humor,funny"),
    _tag("feel_good", "Feel-good", True, "Comedy,Family,Romance,Animation,Music", "uplifting,wholesome,heartwarming,friendship"),
    _tag("moved_me", "Moved me", True, "Drama,Romance,War", "grief,loss of loved one,tragedy,tearjerker"),
    _tag("lovely_romance", "Lovely romance", True, "Romance", "love,wedding,dating,romantic relationship"),
    _tag("relatable_characters", "Relatable characters", True, "Drama,Comedy,Family", "coming of age,everyday life,family relationships"),
    _tag("slice_of_life", "Slice of life", True, "Drama,Comedy", "small town,family relationships,village,daily life"),
    _tag("felt_real", "Felt real", True, "Drama,Crime,History,Documentary", "based on true story,biography,historical,realistic"),
    _tag("thought_provoking", "Thought-provoking", True, "Drama,Science Fiction,Documentary", "dystopia,philosophy,social issues,morality,existential"),
    _tag("mind_bending", "Mind-bending", True, "Science Fiction,Mystery,Fantasy", "time travel,dream,parallel world,multiverse,reality"),
    _tag("world_building", "Great world-building", True, "Fantasy,Science Fiction,Animation,Adventure", "alien,magic,kingdom,mythology,dystopia"),
    _tag("epic_scale", "Epic scale", True, "History,War,Adventure,Fantasy", "epic,battle,dynasty,empire,spectacle"),
    _tag("great_with_family", "Great with family", True, "Family,Animation", "children,kids,family,wholesome,friendship"),
    _tag("learned_something", "Learned something", True, "Documentary,History", "biography,historical figure,investigation,nature"),
    _tag("great_cinematography", "Stunning cinematography", True, "Drama,Adventure,History,War,Western", "cinematography,visuals,landscape,camera"),
    _tag("great_pacing", "Great pacing", True, "Action,Thriller,Mystery,Crime,Adventure", "fast-paced,gripping,page-turner"),
    _tag("creative_original", "Original concept", True, "Science Fiction,Fantasy,Comedy,Mystery", "unique,original,inventive,surreal"),
    _tag("great_chemistry", "Great chemistry", True, "Drama,Romance,Crime", "ensemble,buddy,duo,chemistry,friendship"),
    _tag("atmospheric", "Atmospheric", True, "Horror,Mystery,Drama", "moody,gothic,noir,atmospheric,isolation"),
    _tag("cozy_comfort", "Cozy & comfort watch", True, "Comedy,Family,Animation", "comfort,cozy,wholesome,nostalgia,holiday"),
    _tag("dark_intense", "Dark & intense", True, "Crime,Drama,Horror", "gritty,violence,dark,intense,bleak,brutal"),
    _tag("rewatchable", "Highly rewatchable", True, "Comedy,Action,Science Fiction,Animation", "cult,classic,fun,favorite"),
    # Didn't like.
    _tag("weak_story", "Weak story", False, "Drama,Action,Thriller,Science Fiction", "poor writing,plothole"),
    _tag("predictable", "Predictable", False, "Mystery,Thriller,Romance,Horror", "formulaic,predictable"),
    _tag("too_slow", "Too slow", False, "Drama,Mystery,Western,Horror", "slow burn,slow,pacing"),
    _tag("too_long", "Too long", False, "Drama,History,Action,War", "runtime,long"),
    _tag("unconvincing_acting", "Unconvincing acting", False, "Drama,Romance,Horror", "acting,performance"),
    _tag("disappointing_ending", "Disappointing ending", False, "Thriller,Mystery,Drama,Science Fiction", "ending,anti-climax,twist"),
    _tag("cliched", "Clichéd", False, "Action,Romance,Horror,Comedy", "cliche,trope,formulaic"),
    _tag("too_violent", "Too violent", False, "Action,Horror,Crime,War,Thriller", "gore,violence,bloody,torture"),
    _tag("not_funny", "Not funny", False, "Comedy", "unfunny,bad humor"),
    _tag("not_scary", "Not scary", False, "Horror", "tame,unfrightening"),
    _tag("confusing", "Confusing", False, "Science Fiction,Mystery,Fantasy", "time travel,nonlinear timeline,convoluted"),
    _tag("overhyped", "Overhyped", False),
    _tag("pacing_issues", "Pacing issues / Drags", False, "Drama,Action,Adventure,Science Fiction", "drag,uneven,filler"),
    _tag("flat_characters", "Flat characters", False, "Drama,Action,Horror,Thriller", "shallow,unlikable,forgettable"),
    _tag("plot_holes", "Plot holes / Illogical", False, "Thriller,Mystery,Science Fiction,Action", "plothole,contrived,nonsense"),
    _tag("cringe_dialogue", "Awkward dialogue", False, "Romance,Drama,Comedy,Action", "dialogue,cringe,cheesy"),
    _tag("poor_cgi", "Poor CGI / effects", False, "Science Fiction,Fantasy,Action,Adventure", "cgi,effects,green screen,cheap"),
    _tag("wasted_potential", "Wasted potential", False, "Drama,Science Fiction,Fantasy,Thriller", "disappointing,underwhelming,missed opportunity"),
    _tag("boring", "Boring", False, "Drama,Documentary,Horror", "dull,tedious,uninteresting"),
    _tag("inconsistent_tone", "Inconsistent tone", False, "Comedy,Horror,Drama,Action", "tonal clash,jarring,mood swings"),
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
    genres = set(title.genres)
    keywords = {k.strip().lower() for k in title.keywords}

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
