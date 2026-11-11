"""Child profiles: per-country film certificates, age limits, family signals, and themes notes."""

import logging
import re
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from iwanttowatch.llm import LlmError, LlmProvider, provider_from_settings
from iwanttowatch.models import Title, User, UserTitle
from iwanttowatch.tmdb import TmdbClient, TmdbError

log = logging.getLogger(__name__)

CERTIFICATIONS_CACHE = timedelta(days=30)
UNRATED = frozenset({"", "NR", "UNRATED", "NOT RATED", "N/A"})

THEMES_SYSTEM = """\
You write brief, structured "themes and values" notes for films in bullet point format. \
Answer with exactly four bullet points (each starting with a hyphen "- "), answering \
these questions in order:
- What values does this film show ? (provide maximum of 3 or 4 keywords)
- Is this based on a real story ? (answer under 15 words, or "No")
- Is this a remake of any of the films I watched already or any other popular movies from \
another language ? (answer under 15 words, or "No")
- What are the famous other films by the same director / writer (answer under 20 words)

Format the four bullet points as:
- Values: <maximum of 3 or 4 keywords>
- Real story: <answer under 15 words, or "No">
- Remake: <answer under 15 words, or "No">
- Other famous films: <answer under 20 words>

Be factual, concise, and specific. Plain text only: exactly four bullet points starting \
with "- ", no markdown headings, no intro or outro."""


@dataclass(frozen=True)
class Certificate:
    code: str
    meaning: str
    order: int
    # The youngest age the certificate suits, which is how a child's birth year picks
    # the films they may see; None when it can't be told from the certificate.
    age: int | None = None


# Built-in scales for common countries, so India's age-graded U/A certificates work
# even when TMDb's list only has legacy UA, and certificate checks need no network call.
KNOWN_CERTIFICATES: dict[str, tuple[Certificate, ...]] = {
    "IN": (
        Certificate("U", "Unrestricted public exhibition (all ages)", 1, 0),
        Certificate("U/A 7+", "Parental guidance for children under 7", 2, 7),
        Certificate("U/A 13+", "Parental guidance for children under 13", 3, 13),
        Certificate("U/A 16+", "Parental guidance for children under 16", 4, 16),
        Certificate("A", "Restricted to adults (18+)", 5, 18),
    ),
    "US": (
        Certificate("G", "General audiences (all ages)", 1, 0),
        Certificate("PG", "Parental guidance suggested", 2, 8),
        Certificate("PG-13", "Parents strongly cautioned (under 13)", 3, 13),
        Certificate("R", "Restricted (17+)", 4, 17),
        Certificate("NC-17", "Adults only (18+)", 5, 18),
    ),
    "GB": (
        Certificate("U", "Universal, suitable for all", 1, 0),
        Certificate("PG", "Parental guidance", 2, 8),
        Certificate("12A", "Suitable for 12 years and over", 3, 12),
        Certificate("15", "Suitable only for 15 years and over", 4, 15),
        Certificate("18", "Suitable only for adults (18+)", 5, 18),
    ),
    "AU": (
        Certificate("G", "General (all ages)", 1, 0),
        Certificate("PG", "Parental guidance recommended", 2, 8),
        Certificate("M", "Mature audiences (15+)", 3, 15),
        Certificate("MA 15+", "Mature accompanied (15+)", 4, 15),
        Certificate("R 18+", "Restricted to 18 and over", 5, 18),
    ),
    "CA": (
        Certificate("G", "General audience", 1, 0),
        Certificate("PG", "Parental guidance advised", 2, 8),
        Certificate("14A", "Suitable for 14 years and over", 3, 14),
        Certificate("18A", "Persons under 18 must be accompanied", 4, 18),
        Certificate("R", "Restricted to 18 and over", 5, 18),
    ),
    "DE": (
        Certificate("0", "Approved for all ages", 1, 0),
        Certificate("6", "Approved for ages 6 and up", 2, 6),
        Certificate("12", "Approved for ages 12 and up", 3, 12),
        Certificate("16", "Approved for ages 16 and up", 4, 16),
        Certificate("18", "No youth admission (18+)", 5, 18),
    ),
    "FR": (
        Certificate("U", "Suitable for all audiences", 1, 0),
        Certificate("10", "Not recommended for under 10", 2, 10),
        Certificate("12", "Forbidden for under 12", 3, 12),
        Certificate("16", "Forbidden for under 16", 4, 16),
        Certificate("18", "Forbidden for under 18", 5, 18),
    ),
}

