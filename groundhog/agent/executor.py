"""FAST executor loop: drive the live app one step at a time via typed tools,
recording every executed action with a durable selector — plus the authoring
orchestration (planner → executor → optimizer → save)."""

import re

from rich.console import Console

from groundhog import config
from groundhog.browser.actions import Ctx, perform
from groundhog.browser.session import Session
from groundhog.browser.snapshot import fingerprint, snapshot
from groundhog.browser.selectors import dedupe_ranked, embeds_value
from groundhog.cases.schema import Case, Step
from groundhog.cases.store import save
from groundhog.llm import client

console = Console()

_SEL = {"type": "string", "description": "resilient Playwright locator you saw in the snapshot"}
_FALLBACKS = {"type": "array", "items": {"type": "string"},
              "description": "up to 2 alternate locators of different shapes for the same element"}
_DESC = {"type": "string", "description": "what this step does, one short sentence"}


def _tool(name, desc, props, required):
    return {"name": name, "description": desc,
            "input_schema": {"type": "object", "properties": props, "required": required}}


TOOLS = [
    _tool("goto", "Navigate to a path within the app.",
          {"path": {"type": "string", "description": "path like /:ws/templates"}, "description": _DESC},
          ["path", "description"]),
    _tool("click", "Click an element.",
          {"selector": _SEL, "fallback_selectors": _FALLBACKS, "description": _DESC},
          ["selector", "description"]),
    _tool("fill", "Fill a text input.",
          {"selector": _SEL, "value": {"type": "string"}, "fallback_selectors": _FALLBACKS, "description": _DESC},
          ["selector", "value", "description"]),
    _tool("fill_secret", "Fill a credential input by field name — the value never leaves the runner.",
          {"selector": _SEL, "field": {"type": "string", "enum": ["user", "pass"]}, "description": _DESC},
          ["selector", "field", "description"]),
    _tool("select", "Select an option from a native <select> by its label.",
          {"selector": _SEL, "value": {"type": "string"}, "fallback_selectors": _FALLBACKS, "description": _DESC},
          ["selector", "value", "description"]),
    _tool("press", "Press a key on an element (e.g. Enter).",
          {"selector": _SEL, "value": {"type": "string", "description": "key, e.g. Enter"}, "description": _DESC},
          ["selector", "value", "description"]),
    _tool("read_docs", "Fetch a product documentation page as plain text.",
          {"url": {"type": "string"}}, ["url"]),
    _tool("done", "Finish: the intent is accomplished and verified on the live page.",
          {"start_path": {"type": "string", "description": "where the saved test should begin, /:ws/ for workspace"},
           "assertions": {"type": "array", "items": {"type": "string"},
                          "description": "1-3 plain-English outcomes true on the final page"}},
          ["start_path", "assertions"]),
]


def _read_docs(url: str) -> str:
    import httpx

    if not url.startswith(config.DOCS_URL):
        return f"error: only {config.DOCS_URL} pages can be read"
    text = httpx.get(url, follow_redirects=True, timeout=15).text
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text)[:4000]


def _page_state(page) -> str:
    return f"Current URL: {page.url}\n\nAccessibility snapshot:\n{snapshot(page)}"


