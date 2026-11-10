"""A read-only MCP server for debugging, at /mcp, protected by an admin-created key.

It speaks the subset of the Model Context Protocol a tools-only server needs, over
Streamable HTTP with plain JSON replies: initialize, ping, tools/list, and tools/call.
"""

import hashlib
import hmac
import json
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Body, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from iwanttowatch.api.deps import DbSession
from iwanttowatch.availability import is_stale, watchable
from iwanttowatch.children import allowed_for, library_owners
from iwanttowatch.db import utcnow
from iwanttowatch.feed import hidden, is_documentary, is_non_movie, seen, shortlisted
from iwanttowatch.imdb import enabled as imdb_enabled
from iwanttowatch.jellyfin import STATUS_KEY as JELLYFIN_STATUS
from iwanttowatch.jellyfin import URL_SETTING as JELLYFIN_URL
from iwanttowatch.llm import llm_order
from iwanttowatch.models import (
    AiPick,
    Availability,
    ConnectorStatus,
    Explanation,
    Feedback,
    FeedBuild,
    GroupShortlistItem,
    ImportJob,
    LibraryItem,
    LlmCall,
    Recommendation,
    Title,
    User,
    UserTitle,
    get_setting,
    set_setting,
)
from iwanttowatch.moods import moods_for
from iwanttowatch.tmdb import API_KEY_SETTING

router = APIRouter()
KEY_SETTING = "mcp_key_sha256"
# Newest first; a client asking for another version gets the newest.
PROTOCOL_VERSIONS = ["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"]
INSTRUCTIONS = (
    "Read-only view of an iWantToWatch server for debugging recommendations. Start with "
    "server_status or list_users; feed shows a user's feed as stored at the last build, "
    "with why films are hidden; explain_title says everything known about one film for "
    "one user; find_title turns a name into a TMDb ID; llm_calls and llm_call show the AI "
    "log. Nothing here changes data."
)


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def create_key(session: Session) -> str:
    """A new key, replacing any earlier one; only its hash is stored."""
    key = "iwtw_" + secrets.token_urlsafe(32)
    set_setting(session, KEY_SETTING, _hash(key))
    return key


def _authorised(session: Session, request: Request) -> bool:
    stored = get_setting(session, KEY_SETTING)
    scheme, _, key = request.headers.get("authorization", "").partition(" ")
    return bool(stored and scheme.lower() == "bearer" and hmac.compare_digest(stored, _hash(key)))


def _utc(value: datetime | None) -> str | None:
    # SQLite returns stored UTC times without their time zone.
    return value.replace(tzinfo=UTC).isoformat(timespec="seconds") if value else None


class ToolError(Exception):
    """A problem with a tool's arguments, reported to the client as a tool error."""


def _user(session: Session, name: str) -> User:
    lowered = name.strip().lower()
    users = session.scalars(select(User)).all()
    for match in (
        lambda u: str(u.id) == lowered,
        lambda u: u.username.lower() == lowered,
        lambda u: u.display_name.lower() == lowered,
    ):
        found = [u for u in users if match(u)]
        if len(found) == 1:
            return found[0]
    known = ", ".join(u.username for u in users)
    raise ToolError(f"No single user matches {name!r}. Users: {known}")


def _film(title: Title) -> str:
    return f"{title.title} ({title.year or '?'}, {title.original_language})"


def _build(session: Session, user_id: int) -> dict[str, Any] | None:
    state = session.get(FeedBuild, user_id)
    if state is None:
        return None
    return {
        "status": state.status,
        "step": state.step,
        "error": state.error,
        "built_at": _utc(state.built_at),
    }


# Tools. Each takes a session and its validated arguments and returns JSON-ready data.


class NoArgs(BaseModel):
    pass