# Older TMDb entries use pre-2024 CBFC "UA" / "U/A" (12+ parental guidance) or alternate spacing.
ALIASES: dict[tuple[str, str], int] = {
    ("IN", "UA"): 3,
    ("IN", "U/A"): 3,
    ("IN", "UA 7+"): 2,
    ("IN", "UA 13+"): 3,
    ("IN", "UA 16+"): 4,
    ("IN", "S"): 5,
    ("GB", "12"): 3,
    ("GB", "R18"): 5,
    ("AU", "MA15+"): 4,
    ("AU", "R18+"): 5,
    ("AU", "X 18+"): 5,
    ("AU", "X18+"): 5,
    ("US", "X"): 5,
}


def _code_age(code: str, order: int, lowest_order: int) -> int | None:
    """A certificate's youngest age from TMDb's list: the number in its code ("12",
    "16+"), 0 for the country's lowest ("all ages") one, and unknown for the rest."""
    digits = re.search(r"\d+", code)
    if digits:
        return int(digits.group())
    return 0 if order == lowest_order else None


def _scale(region: str, tmdb: TmdbClient | None = None) -> tuple[Certificate, ...]:
    if region in KNOWN_CERTIFICATES:
        return KNOWN_CERTIFICATES[region]
    if tmdb is not None:
        try:
            raw = tmdb.get("/certification/movie/list", None, CERTIFICATIONS_CACHE)
            items = raw.get("certifications", {}).get(region) or []
            valid = sorted(
                (
                    item
                    for item in items
                    if (cert := (item.get("certification") or "").strip())
                    and cert.upper() not in UNRATED
                    and int(item.get("order") or 0) > 0
                ),
                key=lambda item: int(item["order"]),
            )
            if valid:
                lowest = int(valid[0]["order"])
                return tuple(
                    Certificate(
                        code=item["certification"].strip(),
                        meaning=(item.get("meaning") or "").strip(),
                        order=int(item["order"]),
                        age=_code_age(item["certification"].strip(), int(item["order"]), lowest),
                    )
                    for item in valid
                )
        except TmdbError:
            pass
    # Another country's scale would match none of this country's films.
    return ()


def region_certificates(region: str, tmdb: TmdbClient | None = None) -> list[str]:
    """The region's film certificate codes from mildest to strictest."""
    return [c.code for c in _scale(region, tmdb)]


def certificate_rank(region: str, certificate: str, tmdb: TmdbClient | None = None) -> int | None:
    """Numeric age rank of a certificate in a country, or None when unrated/unknown."""
    code = certificate.strip()
    if not code or code.upper() in UNRATED:
        return None
    if (alias := ALIASES.get((region, code.upper()))) is not None:
        return alias
    for item in _scale(region, tmdb):
        if item.code.upper() == code.upper():
            return item.order
    return None


def allowed_certificates(region: str, max_certificate: str, tmdb: TmdbClient | None) -> list[str]:
    """The upper-cased certificate codes at or below a limit in the region."""
    limit = certificate_rank(region, max_certificate, tmdb)
    if limit is None:
        return []
    codes = {c.code.upper() for c in _scale(region, tmdb) if c.order <= limit}
    codes |= {code for (r, code), rank in ALIASES.items() if r == region and rank <= limit}
    return sorted(codes)


def age_for_certificate(
    region: str, certificate: str, tmdb: TmdbClient | None = None
) -> int | None:
    """The youngest age a certificate suits in a country, or None when unknown."""
    rank = certificate_rank(region, certificate, tmdb)
    return next((c.age for c in _scale(region, tmdb) if c.order == rank), None)


def child_age(user: User, today: date | None = None) -> int | None:
    """A child's age this year, from their birth year; None without one."""
    if user.birth_year is None:
        return None
    return max(0, (today or date.today()).year - user.birth_year)


def limit_for_age(
    region: str, age: int, tmdb: TmdbClient | None = None
) -> tuple[str, list[str]] | None:
    """The strictest-rated certificate a child of this age may watch in the country, with
    every certificate code up to it; None when the country's scale has no usable ages."""
    fits = [c for c in _scale(region, tmdb) if c.age is not None and c.age <= age]
    if not fits:
        return None
    top = max(fits, key=lambda c: c.order)
    return top.code, allowed_certificates(region, top.code, tmdb)


