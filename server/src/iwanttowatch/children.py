"""Child profiles: per-country film certificates, family signals, and themes notes."""

import logging
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from iwanttowatch.llm import LlmError, LlmProvider, provider_from_settings
from iwanttowatch.models import Title, User, UserTitle
from iwanttowatch.tmdb import TmdbClient, TmdbError

log = logging.getLogger(__name__)

CERTIFICATIONS_CACHE = timedelta(days=30)
UNRATED = frozenset({"", "NR", "UNRATED", "NOT RATED", "N/A"})

THEMES_SYSTEM = """\
You write brief, balanced "themes and values" notes for parents choosing a film for \
their family. You get a film's title, year, genres, keywords, and overview. In two or \
three short sentences (at most 60 words), describe the main themes, positive values or \
character qualities (such as friendship, courage, kindness, honesty, or perseverance), \
and any intense, scary, or mature elements a parent should know about. Be factual and \
specific to this film, never preachy. Plain text only: no lists, no headings, no \
markdown, no quotation marks around the answer."""


@dataclass(frozen=True)
class Certificate:
    code: str
    meaning: str
    order: int
    adult: bool = False


# Built-in scales for common countries, so India's age-graded U/A certificates work
# even when TMDb's list only has legacy UA, and certificate checks need no network call.
KNOWN_CERTIFICATES: dict[str, tuple[Certificate, ...]] = {
    "IN": (
        Certificate("U", "Unrestricted public exhibition (all ages)", 1),
        Certificate("U/A 7+", "Parental guidance for children under 7", 2),
        Certificate("U/A 13+", "Parental guidance for children under 13", 3),
        Certificate("U/A 16+", "Parental guidance for children under 16", 4),
        Certificate("A", "Restricted to adults (18+)", 5, adult=True),
    ),
    "US": (
        Certificate("G", "General audiences (all ages)", 1),
        Certificate("PG", "Parental guidance suggested", 2),
        Certificate("PG-13", "Parents strongly cautioned (under 13)", 3),
        Certificate("R", "Restricted (17+)", 4, adult=True),
        Certificate("NC-17", "Adults only (18+)", 5, adult=True),
    ),
    "GB": (
        Certificate("U", "Universal, suitable for all", 1),
        Certificate("PG", "Parental guidance", 2),
        Certificate("12A", "Suitable for 12 years and over", 3),
        Certificate("15", "Suitable only for 15 years and over", 4),
        Certificate("18", "Suitable only for adults (18+)", 5, adult=True),
    ),
    "AU": (
        Certificate("G", "General (all ages)", 1),
        Certificate("PG", "Parental guidance recommended", 2),
        Certificate("M", "Mature audiences (15+)", 3),
        Certificate("MA 15+", "Mature accompanied (15+)", 4),
        Certificate("R 18+", "Restricted to 18 and over", 5, adult=True),
    ),
    "CA": (
        Certificate("G", "General audience", 1),
        Certificate("PG", "Parental guidance advised", 2),
        Certificate("14A", "Suitable for 14 years and over", 3),
        Certificate("18A", "Persons under 18 must be accompanied", 4, adult=True),
        Certificate("R", "Restricted to 18 and over", 5, adult=True),
    ),
    "DE": (
        Certificate("0", "Approved for all ages", 1),
        Certificate("6", "Approved for ages 6 and up", 2),
        Certificate("12", "Approved for ages 12 and up", 3),
        Certificate("16", "Approved for ages 16 and up", 4),
        Certificate("18", "No youth admission (18+)", 5, adult=True),
    ),
    "FR": (
        Certificate("U", "Suitable for all audiences", 1),
        Certificate("10", "Not recommended for under 10", 2),
        Certificate("12", "Forbidden for under 12", 3),
        Certificate("16", "Forbidden for under 16", 4),
        Certificate("18", "Forbidden for under 18", 5, adult=True),
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
                max_order = max(int(item["order"]) for item in valid)
                return tuple(
                    Certificate(
                        code=item["certification"].strip(),
                        meaning=(item.get("meaning") or "").strip(),
                        order=int(item["order"]),
                        adult=int(item["order"]) == max_order and len(valid) > 1,
                    )
                    for item in valid
                )
        except TmdbError:
            pass
    # Another country's scale would match none of this country's films.
    return ()


def certificates_for_region(tmdb: TmdbClient | None, region: str) -> list[Certificate]:
    """The certificates a parent can pick as a child's maximum in this country."""
    return [c for c in _scale(region, tmdb) if not c.adult]


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
    """The upper-cased certificate codes at or below a child's limit in the region."""
    limit = certificate_rank(region, max_certificate, tmdb)
    if limit is None:
        return []
    codes = {c.code.upper() for c in _scale(region, tmdb) if c.order <= limit}
    codes |= {code for (r, code), rank in ALIASES.items() if r == region and rank <= limit}
    return sorted(codes)


def allowed_for(title: Title, region: str, allowed: list[str] | None) -> bool:
    """Whether a film's certificate in the region is one a profile may watch.

    `allowed` is the profile's `allowed_certificates`; None means no age limit. Films
    without a certificate in the region, or with an unknown one, are left out.
    """
    if allowed is None:
        return True
    cert = (title.certifications or {}).get(region)
    return cert is not None and cert.strip().upper() in allowed


def equivalent_certificate(
    old_region: str, old_cert: str, new_region: str, tmdb: TmdbClient | None = None
) -> str:
    """Map a child's certificate limit when their parent changes country."""
    options = certificates_for_region(tmdb, new_region)
    if not options:
        return old_cert
    rank = certificate_rank(old_region, old_cert, tmdb) or 1
    best = min(options, key=lambda c: abs(c.order - rank))
    return best.code


def family_tagged_films(session: Session) -> set[int]:
    """Films a parent on this server liked or loved and tagged 'Great with family'."""
    rows = session.execute(
        select(UserTitle.tmdb_id, UserTitle.tags)
        .join(User, User.id == UserTitle.user_id)
        .where(User.parent_id.is_(None), UserTitle.reaction.in_(["liked", "loved"]))
    )
    return {tmdb_id for tmdb_id, tags in rows if tags and "great_with_family" in tags}


def generate_themes_note(session: Session, title: Title, llm: LlmProvider) -> str:
    """Write and store an LLM 'themes and values' note for a film, or return the cached one."""
    if title.themes_note:
        return title.themes_note
    lines = [f"Title: {title.title}" + (f" ({title.year})" if title.year else "")]
    if title.genres:
        lines.append("Genres: " + ", ".join(title.genres))
    if title.keywords:
        lines.append("Keywords: " + ", ".join(title.keywords[:20]))
    if title.overview:
        lines.append(f"Overview: {title.overview}")
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
            generate_themes_note(session, title, llm)
    except LlmError:
        log.warning("Couldn't write themes note for title %s", title.tmdb_id, exc_info=True)
