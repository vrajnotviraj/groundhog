"""Trace → graph. Every agent run teaches the graph; everything goes through
store.py upserts."""

from groundhog.browser.selectors import is_weak
from groundhog.cases.schema import Case
from groundhog.graph import store


def ingest_trace(case: Case, trace: list[dict]) -> None:
    """Executor trace: every executed action is a verified element, every URL
    change a verified transition; the case is linked to its coverage."""
    pages, elements = set(), set()
    for t in trace:
        frm = store.page_key(t["url_before"])
        to = store.page_key(t["url_after"])
        pages.update([frm, to])
        store.upsert_page(frm)
        if t.get("selector"):
            kind = _kind(t)
            store.upsert_element(frm, t["selector"], kind=kind,
                                 description=t.get("description", ""))
            elements.add(store.element_key(frm, t["selector"]))
            if to != frm:
                store.upsert_transition(frm, t["selector"], t["action"], to)
        elif to != frm:
            store.upsert_page(to)

    store.upsert_case(case.name, case.intent)
    store.link_case(case.name, sorted(pages), sorted(elements))


def ingest_run(case: Case, passed: bool) -> None:
    """A replay outcome refreshes the case node (heals are ingested where they
    happen, with the live page URL in hand)."""
    store.upsert_case(case.name, case.intent, status="passed" if passed else "failed")


def ingest_crawl(url: str, title: str, elements: list, transitions: list[tuple[str, str, str]]) -> None:
    """One crawled page: its elements and the nav transitions discovered.
    elements: ObservedElement-likes; transitions: (selector, action, to_url)."""
    key = store.page_key(url)
    store.upsert_page(key, title=title)
    # The observe model sometimes invents pseudo-tag CSS — a weak selector in
    # the graph poisons every plan that reuses it, so gate the single write path.
    for e in elements:
        if is_weak(e.selector):
            continue
        store.upsert_element(key, e.selector, role=e.role, name=e.name,
                             kind=e.kind, description=e.description)
    for selector, action, to_url in transitions:
        if not is_weak(selector):
            store.upsert_transition(key, selector, action, store.page_key(to_url))


def _kind(t: dict) -> str:
    desc = (t.get("description", "") + " " + (t.get("selector") or "")).lower()
    if any(w in desc for w in ("delete", "remove", "revoke")):
        return "destructive"
    if t["action"] in ("fill", "select", "press", "fill_secret") or \
       any(w in desc for w in ("create", "submit", "save", "edit", "update")):
        return "mutation"
    return "nav"