def server_status(session: Session, _args: NoArgs) -> dict[str, Any]:
    jellyfin = session.get(ConnectorStatus, JELLYFIN_STATUS)
    jobs = session.scalars(select(ImportJob).order_by(ImportJob.id.desc()).limit(5))
    builds = session.execute(
        select(User.username, FeedBuild).join(FeedBuild, FeedBuild.user_id == User.id)
    ).all()
    return {
        "tmdb_configured": get_setting(session, API_KEY_SETTING) is not None,
        "llm_order": llm_order(session),
        "imdb_ratings": imdb_enabled(session),
        "jellyfin": {
            "connected": get_setting(session, JELLYFIN_URL) is not None,
            "synced_at": _utc(jellyfin.synced_at) if jellyfin else None,
            "error": jellyfin.error if jellyfin else None,
            "last_webhook_at": _utc(jellyfin.webhook_at) if jellyfin else None,
            "library_items": session.scalar(select(func.count()).select_from(LibraryItem)),
        },
        "counts": {
            "users": session.scalar(select(func.count()).select_from(User)),
            "titles": session.scalar(select(func.count()).select_from(Title)),
            "availability_rows": session.scalar(select(func.count()).select_from(Availability)),
        },
        "feed_builds": {name: _build(session, build.user_id) for name, build in builds},
        "recent_imports": [
            {
                "id": job.id,
                "source": job.source,
                "status": job.status,
                "error": job.error,
                "created_at": _utc(job.created_at),
            }
            for job in jobs
        ],
    }


def list_users(session: Session, _args: NoArgs) -> list[dict[str, Any]]:
    out = []
    for user in session.scalars(select(User).order_by(User.id)):
        ratings = session.scalar(
            select(func.count(UserTitle.tmdb_id.distinct())).where(
                UserTitle.user_id == user.id, UserTitle.rating.is_not(None)
            )
        )
        out.append(
            {
                "id": user.id,
                "username": user.username,
                "display_name": user.display_name,
                "admin": user.is_admin,
                "child": user.is_child,
                "max_certificate": user.max_certificate,
                "region": user.region,
                "languages": user.languages,
                "subscriptions": user.subscriptions,
                "birth_year": user.birth_year,
                "jellyfin_linked": user.jellyfin_user_id is not None,
                "rated_films": ratings,
                "seen_films": len(seen(session, user.id)),
                "feed": _build(session, user.id),
            }
        )
    return out


class FeedArgs(BaseModel):
    user: str = Field(description="User ID, username, or display name")
    limit: int = Field(20, ge=1, le=200)
    offset: int = Field(0, ge=0)
    include_hidden: bool = Field(
        False,
        description="Also list stored films the feed hides, with why (seen, turned down, "
        "above the age limit, or not playable on Jellyfin or the user's services)",
    )


def _hide_reasons(session: Session, user: User, titles: list[Title]) -> dict[int, list[str]]:
    """Why the Discover feed (with "available to watch" on) leaves each film out."""
    ids = [t.tmdb_id for t in titles]
    watched = seen(session, user.id)
    saved = set(shortlisted(session, user.id))
    turned_down = hidden(session, user.id) - saved
    owners = library_owners(session, user)
    library = set(
        session.scalars(
            select(LibraryItem.tmdb_id).where(
                LibraryItem.user_id.in_(owners), LibraryItem.tmdb_id.in_(ids)
            )
        )
    )
    offers = {
        row.tmdb_id: row.offers
        for row in session.scalars(
            select(Availability).where(
                Availability.region == user.region, Availability.tmdb_id.in_(ids)
            )
        )
    }
    reasons: dict[int, list[str]] = {}
    for title in titles:
        why = []
        if is_documentary(title):
            why.append("documentary")
        elif is_non_movie(title):
            why.append("non-movie (stand-up, concert, featurette, or short)")
        if title.tmdb_id in watched:
            why.append("watched or rated")
        if title.tmdb_id in turned_down:
            why.append("turned down, not interested, or snoozed")
        if not allowed_for(title, user.region, user.allowed_certificates):
            why.append(f"above the age limit ({user.max_certificate}) or no certificate")
        if title.tmdb_id not in library and not any(
            o["kind"] == "flatrate"
            for o in watchable(offers.get(title.tmdb_id, []), user.subscriptions)
        ):
            why.append("not on Jellyfin or a subscribed service")
        reasons[title.tmdb_id] = why
    return reasons


