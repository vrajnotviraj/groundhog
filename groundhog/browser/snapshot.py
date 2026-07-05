"""Pruned accessibility snapshots — the agent's eyes, and the replay drift gate.

An ariaSnapshot is already far smaller than raw HTML, but pages with long
repetitive lists (157 template cards, 200 log rows) blow the prompt up with
near-identical siblings that add tokens, not signal. We collapse any run of
same-role siblings beyond max_repeat into an "(N more …)" marker and cap total
lines — keeping structure and navigation while cutting repetition.
"""

import hashlib
import re

INDENT = re.compile(r"^ *")
ROLE = re.compile(r"^-\s+([a-zA-Z]+)")


def _indent(line: str) -> int:
    return INDENT.match(line).end()


def _role(line: str) -> str | None:
    m = ROLE.match(line.strip())
    return m.group(1) if m else None


def prune_tree(text: str, max_repeat: int = 6, max_lines: int = 250) -> str:
    lines = (text or "").split("\n")
    out: list[str] = []
    i = 0

    def block_end(start: int, indent: int) -> int:
        k = start + 1
        while k < len(lines) and (not lines[k].strip() or _indent(lines[k]) > indent):
            k += 1
        return k

    while i < len(lines):
        indent, role = _indent(lines[i]), _role(lines[i])

        # Gather consecutive sibling blocks at this indent sharing the same role.
        siblings = []
        p = i
        while role and p < len(lines) and _indent(lines[p]) == indent and _role(lines[p]) == role:
            end = block_end(p, indent)
            siblings.append((p, end))
            p = end

        if role and len(siblings) > max_repeat:
            for s, e in siblings[:max_repeat]:
                out.extend(lines[s:e])
            out.append(f"{' ' * indent}- … ({len(siblings) - max_repeat} more {role})")
            i = siblings[-1][1]
        else:
            out.append(lines[i])
            i += 1

    if len(out) > max_lines:
        return "\n".join([*out[:max_lines], f"… ({len(out) - max_lines} more lines truncated)"])
    return "\n".join(out)


# ReactFlow canvases render nodes/edges mostly outside the aria tree, so the
# executor and judge would otherwise be blind to them. One evaluate lists what
# exists, keyed the way selectors will address it (data-id, visible label).
CANVAS_JS = """() => ({
  nodes: [...document.querySelectorAll('.react-flow__node')].slice(0, 40).map(n => ({
    id: n.getAttribute('data-id') || '',
    label: (n.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 60),
    handles: [...n.querySelectorAll('.react-flow__handle')].map(h =>
      h.classList.contains('source') ? 'source'
      : h.classList.contains('target') ? 'target' : 'handle'),
  })),
  edges: [...document.querySelectorAll('.react-flow__edge')].map(e =>
    e.getAttribute('aria-label') || ''),
})"""


def format_canvas(data) -> str:
    """Render the CANVAS_JS payload as a text block — pure, so it unit-tests
    without a browser. Empty or malformed data renders ""."""
    try:
        lines = []
        for n in data.get("nodes", []):
            handles = ", ".join(n.get("handles", []))
            lines.append(f'- node data-id="{n.get("id", "")}" "{n.get("label", "")}"'
                         + (f" handles: {handles}" if handles else ""))
        lines.extend(f'- edge "{e}"' for e in data.get("edges", []) if e)
        return "Canvas (ReactFlow):\n" + "\n".join(lines) if lines else ""
    except Exception:
        return ""


def _canvas_supplement(page) -> str:
    """The supplement is an accelerator, never a way to break a snapshot — any
    failure returns ""."""
    try:
        if page.locator(".react-flow__node").count() == 0:
            return ""
        block = format_canvas(page.evaluate(CANVAS_JS))
        return f"\n\n{block}" if block else ""
    except Exception:
        return ""


def snapshot(page, prune: bool = True) -> str:
    tree = page.locator("body").aria_snapshot()
    return (prune_tree(tree) if prune else tree) + _canvas_supplement(page)


def fingerprint(pruned_tree: str) -> str:
    """Drift-gate hash. Digit runs are normalized out so live counts, dates and
    metrics don't make every run look like drift."""
    stable = re.sub(r"\d+", "#", pruned_tree)
    return "sha256:" + hashlib.sha256(stable.encode()).hexdigest()[:16]
