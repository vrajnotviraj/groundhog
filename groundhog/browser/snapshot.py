"""The element table: what Jev sees, and the durable selectors code derives from what it picks.

snapshot.js does the DOM read (one evaluate per document) and owns node identity.
Python numbers the elements, merges child frames, and turns a picked node into
ranked selectors that are each verified to resolve back to that same node.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from groundhog.config import ws_path

JS = (Path(__file__).parent / "snapshot.js").read_text()
SAME_NODE = "(e, n) => window.__gh.nodes.get(n) === e"

MAX_ELEMENTS = 240  # a Choice holds 255 options and the head adds "none"
MAX_FRAMES = 3


@dataclass
class Element:
    id: str  # "e12" top document, "f1e12" inside child frame 1; the Choice option key
    role: str
    label: str
    value: str
    kind: str  # "click" | "fill"
    attrs: dict
    state: dict
    scope: dict | None
    frame: str | None  # Playwright frame selector, or None for the top document
    node: int  # code-owned node id inside its document


@dataclass
class Snapshot:
    url: str
    title: str
    text: str
    elements: list[Element]
    omitted: int
    fingerprint: str


def observe(page) -> Snapshot:
    """Every rendered element in the page and its frames, offered whether or not it is
    scrolled into view: Playwright locators scroll to their target themselves."""
    top = page.evaluate(JS) or {}
    elements = _elements(top, None, "e")
    omitted = top.get("omitted", 0)

    n = 0
    for f in page.frames[1:]:
        if n >= MAX_FRAMES:
            break
        try:
            if f.parent_frame != page.main_frame:
                continue
            fe = f.frame_element()
            box = fe.bounding_box()
            if not box or box["width"] <= 0 or box["height"] <= 0:
                continue
            sel = _frame_selector(fe)
            data = f.evaluate(JS) or {}
            n += 1
            elements += _elements(data, sel, f"f{n}e")
            omitted += data.get("omitted", 0)
        except Exception:
            continue  # a frame is a bonus; snapshot never fails because of one

    if len(elements) > MAX_ELEMENTS:
        omitted += len(elements) - MAX_ELEMENTS
        elements = elements[:MAX_ELEMENTS]

    url, text = top.get("url") or page.url, top.get("text", "")
    return Snapshot(url=url, title=top.get("title", ""), text=text, elements=elements, omitted=omitted,
                    fingerprint=_fingerprint(url, text, elements))


def _elements(data, frame, prefix) -> list[Element]:
    return [Element(id=f"{prefix}{i + 1}", frame=frame, **d) for i, d in enumerate(data.get("elements", []))]


def _frame_selector(fe) -> str:
    for attr, tpl in (("name", "iframe[name={}]"), ("title", "iframe[title={}]")):
        v = fe.get_attribute(attr)
        if v:
            return tpl.format(_q(v))
    v = fe.get_attribute("id")
    if v:
        return f"#{v}"
    k = fe.evaluate('e => [...document.querySelectorAll("iframe")].indexOf(e)')
    return f"iframe >> nth={k}"


def _fingerprint(url: str, text: str, elements: list[Element]) -> str:
    """Drift gate. Digit runs are normalized out so live counts and dates aren't drift,
    but element state is in, so toggling a checkbox counts as a change, and so is the
    visible text, so a save that only writes a confirmation line is not a no-op."""
    rows = sorted("|".join([e.role, e.label, e.state.get("checked", ""),
                            e.state.get("expanded", ""), e.state.get("selected", "")]) for e in elements)
    stable = re.sub(r"\d+", "#", "\n".join([ws_path(url), text or "", *rows]))
    return "sha256:" + hashlib.sha256(stable.encode()).hexdigest()[:16]


# --- selectors -------------------------------------------------------------

DIGIT_RUN = re.compile(r"\d{2,}")
UNSTABLE_ID = ("rc_", ":r", "radix-", "mui-", "headlessui-", "react-select")


def _q(v: str) -> str:
    return json.dumps(v)


def _href_frag(href: str) -> str:
    """A link path without the per-install workspace segment, so it can be saved."""
    return ws_path(href).removeprefix("/:ws")


def _scope_prefix(scope: dict | None) -> str | None:
    if not scope:
        return None
    kind = scope.get("kind")
    if kind == "dialog":
        return "role=dialog"
    if kind == "link":
        return f"a[href*={_q(_href_frag(scope.get('href') or ''))}]"
    if kind == "region":
        return f"role=region[name={_q(scope.get('name') or '')}]"
    if kind == "row":
        return f"{scope.get('tag', 'tr')}:has-text({_q(scope.get('text') or '')})"
    return None


def _candidates(el: Element, hints) -> list[str]:
    a, out = el.attrs, []
    if a.get("testid"):
        out.append(f"[data-testid={_q(a['testid'])}]")
    eid = a.get("id")
    if eid and not DIGIT_RUN.search(eid) and not eid.startswith(UNSTABLE_ID):
        out.append(f"#{eid}")
    if a.get("aria_label"):
        out.append(f"[aria-label={_q(a['aria_label'])}]")
    for h in hints:
        # Option labels carry suffixes ("gh-1 Has test version"); a hint pins the entity.
        if h and len(el.label) > len(h) and h in el.label:
            out.append(f"role={el.role}[name*={_q(h)}]")
    if el.label:
        out.append(f"role={el.role}[name={_q(el.label)}]")
    if a.get("placeholder"):
        out.append(f"[placeholder={_q(a['placeholder'])}]")
    if a.get("name"):
        out.append(f"[name={_q(a['name'])}]")
    if a.get("href"):
        out.append(f"a[href*={_q(_href_frag(a['href']))}]")
    if a.get("tag") == "label" and el.label:
        out.append(f"label:has(:text-is({_q(el.label)}))")
    return out


def _root(page, el: Element):
    return page.frame_locator(el.frame) if el.frame else page


def _unique(page, el: Element, sel: str) -> bool:
    try:
        loc = _root(page, el).locator(sel)
        return loc.count() == 1 and bool(loc.first.evaluate(SAME_NODE, el.node))
    except Exception:
        return False


def _nth(page, el: Element, base: str) -> int | None:
    try:
        for k, loc in enumerate(_root(page, el).locator(base).all()):
            if loc.evaluate(SAME_NODE, el.node):
                return k
    except Exception:
        pass
    return None


def selectors_for(page, el: Element, hints: list[str] = ()) -> list[str]:
    """Ranked durable selectors for el's node, best first, each verified unique.
    Raises when nothing verifies, so a dead selector is never saved."""
    good, ambiguous = [], []
    for sel in _candidates(el, hints):
        (good if _unique(page, el, sel) else ambiguous).append(sel)
        if len(good) >= 3:
            return good[:3]

    prefix = _scope_prefix(el.scope)
    if prefix:
        for sel in ambiguous:
            scoped = f"{prefix} >> {sel}"
            if _unique(page, el, scoped):
                good.append(scoped)
                if len(good) >= 3:
                    return good[:3]

    if good:
        return good[:3]

    # Nothing named the node uniquely (icon-only buttons, truncated labels, repeated
    # rows): index it in live DOM order, narrowing with the strongest base that still
    # matches it. A name Playwright does not reproduce matches nothing, hence the walk.
    aria = el.attrs.get("aria_label")
    bases = [f"[aria-label={_q(aria)}]"] if aria else []
    if el.label:
        bases.append(f"role={el.role}[name={_q(el.label)}]")
    bases += [f"role={el.role}", el.attrs.get("tag", "")]
    for base in bases:
        k = _nth(page, el, base) if base else None
        if k is not None and _unique(page, el, f"{base} >> nth={k}"):
            return [f"{base} >> nth={k}"]
    raise RuntimeError(f"no verifiable selector for [{el.role} {el.label}]")
