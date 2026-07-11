"""FAST executor loop: drive the live app one step at a time via typed tools,
recording every executed action with a durable selector — plus the authoring
orchestration (planner → executor → optimizer → save)."""

import re
from typing import get_args

from rich.console import Console
from rich.markup import escape

from groundhog import config
from groundhog.browser.actions import Ctx, goto_app, on_picker, perform, recover_workspace, resolve_path
from groundhog.browser.session import Session
from groundhog.browser.snapshot import fingerprint, snapshot
from groundhog.browser.selectors import dedupe_ranked, embeds_value, is_weak
from groundhog.cases.schema import Action, Case, Step
from groundhog.cases.store import save
from groundhog.llm import client

console = Console()

_SEL = {"type": "string", "description": "resilient Playwright locator you saw in the snapshot"}
_FALLBACKS = {"type": "array", "items": {"type": "string"},
              "description": "up to 2 alternate locators of different shapes for the same element"}
_FRAME = {"type": "string",
          "description": "iframe selector from the snapshot's Frame blocks — required when the element lives inside an iframe"}
_DESC = {"type": "string", "description": "what this step does, one short sentence"}


def _tool(name, desc, props, required):
    return {"name": name, "description": desc,
            "input_schema": {"type": "object", "properties": props, "required": required}}


TOOLS = [
    _tool("goto", "Navigate to a path within the app.",
          {"path": {"type": "string", "description": "path like /:ws/templates"}, "description": _DESC},
          ["path", "description"]),
    _tool("click", "Click an element.",
          {"selector": _SEL, "fallback_selectors": _FALLBACKS, "frame": _FRAME, "description": _DESC},
          ["selector", "description"]),
    _tool("fill", "Fill a text input.",
          {"selector": _SEL, "value": {"type": "string"}, "fallback_selectors": _FALLBACKS, "frame": _FRAME, "description": _DESC},
          ["selector", "value", "description"]),
    _tool("fill_secret", "Fill a credential input by field name — the value never leaves the runner.",
          {"selector": _SEL, "field": {"type": "string", "enum": ["user", "pass"]}, "description": _DESC},
          ["selector", "field", "description"]),
    _tool("select", "Select an option from a native <select> by its label.",
          {"selector": _SEL, "value": {"type": "string"}, "fallback_selectors": _FALLBACKS, "frame": _FRAME, "description": _DESC},
          ["selector", "value", "description"]),
    _tool("press", "Press a key on an element (e.g. Enter).",
          {"selector": _SEL, "value": {"type": "string", "description": "key, e.g. Enter"}, "frame": _FRAME, "description": _DESC},
          ["selector", "value", "description"]),
    _tool("hover", "Hover an element to reveal controls that only appear on hover "
          "(row/card action buttons). Use when a control resolves but is reported not visible.",
          {"selector": _SEL, "fallback_selectors": _FALLBACKS, "frame": _FRAME, "description": _DESC},
          ["selector", "description"]),
    _tool("drag", "Drag one element onto another: a palette item onto the canvas, or a "
          "node's source handle onto another node's target handle to connect them.",
          {"selector": _SEL,
           "to_selector": {"type": "string", "description": "locator for the drop target you saw in the snapshot"},
           "fallback_selectors": _FALLBACKS, "frame": _FRAME, "description": _DESC},
          ["selector", "to_selector", "description"]),
    _tool("read_docs", "Fetch a product documentation page as plain text.",
          {"url": {"type": "string"}}, ["url"]),
    _tool("done", "Finish: the intent is accomplished and verified on the live page.",
          {"start_path": {"type": "string", "description": "where the saved test should begin, /:ws/ for workspace"},
           "assertions": {"type": "array", "items": {"type": "string"},
                          "description": "1-3 plain-English outcomes true on the final page"}},
          ["start_path", "assertions"]),
]


_STATE_MARK = "Current URL: "
_ELIDED = "[stale page state elided — the latest snapshot is the ground truth]"