def run_executor(page, ctx: Ctx, intent: str, plan_steps: list[str], notes: str = "") -> tuple[list[dict], dict | None]:
    """Drive the loop; returns (trace, done_payload). done_payload is None when
    the action budget ran out before the agent finished."""
    system = client.prompt("executor", context="")
    trace: list[dict] = []
    steps_text = "\n".join(f"{i}. {s}" for i, s in enumerate(plan_steps, 1))
    messages = [{"role": "user", "content":
                 f"Intent: {intent}\n\nDraft plan (context only — verify against the live page):\n{steps_text}\n"
                 + (f"\nPlanner notes: {notes}\n" if notes else "")
                 + f"\n{_page_state(page)}"}]

    nudges = 0
    for _ in range(config.EXECUTOR_MAX_ACTIONS):
        resp = client.message(messages, system=system, tools=TOOLS)
        tool_uses = [b for b in resp.content if b.type == "tool_use"]
        if not tool_uses:
            if nudges >= 2:
                break
            nudges += 1
            messages.append({"role": "assistant", "content": resp.content})
            messages.append({"role": "user", "content": "Continue with a tool call, or call done."})
            continue

        messages.append({"role": "assistant", "content": resp.content})
        results = []
        done_payload = None
        for tu in tool_uses:
            if tu.name == "done":
                done_payload = dict(tu.input)
                results.append({"type": "tool_result", "tool_use_id": tu.id, "content": "recorded"})
                continue
            result = _execute(page, ctx, tu.name, dict(tu.input), trace)
            results.append({"type": "tool_result", "tool_use_id": tu.id,
                            "content": result["text"], "is_error": not result["ok"]})
        messages.append({"role": "user", "content": results})
        if done_payload is not None:
            return trace, done_payload
    return trace, None


def _execute(page, ctx: Ctx, action: str, inp: dict, trace: list[dict]) -> dict:
    if action == "read_docs":
        return {"ok": True, "text": _read_docs(inp.get("url", ""))}

    url_before, fp_before = page.url, fingerprint(snapshot(page))
    step = Step(
        id="", action="goto" if action == "goto" else action,
        selector=inp.get("selector"),
        value=inp.get("path") if action == "goto" else inp.get("value"),
        field=inp.get("field"),
        description=inp.get("description", ""),
    )
    try:
        perform(page, step, ctx)
    except Exception as e:
        console.print(f"  [red]✗[/] {action} {step.selector or step.value} — {str(e).splitlines()[0]}")
        return {"ok": False, "text": f"error: {str(e).splitlines()[0]}\n\n{_page_state(page)}"}

    fallbacks = dedupe_ranked([s for s in inp.get("fallback_selectors", [])
                               if not embeds_value(s, step.value)])[:2]
    trace.append({
        "action": step.action, "selector": step.selector, "fallback_selectors": fallbacks,
        "value": None if action == "fill_secret" else step.value,
        "field": step.field, "description": step.description,
        "url_before": url_before, "url_after": page.url,
        "fingerprint_before": fp_before,
    })
    console.print(f"  [green]·[/] {step.description}")
    return {"ok": True, "text": f"ok\n\n{_page_state(page)}"}


def _derive_name(intent: str) -> str:
    words = re.findall(r"[a-z0-9]+", intent.lower())
    return "-".join(words[:5]) or "case"


def author_case(intent: str, name: str | None = None, headless: bool = True) -> Case:
    from datetime import datetime, timezone

    from groundhog.agent.planner import plan as make_plan
    from groundhog.agent.optimizer import optimize

    name = name or _derive_name(intent)
    draft, used_graph = make_plan(intent)
    console.print(f"[cyan]plan[/] start at {draft.start_path}"
                  f" ({'graph-informed' if used_graph else 'graphless'}):")
    for s in draft.steps:
        console.print(f"  - {s}")

    with Session(headless=headless) as session:
        session.ensure_logged_in()
        ctx = Ctx(ws=session.ws)
        page = session.page
        page.goto(f"{config.BASE_URL}{draft.start_path.replace('/:ws', '/' + ctx.ws if ctx.ws else '')}")
        trace, done = run_executor(page, ctx, intent, draft.steps, draft.notes)
        if not trace:
            raise RuntimeError("executor recorded no successful actions — nothing to save")
        if done is None:
            raise RuntimeError(f"executor hit the {config.EXECUTOR_MAX_ACTIONS}-action budget before finishing")

    case = optimize(name, intent, trace, done)
    case.meta.created_at = datetime.now(timezone.utc).isoformat()
    save(case)

    try:
        from groundhog.graph.ingest import ingest_trace

        ingest_trace(case, trace)
    except Exception:
        pass  # the graph accelerates authoring; it is never a prerequisite
    return case
