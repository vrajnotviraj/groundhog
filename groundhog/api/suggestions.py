"""Suggested tests: ask Anthropic for new test intents, list them, author one with Jev, dismiss or delete it."""

import ipaddress
import itertools
import re
import secrets
import socket
from typing import Annotated

import anthropic
import httpx
from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field, StringConstraints, ValidationError

from groundhog import db, events
from groundhog.agent import suggester
from groundhog.api import cases
from groundhog.api.auth import admin_only, current_user
from groundhog.api.map import get_map
from groundhog.cases import store
from groundhog.cases.schema import NAME

router = APIRouter(prefix="/suggestions", dependencies=[Depends(current_user)])
SuggestionId = Annotated[str, Path(pattern=r"^[0-9a-f]{12}$")]
DocsUrl = Annotated[str, StringConstraints(pattern=r"^https?://\S{1,2000}$")]
SCRIPTS = re.compile(r"<(script|style)\b.*?</\1\s*>", re.S | re.I)
TAGS = re.compile(r"<[^>]+>")


class SuggestRequest(BaseModel):
    docs_urls: list[DocsUrl] = Field(default_factory=list, max_length=5)
    text: str = Field("", max_length=20_000)
    use_map: bool = True
    count: int = Field(8, ge=1, le=15)


def find(suggestion_id: str) -> dict:
    suggestion = db.suggestions().find_one({"_id": suggestion_id})
    if suggestion is None:
        raise HTTPException(404, f"No suggestion {suggestion_id}.")
    return suggestion


def row(suggestion: dict) -> dict:
    """A suggestion as the UI shows it: `id` for `_id`, plus the status of the run that authored it."""
    run = db.runs().find_one({"_id": suggestion["run_id"]}, {"status": 1}) if suggestion.get("run_id") else None
    return {"id": suggestion.pop("_id"), **suggestion, **({"run_status": run["status"]} if run else {})}


def check_public(url: str) -> None:
    """Refuse a URL whose host resolves to a loopback, private, link-local, reserved or unspecified address."""
    try:
        addresses = [ipaddress.ip_address(info[4][0]) for info in socket.getaddrinfo(httpx.URL(url).host, None)]
    except (socket.gaierror, UnicodeError) as e:
        raise HTTPException(502, f"Could not read {url}: {e}")
    if any(a.is_loopback or a.is_private or a.is_link_local or a.is_reserved or a.is_unspecified for a in addresses):
        raise HTTPException(400, "Only public docs sites can be read.")


def page_text(url: str) -> str:
    """The readable text of a docs page: scripts, styles and tags stripped, whitespace collapsed, capped."""
    check_public(url)
    try:
        with httpx.stream("GET", url, timeout=15, follow_redirects=True) as r:
            check_public(str(r.url))  # a redirect may land on an internal host
            r.raise_for_status()
            raw = b"".join(itertools.islice(r.iter_bytes(65536), 16))  # the first 1 MB
            html = raw.decode(r.encoding or "utf-8", errors="replace")
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Could not read {url}: {e}")
    return " ".join(TAGS.sub(" ", SCRIPTS.sub(" ", html)).split())[:12_000]


@router.get("")
def list_suggestions() -> list[dict]:
    return [row(s) for s in db.suggestions().find().sort("created_at", -1)]


@router.post("")
def suggest(body: SuggestRequest, user: dict = Depends(current_user)) -> list[dict]:
    docs = "\n\n".join([*(page_text(url) for url in body.docs_urls), body.text]).strip()
    catalog = [f"{c.name}: {c.intent}" for c in store.list_cases()]
    gaps = [f"{g['path']}: {g['control']['kind']} control \"{g['control']['label']}\", no case exercises it"
            for g in get_map()["gaps"]] if body.use_map else []
    try:
        drafts = suggester.suggest(docs, catalog, gaps, body.count)
    except RuntimeError as e:  # the Anthropic key is not set
        raise HTTPException(409, str(e))
    except anthropic.APIError as e:
        raise HTTPException(502, str(e))
    source = "both" if docs and gaps else "docs" if docs else "map"
    saved = [{"_id": secrets.token_hex(6), "name": d.name if re.match(NAME, d.name) else store.derive_name(d.intent),
              "intent": d.intent, "why": d.why, "vars": {p.var: p.value for p in d.vars}, "source": source,
              "status": "open", "created_at": events.now(), "created_by": user["email"]} for d in drafts]
    if saved:
        db.suggestions().insert_many(saved)
    return [row(s) for s in saved]


@router.post("/{suggestion_id}/author")
def author(suggestion_id: SuggestionId, user: dict = Depends(current_user)) -> dict:
    suggestion = find(suggestion_id)
    try:
        request = cases.AuthorCase(intent=suggestion["intent"], name=suggestion["name"], vars=suggestion["vars"])
    except ValidationError as e:
        raise HTTPException(422, f"This suggestion cannot be authored as written: {e}")
    run_id = cases.author_case(request, user)["run_id"]
    db.suggestions().update_one({"_id": suggestion_id},
                                {"$set": {"status": "authored", "case": request.name, "run_id": run_id}})
    return {"run_id": run_id}


@router.post("/{suggestion_id}/dismiss", status_code=204)
def dismiss(suggestion_id: SuggestionId) -> None:
    """Dismiss an open suggestion, or reopen a dismissed one."""
    status = "open" if find(suggestion_id)["status"] == "dismissed" else "dismissed"
    db.suggestions().update_one({"_id": suggestion_id}, {"$set": {"status": status}})


@router.delete("/{suggestion_id}", status_code=204, dependencies=[Depends(admin_only)])
def delete(suggestion_id: SuggestionId) -> None:
    if db.suggestions().delete_one({"_id": suggestion_id}).deleted_count == 0:
        raise HTTPException(404, f"No suggestion {suggestion_id}.")
