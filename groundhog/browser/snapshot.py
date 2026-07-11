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


# The top-document aria tree stops at the iframe boundary, so an editor rendered
# inside an iframe (Stripo, embedded WYSIWYG) is invisible to the agent. This
# lists visible iframes with the metadata a Playwright frame selector is derived
# from, so each frame's aria tree can be pulled and addressed.
FRAMES_JS = """() => [...document.querySelectorAll('iframe')].map((f, i) => {
  const r = f.getBoundingClientRect();
  const s = getComputedStyle(f);
  return {
    nth: i,
    name: f.getAttribute('name') || '',
    title: f.getAttribute('title') || '',
    id: f.id || '',
    width: r.width, height: r.height,
    hidden: s.visibility === 'hidden' || s.display === 'none' || f.hidden,
  };
})"""


def _frame_selector(meta) -> str:
    """A usable Playwright frame_locator selector for one iframe, preferring
    stable attributes and falling back to positional nth."""
    if meta.get("name"):
        return f'iframe[name="{meta["name"]}"]'
    if meta.get("title"):
        return f'iframe[title="{meta["title"]}"]'
    if meta.get("id"):
        return f'#{meta["id"]}'
    return f'iframe >> nth={meta.get("nth", 0)}'


def format_frames(frames) -> str:
    """Render per-iframe aria supplements as labeled text blocks — pure, so it
    unit-tests without a browser. `frames` is a list of {selector, tree} dicts
    (tree already pruned); empty or malformed data renders ""."""
    try:
        blocks = []
        for f in frames:
            tree = (f.get("tree") or "").strip()
            if tree:
                blocks.append(f"Frame {f.get('selector', '')}:\n{tree}")
        return "\n\n".join(blocks)
    except Exception:
        return ""


def _frames_supplement(page) -> str:
    """A bounded per-iframe aria supplement (cap 3 visible frames). Any failure
    — cross-origin restriction, detached frame, no evaluate — drops that frame;
    a snapshot must never throw."""
    try:
        metas = page.evaluate(FRAMES_JS)
    except Exception:
        return ""
    frames = []
    for meta in metas or []:
        try:
            if meta.get("hidden") or meta.get("width", 0) < 1 or meta.get("height", 0) < 1:
                continue
            sel = _frame_selector(meta)
            tree = page.frame_locator(sel).locator("body").aria_snapshot()
            frames.append({"selector": sel, "tree": prune_tree(tree, max_lines=80)})
        except Exception:
            continue
        if len(frames) >= 3:
            break
    block = format_frames(frames)
    return f"\n\n{block}" if block else ""


def snapshot(page, prune: bool = True) -> str:
    tree = page.locator("body").aria_snapshot()
    return ((prune_tree(tree) if prune else tree)
            + _canvas_supplement(page) + _frames_supplement(page))


def fingerprint(pruned_tree: str) -> str:
    """Drift-gate hash. Digit runs are normalized out so live counts, dates and
    metrics don't make every run look like drift."""
    stable = re.sub(r"\d+", "#", pruned_tree)
    return "sha256:" + hashlib.sha256(stable.encode()).hexdigest()[:16]
