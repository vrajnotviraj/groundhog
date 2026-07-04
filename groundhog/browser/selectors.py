"""Durable-selector rules — the single quality bar every persisted selector passes.

Rank: data-testid → #id → [aria-label] → role=X[name="Y"] → [placeholder] → text="…".
A bare-tag selector (div/button/input) matches many elements, so .first() can
silently act on the wrong one — those are rejected outright.
"""

import re

# A durable selector needs an anchor: an attribute ([…]), an id (#), an engine
# (role=/text=), or quoted text. Purely structural CSS — bare tags, descendant
# chains, :nth pseudos — has none, and matches nothing or the wrong thing.
ANCHOR = re.compile(r"[\[#=\"']")

# ARIA role names masquerading as CSS tags (combobox[name*=…], textbox[…]):
# they parse as selectors for elements that don't exist and never match.
ROLE_TAG = re.compile(r"^(combobox|textbox|checkbox|radio|listbox|option|dialog"
                      r"|listitem|menuitem|switch|slider|tab|treeitem)\b")

# One locator engine per selector, ranked by durability.
RANK = [
    re.compile(r"^\[data-testid="),
    re.compile(r"^#[\w-]+$"),
    re.compile(r"^\[aria-label="),
    re.compile(r"^role=\w+\[name="),
    re.compile(r"^\[placeholder="),
    re.compile(r'^text="'),
]


def is_weak(selector: str | None) -> bool:
    s = (selector or "").strip()
    return not s or not ANCHOR.search(s) or bool(ROLE_TAG.match(s))


def rank(selector: str) -> int:
    """Lower is more durable; unranked shapes sort last."""
    for i, pat in enumerate(RANK):
        if pat.match(selector.strip()):
            return i
    return len(RANK)


def clean_label(text: str | None) -> str:
    """A short, single-line label with no long digit run (id-like data) — stable
    enough to key a text= selector on."""
    t = re.sub(r"\s+", " ", text or "").strip()
    return t if t and len(t) <= 40 and not re.search(r"\d{4,}", t) else ""


def embeds_value(selector: str, value: str | None) -> bool:
    """Overfitting guard: a selector must never embed the step's data value,
    or the case breaks the moment the test data changes. A {{var}} placeholder
    is not data — it renders per run — so it passes."""
    return (bool(value) and "{{" not in value
            and len(value) >= 3 and value.lower() in selector.lower())


def dedupe_ranked(selectors: list[str]) -> list[str]:
    """Ranked, deduped, weak-free candidate list (best first)."""
    seen, out = set(), []
    for s in sorted((s.strip() for s in selectors if s and not is_weak(s)), key=rank):
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out