def _page_state(page) -> str:
    return f"{_STATE_MARK}{page.url}\n\nAccessibility snapshot:\n{snapshot(page)}"


def _elide_stale_states(messages: list[dict], keep: int = 2) -> None:
    """Bound the loop's context on long flows: a page state is huge and stale one
    action later. Keep the newest `keep`, collapse the rest. The assistant's own
    tool calls stay — they are the compact, durable record of what is done."""
    holders = []
    for m in messages:
        if isinstance(m["content"], str) and _STATE_MARK in m["content"]:
            holders.append(m)
        elif isinstance(m["content"], list):
            holders += [b for b in m["content"]
                        if isinstance(b, dict) and b.get("type") == "tool_result"
                        and isinstance(b.get("content"), str) and _STATE_MARK in b["content"]]
    for h in holders[:-keep]:
        h["content"] = h["content"].split(_STATE_MARK)[0] + _ELIDED


def _templatize(obj, vars: dict[str, str] | None):
    """Reverse-substitute concrete var values back into {{var}} placeholders, so
    the saved case is parameterized even though the agent typed real values
    (validated name fields reject literal braces)."""
    if not vars:
        return obj
    if isinstance(obj, str):
        for k, v in vars.items():
            if len(v) >= 3:
                obj = obj.replace(v, "{{" + k + "}}")
        return obj
    if isinstance(obj, list):
        return [_templatize(x, vars) for x in obj]
    if isinstance(obj, dict):
        return {k: _templatize(x, vars) for k, x in obj.items()}
    return obj


def run_executor(page, ctx: Ctx, intent: str, plan_steps: list[str], notes: str = "",
                 max_actions: int = 0, trace: list[dict] | None = None) -> tuple[list[dict], dict | None]:
    """Drive the loop; returns (trace, done_payload). done_payload is None when
    the action budget ran out before the agent finished. The caller may supply
    the trace list so actions recorded before a mid-loop crash survive it."""
    system = client.prompt("executor", context="")
    trace = [] if trace is None else trace
    steps_text = "\n".join(f"{i}. {s}" for i, s in enumerate(plan_steps, 1))
    messages = [{"role": "user", "content":
                 f"Intent: {intent}\n\nDraft plan (context only — verify against the live page):\n{steps_text}\n"
                 + (f"\nPlanner notes: {notes}\n" if notes else "")
                 + f"\n{_page_state(page)}"}]

    nudges = 0
    # A run of failed guesses (the FAST model flailing against an unfamiliar page)
    # earns one turn on the SMART model; a single success drops back to FAST.
    consecutive_failures = 0
    failed: dict[tuple[str, str], int] = {}
    # The `failed` gate blocks a dead selector; this catches the opposite failure
    # — a lost agent cycling through the same screens with "successful" clicks.
    succeeded: dict[tuple[str, str], int] = {}
    for _ in range(max_actions or config.EXECUTOR_MAX_ACTIONS):
        _elide_stale_states(messages)
        escalate = consecutive_failures >= 3
        if escalate:
            console.print(f"  [dim]↑ {consecutive_failures} actions failed — escalating to {client.SMART}[/]")
        resp = client.message(messages, system=system, tools=TOOLS,
                              model=client.SMART if escalate else client.FAST)
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
            result = _execute(page, ctx, tu.name, dict(tu.input), trace, failed)
            consecutive_failures = 0 if result["ok"] else consecutive_failures + 1
            if result["ok"]:
                skey = (tu.name, dict(tu.input).get("selector") or "")
                succeeded[skey] = succeeded.get(skey, 0) + 1
                if succeeded[skey] >= 3:
                    result["text"] += (
                        "\n\nnote: this exact action has now succeeded 3 times this run — "
                        "if you are cycling through the same screens, step back: re-read the "
                        "goal, and consider that the content you need may be inside an iframe "
                        "(see Frame blocks in the snapshot) or behind a different control.")
            results.append({"type": "tool_result", "tool_use_id": tu.id,
                            "content": result["text"], "is_error": not result["ok"]})
        messages.append({"role": "user", "content": results})
        if done_payload is not None:
            return trace, done_payload
    return trace, None