def feed(session: Session, args: FeedArgs) -> dict[str, Any]:
    user = _user(session, args.user)
    rows = session.execute(
        select(Recommendation, Title)
        .join(Title, Title.tmdb_id == Recommendation.tmdb_id)
        .where(Recommendation.user_id == user.id)
        .order_by(Recommendation.rank)
    ).all()
    why_hidden = _hide_reasons(session, user, [title for _, title in rows])
    picks = {p.tmdb_id: p for p in session.scalars(select(AiPick).where(AiPick.user_id == user.id))}
    listed = [
        (rec, title) for rec, title in rows if args.include_hidden or not why_hidden[title.tmdb_id]
    ]
    items = []
    for position, (rec, title) in enumerate(listed[args.offset : args.offset + args.limit]):
        item: dict[str, Any] = {
            "position": args.offset + position + 1,
            "stored_rank": rec.rank,
            "tmdb_id": title.tmdb_id,
            "film": _film(title),
            "match": round(rec.score * 100),
            "reasons": rec.reasons,
        }
        if pick := picks.get(title.tmdb_id):
            item["ai"] = {"added": pick.added, "expects": pick.rating, "why": pick.why}
        if why_hidden[title.tmdb_id]:
            item["hidden_because"] = why_hidden[title.tmdb_id]
        items.append(item)
    return {
        "user": user.username,
        "build": _build(session, user.id),
        "stored": len(rows),
        "shown": sum(not why_hidden[title.tmdb_id] for _, title in rows),
        "items": items,
    }


class TitleArgs(BaseModel):
    user: str = Field(description="User ID, username, or display name")
    tmdb_id: int = Field(description="TMDb movie ID; find_title looks one up by name")


def explain_title(session: Session, args: TitleArgs) -> dict[str, Any]:
    user = _user(session, args.user)
    title = session.get(Title, args.tmdb_id)
    if title is None:
        raise ToolError(f"TMDb {args.tmdb_id} isn't in the local catalogue")
    rec = session.get(Recommendation, (user.id, title.tmdb_id))
    stored = session.scalar(select(func.count()).where(Recommendation.user_id == user.id))
    pick = session.get(AiPick, (user.id, title.tmdb_id))
    feedback = session.get(Feedback, (user.id, title.tmdb_id))
    group = session.get(GroupShortlistItem, title.tmdb_id)
    place = session.get(Availability, (title.tmdb_id, user.region))
    owners = library_owners(session, user)
    on_jellyfin = session.scalar(
        select(LibraryItem.id).where(
            LibraryItem.user_id.in_(owners), LibraryItem.tmdb_id == title.tmdb_id
        )
    )
    why_hidden = _hide_reasons(session, user, [title])[title.tmdb_id]
    if rec is None:
        verdict = "Not in the stored feed: not a candidate at the last build, or new since."
    elif why_hidden:
        verdict = f"Stored at rank {rec.rank + 1} of {stored} but hidden: {'; '.join(why_hidden)}."
    else:
        verdict = f"In the feed at stored rank {rec.rank + 1} of {stored}."
    entries = session.scalars(
        select(UserTitle).where(UserTitle.user_id == user.id, UserTitle.tmdb_id == title.tmdb_id)
    )
    return {
        "verdict": verdict,
        "film": {
            "tmdb_id": title.tmdb_id,
            "imdb_id": title.imdb_id,
            "title": title.title,
            "original_title": title.original_title,
            "year": title.year,
            "language": title.original_language,
            "runtime": title.runtime,
            "genres": title.genres,
            "moods": moods_for(title),
            "moods_from": "AI" if title.ai_moods is not None else "keywords",
            "keywords": title.keywords[:15],
            "directors": [d.get("name") for d in title.directors],
            "certifications": title.certifications,
            "tmdb_votes": {"average": title.vote_average, "count": title.vote_count},
            "imdb": {"rating": title.imdb_rating, "votes": title.imdb_votes},
            "fetched_at": _utc(title.fetched_at),
        },
        "recommendation": {"match": round(rec.score * 100), "reasons": rec.reasons}
        if rec
        else None,
        "ai": {"added": pick.added, "expects": pick.rating, "why": pick.why} if pick else None,
        "why_this": explained.text
        if (explained := session.get(Explanation, (user.id, title.tmdb_id)))
        else None,
        "user_sources": [
            {
                "source": e.source,
                "rating": e.rating,
                "watched": e.watched,
                "watched_at": e.watched_at.isoformat() if e.watched_at else None,
                "favorite": e.favorite,
                "reaction": e.reaction,
                "tags": e.tags,
                "note": e.note,
            }
            for e in entries
        ],
        "feedback": {"kind": feedback.kind, "until": _utc(feedback.until)} if feedback else None,
        "shortlisted": title.tmdb_id in shortlisted(session, user.id),
        "group_shortlist_added_by": group.added_by if group else None,
        "availability": {
            "region": user.region,
            "on_jellyfin": on_jellyfin is not None,
            "offers": [f"{o['name']} ({o['kind']})" for o in place.offers] if place else None,
            "playable_for_user": [o["name"] for o in watchable(place.offers, user.subscriptions)]
            if place
            else [],
            "checked_at": _utc(place.checked_at) if place else None,
            "stale": is_stale(place) if place else None,
        },
    }


