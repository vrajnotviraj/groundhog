"""Walk the app's pages under one scope by following links, and store what each page holds.

The crawl only navigates: it never clicks, types or submits, and it makes no AI calls.
"""

import re
from collections import deque
from urllib.parse import urljoin, urlsplit

from groundhog import config, db, events
from groundhog.browser.actions import Ctx, goto_app, resolve_path
from groundhog.browser.session import Session
from groundhog.browser.snapshot import Element, observe

CONTROL_ROLES = {"button", "link", "menuitem", "tab", "switch", "checkbox", "combobox"}
DESTRUCTIVE = re.compile(r"\b(delete|remove|discard)\b", re.I)
MUTATION = re.compile(r"\b(add|create|new|save|submit|update|publish|send|invite|import)\b", re.I)
SIGN_OUT = re.compile(r"logout|signout|sign-out", re.I)


def crawl(scope: str, max_pages: int, headless: bool, run_id: str | None = None) -> dict:
    """Log in and store every page reachable by links from the scope's root; return the page and control counts."""
    prefix = "/:ws" + scope
    root = "/:ws/home" if scope == "/" else prefix
    with Session(headless=headless) as session:
        session.ensure_logged_in()
        return walk(session, root, prefix, max_pages, run_id)


def walk(session, root: str, prefix: str, max_pages: int, run_id: str | None) -> dict:
    """Visit pages breadth first from the root, at most CRAWL_MAX_DEPTH links away and max_pages in all."""
    queue, seen = deque([(root, 0)]), {root}
    counts = {"pages": 0, "controls": 0}
    while queue and counts["pages"] < max_pages:
        key, depth = queue.popleft()
        try:
            page = visit(session, key, depth, prefix, run_id)
        except Exception as e:  # one page that will not load must not end the crawl
            events.emit("note", level="warn", text=f"skipped {key}: {str(e).splitlines()[0]}")
            continue
        counts["pages"] += 1
        counts["controls"] += len(page["controls"])
        if depth < config.CRAWL_MAX_DEPTH:
            fresh = [link for link in page["links"] if link not in seen]
            seen.update(fresh)
            queue.extend((link, depth + 1) for link in fresh)
    return counts


def visit(session, key: str, depth: int, prefix: str, run_id: str | None) -> dict:
    """Open one page, store its document, record it on the run and return the document."""
    goto_app(session.page, resolve_path(key, Ctx(ws=session.ws)))
    snap = observe(session.page)
    page = {"title": snap.title, "section": section(key), "links": links(snap.elements, prefix, snap.url),
            "controls": controls(snap.elements), "last_seen": events.now(), "run_id": run_id}
    db.pages().replace_one({"_id": key}, page, upsert=True)
    events.emit("page", path=key, title=snap.title, controls=len(page["controls"]), links=len(page["links"]),
                depth=depth)
    events.shot(session.page)
    return page


def section(key: str) -> str:
    """The first path segment after the workspace: /:ws/templates/x/edit is in templates, /:ws is home."""
    return key.removeprefix("/:ws").strip("/").split("/")[0] or "home"


def controls(elements: list[Element]) -> list[dict]:
    """Each distinct control on the page with the kind its label suggests."""
    found = {(e.role, e.label): {"role": e.role, "label": e.label, "kind": control_kind(e.role, e.label)}
             for e in elements if e.role in CONTROL_ROLES}
    return list(found.values())


def control_kind(role: str, label: str) -> str:
    if role == "link":
        return "nav"
    if DESTRUCTIVE.search(label):
        return "destructive"
    if MUTATION.search(label):
        return "mutation"
    return "other"


def links(elements: list[Element], prefix: str, page_url: str) -> list[str]:
    """Page keys of the same-origin links that stay inside the scope, sign-out links left out."""
    host = urlsplit(config.BASE_URL).netloc
    keys = []
    for e in elements:
        if not e.attrs.get("href"):
            continue
        href = urljoin(page_url, e.attrs["href"])
        key = config.ws_path(href)
        if urlsplit(href).netloc in ("", host) and key.startswith(prefix) and not SIGN_OUT.search(href):
            keys.append(key)
    return list(dict.fromkeys(keys))