def _execute(page, ctx: Ctx, action: str, inp: dict, trace: list[dict],
             failed: dict[tuple[str, str], int]) -> dict:
    if action == "read_docs":
        from groundhog.crawl.docs import read_docs_page

        return {"ok": True, "text": read_docs_page(inp.get("url", ""))}

    # A hallucinated tool name must bounce back into the loop as a tool error,
    # not crash the run — authoring is the expensive part of the product.
    if action not in get_args(Action):
        return {"ok": False, "text": f"error: unknown tool {action!r} — use only the provided tools"}

    # Deterministic gates before touching the browser — a bad selector otherwise
    # costs a full step timeout per attempt.
    key = (action, inp.get("selector") or "")
    weak = ("selector" if action != "goto" and is_weak(inp.get("selector"))
            else "to_selector" if action == "drag" and is_weak(inp.get("to_selector")) else None)
    if weak:
        return {"ok": False, "text": f"error: weak {weak} — purely structural CSS (bare tags, "
                                     "descendant chains, :nth pseudos, snapshot role names like "
                                     "'combobox' used as tags) cannot be durable. Use "
                                     'role=…[name="…"], [aria-label="…"], [placeholder="…"], #id, or text="…".'}
    if failed.get(key, 0) >= 2:
        return {"ok": False, "text": "error: this selector already failed twice — "
                                     "use a different selector shape or navigate by URL"}

    if on_picker(page):
        recover_workspace(page)
    # goto steps never carry a fingerprint into the saved case (the optimizer
    # only attaches them to selector steps), so skip the expensive snapshot.
    url_before = page.url
    fp_before = None if action == "goto" else fingerprint(snapshot(page))
    step = Step(
        id="", action=action,
        selector=inp.get("selector"),
        to_selector=inp.get("to_selector"),
        frame=inp.get("frame"),
        value=inp.get("path") if action == "goto" else inp.get("value"),
        field=inp.get("field"),
        description=inp.get("description", ""),
    )
    try:
        perform(page, step, ctx, fp_before=fp_before)
    except Exception as e:
        failed[key] = failed.get(key, 0) + 1
        # escape: selectors contain […] which Rich would swallow as markup tags.
        console.print(f"  [red]✗[/] {escape(f'{action} {step.selector or step.value} — {str(e).splitlines()[0]}')}")
        return {"ok": False, "text": f"error: {str(e).splitlines()[0]}\n\n{_page_state(page)}"}

    fallbacks = dedupe_ranked([s for s in inp.get("fallback_selectors", [])
                               if not embeds_value(s, step.value)])[:2]
    trace.append({
        "action": step.action, "selector": step.selector, "fallback_selectors": fallbacks,
        "to_selector": step.to_selector, "frame": step.frame,
        "value": None if action == "fill_secret" else step.value,
        "field": step.field, "description": step.description,
        "url_before": url_before, "url_after": page.url,
        "fingerprint_before": fp_before,
    })
    console.print(f"  [green]·[/] {escape(step.description)}")
    return {"ok": True, "text": f"ok\n\n{_page_state(page)}"}


def _dump_partial(name: str, trace: list[dict]) -> str:
    """Executor work is the expensive part of authoring; when it dies partway,
    park the recorded actions in runs/ so they can be inspected or salvaged
    instead of re-paid."""
    import json
    from datetime import datetime, timezone

    config.RUNS_DIR.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = config.RUNS_DIR / f"{name}-partial-{ts}.json"
    path.write_text(json.dumps(trace, indent=2) + "\n")
    return str(path)


def _derive_name(intent: str) -> str:
    words = re.findall(r"[a-z0-9]+", intent.lower())
    return "-".join(words[:5]) or "case"