class FindArgs(BaseModel):
    query: str = Field(min_length=1, description="Part of a title, original title, or year")
    limit: int = Field(10, ge=1, le=50)


def find_title(session: Session, args: FindArgs) -> list[dict[str, Any]]:
    """Films in the local catalogue; it holds every film imported, rated, or scored."""
    pattern = f"%{args.query.strip()}%"
    titles = session.scalars(
        select(Title)
        .where(or_(Title.title.ilike(pattern), Title.original_title.ilike(pattern)))
        .order_by(Title.vote_count.desc().nulls_last())
        .limit(args.limit)
    )
    return [{"tmdb_id": t.tmdb_id, "film": _film(t)} for t in titles]


class CallsArgs(BaseModel):
    limit: int = Field(10, ge=1, le=200)
    purpose: str | None = Field(
        None, description="suggestions, persona, themes, moods, why, ask, check, or test"
    )
    failed_only: bool = False


def llm_calls(session: Session, args: CallsArgs) -> dict[str, Any]:
    now = utcnow()
    query = (
        select(LlmCall, User.username)
        .outerjoin(User, User.id == LlmCall.user_id)
        .where(LlmCall.created_at >= now - timedelta(days=1))
        .order_by(LlmCall.id.desc())
        .limit(args.limit)
    )
    if args.purpose:
        query = query.where(LlmCall.purpose == args.purpose)
    if args.failed_only:
        query = query.where(LlmCall.error.is_not(None))
    since = {"last_hour": timedelta(hours=1), "last_day": timedelta(days=1)}
    return {
        **{
            name: session.scalar(select(func.count()).where(LlmCall.created_at >= now - delta))
            for name, delta in since.items()
        },
        "calls": [
            {
                "id": call.id,
                "at": _utc(call.created_at),
                "purpose": call.purpose,
                "model": f"{call.provider}/{call.model}",
                "user": name,
                "duration_ms": call.duration_ms,
                "error": call.error,
                "reply_start": (call.reply or "")[:200],
            }
            for call, name in session.execute(query)
        ],
    }


class CallArgs(BaseModel):
    id: int = Field(description="An ID from llm_calls")


def llm_call(session: Session, args: CallArgs) -> dict[str, Any]:
    call = session.get(LlmCall, args.id)
    if call is None:
        raise ToolError(f"No LLM call {args.id}; only the newest 200 are kept")
    return {
        "id": call.id,
        "at": _utc(call.created_at),
        "purpose": call.purpose,
        "model": f"{call.provider}/{call.model}",
        "duration_ms": call.duration_ms,
        "system": call.system,
        "prompt": call.prompt,
        "reply": call.reply,
        "error": call.error,
    }