def refresh_limit(user: User, tmdb: TmdbClient | None, today: date | None = None) -> bool:
    """Work out a child's age limit from their birth year and country. False when it
    couldn't be, which leaves the earlier limit in place."""
    age = child_age(user, today)
    if age is None:
        return False
    limit = limit_for_age(user.region, age, tmdb)
    if limit is None:
        return False
    user.max_certificate, user.allowed_certificates = limit
    return True


def allowed_for(title: Title, region: str, allowed: list[str] | None) -> bool:
    """Whether a film's certificate in the region is one a profile may watch.

    `allowed` is the profile's `allowed_certificates`; None means no age limit. Films
    without a certificate in the region, or with an unknown one, are left out.
    """
    if allowed is None:
        return True
    cert = (title.certifications or {}).get(region)
    return cert is not None and cert.strip().upper() in allowed


def family_tagged_films(session: Session) -> set[int]:
    """Films an adult on this server liked or loved and tagged 'Great with family'."""
    rows = session.execute(
        select(UserTitle.tmdb_id, UserTitle.tags)
        .join(User, User.id == UserTitle.user_id)
        .where(User.is_child.is_(False), UserTitle.reaction.in_(["liked", "loved"]))
    )
    return {tmdb_id for tmdb_id, tags in rows if tags and "great_with_family" in tags}


def library_owners(session: Session, user: User) -> list[int]:
    """Whose Jellyfin libraries a profile can play from. A child has no Jellyfin account,
    so they play from the household's: every adult's."""
    if not user.is_child:
        return [user.id]
    return list(session.scalars(select(User.id).where(User.is_child.is_(False))))


def user_watched_titles(session: Session, user_id: int, limit: int = 50) -> list[str]:
    """Films the user has watched or rated, most recent first."""
    rows = session.scalars(
        select(Title.title)
        .join(UserTitle, UserTitle.tmdb_id == Title.tmdb_id)
        .where(
            UserTitle.user_id == user_id,
            or_(
                UserTitle.watched.is_(True),
                UserTitle.rating.is_not(None),
                UserTitle.reaction.is_not(None),
            ),
        )
        .order_by(UserTitle.updated_at.desc())
        .limit(limit)
    )
    seen_titles: set[str] = set()
    result: list[str] = []
    for t in rows:
        if t and t not in seen_titles:
            seen_titles.add(t)
            result.append(t)
    return result


def generate_themes_note(
    session: Session,
    title: Title,
    llm: LlmProvider,
    user_id: int | None = None,
    force: bool = False,
) -> str:
    """Write and store an LLM 'themes and values' note for a film, or return the cached one."""
    if title.themes_note and not force:
        return title.themes_note
    lines = [f"Title: {title.title}" + (f" ({title.year})" if title.year else "")]
    if title.original_title and title.original_title != title.title:
        lines.append(f"Original title: {title.original_title}")
    if title.original_language:
        lines.append(f"Original language: {title.original_language}")
    if title.genres:
        lines.append("Genres: " + ", ".join(title.genres))
    if title.keywords:
        lines.append("Keywords: " + ", ".join(title.keywords[:20]))
    if title.overview:
        lines.append(f"Overview: {title.overview}")
    if title.directors:
        directors = [d["name"] for d in title.directors if isinstance(d, dict) and d.get("name")]
        if directors:
            lines.append(f"Director: {', '.join(directors[:3])}")
    if title.writers:
        writers = [w["name"] for w in title.writers if isinstance(w, dict) and w.get("name")]
        if writers:
            lines.append(f"Writer: {', '.join(writers[:3])}")
    if user_id is not None:
        watched = user_watched_titles(session, user_id)
        if watched:
            lines.append(f"Films I watched already: {', '.join(watched)}")
        else:
            lines.append("Films I watched already: None")
    else:
        lines.append("Films I watched already: None")
    text = llm.generate(THEMES_SYSTEM, "\n".join(lines)).strip().strip('"“”').strip()
    if not text:
        raise LlmError("The LLM returned an empty answer")
    title.themes_note = text
    session.commit()
    return text


def ensure_themes_note_quietly(session: Session, title: Title, user_id: int) -> None:
    """Populate a film's themes note when an LLM is configured; ignore LLM failures."""
    if title.themes_note is not None:
        return
    try:
        llm = provider_from_settings(session, "themes", user_id)
        if llm is not None:
            generate_themes_note(session, title, llm, user_id=user_id)
    except LlmError:
        log.warning("Couldn't write themes note for title %s", title.tmdb_id, exc_info=True)