def _drive(session: Session, draft, live_intent: str, name: str) -> tuple[list[dict], dict]:
    """Run the executor against a logged-in session; returns (trace, done)."""
    ctx = Ctx(ws=session.ws)
    page = session.page
    goto_app(page, resolve_path(draft.start_path, ctx))
    # Long flows: scale the runaway guard with plan size — ~5 live actions per
    # sub-goal absorbs retries and verification without letting a lost agent spin.
    budget = max(config.EXECUTOR_MAX_ACTIONS, 5 * len(draft.steps))
    trace: list[dict] = []
    try:
        trace, done = run_executor(page, ctx, live_intent, draft.steps, draft.notes,
                                   max_actions=budget, trace=trace)
    except Exception:
        if trace:
            console.print(f"[yellow]partial trace saved: {_dump_partial(name, trace)}[/]")
        raise
    if not trace:
        raise RuntimeError("executor recorded no successful actions — nothing to save")
    if done is None:
        raise RuntimeError(f"executor hit the {budget}-action budget before finishing — "
                           f"partial trace: {_dump_partial(name, trace)}")
    return trace, done


def _verify_vars(vars: dict[str, str] | None, stamp: int) -> dict[str, str]:
    """Fresh-suffix each supplied var value so a verification replay exercises the
    same steps against new data — replaying a create-style case with the values
    authoring just used would collide with them (duplicate-name rejection)."""
    return {k: f"{v}-v{stamp}" for k, v in (vars or {}).items()}


def verify_case(case: Case, vars: dict[str, str] | None = None, headless: bool = True):
    """Prove a freshly authored case actually replays: one static run (no healer)
    against fresh data. Returns the RunResult; never touches the saved case."""
    from datetime import datetime, timezone

    from groundhog.runner.replay import run_case

    fresh = _verify_vars(vars, int(datetime.now(timezone.utc).timestamp()))
    console.print(f"[cyan]verify[/] replaying {case.name} once against fresh data"
                  + (f" ({', '.join(fresh.values())})" if fresh else ""))
    with Session(headless=headless) as session:
        session.ensure_logged_in()
        result = run_case(case, session, vars=fresh, heal=False)
    if fresh:
        console.print("[yellow]note[/] verification created extra data "
                      f"({', '.join(fresh.values())}) — this repo pairs creates with deletes "
                      "at the flow level, not per case, so you may want to clean it up.")
    return result


def author_case(intent: str, name: str | None = None, headless: bool = True,
                vars: dict[str, str] | None = None, session: Session | None = None) -> Case:
    """Author one case agentically. Pass `session` to reuse a live logged-in
    session (flow composing); otherwise one is opened for this case."""
    from datetime import datetime, timezone

    from groundhog.agent.planner import plan as make_plan
    from groundhog.agent.optimizer import optimize
    from groundhog.cases.store import render

    name = name or _derive_name(intent)
    # The agent works with concrete values (validated fields reject literal
    # braces); the saved case is re-parameterized from `vars` afterwards.
    live_intent = render(intent, vars)
    draft, used_graph = make_plan(live_intent)
    console.print(f"[cyan]plan[/] start at {draft.start_path}"
                  f" ({'graph-informed' if used_graph else 'graphless'}):")
    for s in draft.steps:
        console.print(f"  - {s}")

    if session is not None:
        trace, done = _drive(session, draft, live_intent, name)
    else:
        with Session(headless=headless) as owned:
            owned.ensure_logged_in()
            trace, done = _drive(owned, draft, live_intent, name)

    trace, done = _templatize(trace, vars), _templatize(done, vars)
    case = optimize(name, intent, trace, done)
    case.meta.created_at = datetime.now(timezone.utc).isoformat()
    save(case)

    try:
        from groundhog.graph.ingest import ingest_trace

        ingest_trace(case, trace)
    except Exception:
        pass  # the graph accelerates authoring; it is never a prerequisite
    return case