Tool = tuple[str, type[BaseModel], Callable[[Session, Any], Any]]
TOOLS: dict[str, Tool] = {
    "server_status": (
        "Connectors (TMDb, Jellyfin, LLM order, IMDb ratings), catalogue counts, every "
        "user's feed build state, and recent imports.",
        NoArgs,
        server_status,
    ),
    "list_users": (
        "Every user and child profile with region, languages, services, age limit, "
        "rating counts, and feed build state.",
        NoArgs,
        list_users,
    ),
    "feed": ("A user's feed in order, with match, reasons, and AI picks.", FeedArgs, feed),
    "explain_title": (
        "Everything known about one film for one user: where it stands in their feed and "
        "why, its scores and reasons, their ratings per source, feedback, and availability.",
        TitleArgs,
        explain_title,
    ),
    "find_title": ("Look up TMDb IDs by title in the local catalogue.", FindArgs, find_title),
    "llm_calls": (
        "Recent LLM calls with counts for the last hour and day; llm_call has the full text.",
        CallsArgs,
        llm_calls,
    ),
    "llm_call": ("One LLM call's full system prompt, prompt, and reply.", CallArgs, llm_call),
}


def _schema(model: type[BaseModel]) -> dict[str, Any]:
    schema = model.model_json_schema()
    schema.pop("title", None)
    return {"type": "object", **schema}


def _call_tool(session: Session, params: dict[str, Any]) -> dict[str, Any]:
    name = params.get("name")
    if name not in TOOLS:
        raise _RpcError(-32602, f"Unknown tool: {name}")
    _, model, run = TOOLS[name]
    try:
        result = run(session, model.model_validate(params.get("arguments") or {}))
    except (ToolError, ValidationError) as error:
        return {"content": [{"type": "text", "text": str(error)}], "isError": True}
    finally:
        # Read-only: nothing a tool touched is ever written back.
        session.rollback()
    return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]}


class _RpcError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


def _answer(session: Session, request: Request, message: Any) -> dict[str, Any] | None:
    """The JSON-RPC response to one message, or None for a notification."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Bad request"}}
    if "id" not in message:
        return None
    method, params = message.get("method"), message.get("params") or {}
    try:
        if method == "initialize":
            wanted = params.get("protocolVersion")
            result: dict[str, Any] = {
                "protocolVersion": wanted if wanted in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "iwanttowatch", "version": request.app.version},
                "instructions": INSTRUCTIONS,
            }
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {
                "tools": [
                    {
                        "name": name,
                        "description": description,
                        "inputSchema": _schema(model),
                        "annotations": {"readOnlyHint": True, "openWorldHint": False},
                    }
                    for name, (description, model, _) in TOOLS.items()
                ]
            }
        elif method == "tools/call":
            result = _call_tool(session, params)
        else:
            raise _RpcError(-32601, f"Method not found: {method}")
    except _RpcError as error:
        return {
            "jsonrpc": "2.0",
            "id": message["id"],
            "error": {"code": error.code, "message": str(error)},
        }
    return {"jsonrpc": "2.0", "id": message["id"], "result": result}


@router.post("/mcp", include_in_schema=False)
def mcp(body: Annotated[Any, Body()], request: Request, session: DbSession) -> Response:
    if not _authorised(session, request):
        return JSONResponse(
            {"error": "Create an MCP key in Settings → Debugging and send it as a bearer token"},
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Bearer"},
        )
    if isinstance(body, list):
        answers = [a for m in body if (a := _answer(session, request, m)) is not None]
        reply: Any = answers or None
    else:
        reply = _answer(session, request, body)
    if reply is None:
        # Only notifications or responses: nothing to answer.
        return Response(status_code=status.HTTP_202_ACCEPTED)
    return JSONResponse(reply)


@router.get("/mcp", include_in_schema=False)
@router.delete("/mcp", include_in_schema=False)
def mcp_stream() -> Response:
    # Stateless: no server-sent event stream and no session to end.
    return Response(status_code=status.HTTP_405_METHOD_NOT_ALLOWED, headers={"Allow": "POST"})
