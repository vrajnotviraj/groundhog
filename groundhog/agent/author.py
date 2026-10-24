"""Author one case: Jev picks the operation and the element, code derives the selector.

The loop runs the real app once. Every accepted action becomes a trace entry with a
verified durable selector; the trace becomes a Case that later replays with zero AI.
"""

import re
import time
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlsplit

from groundhog import config, events, jev
from groundhog.agent import text
from groundhog.browser.actions import Ctx, goto_app, on_picker, perform, recover_workspace, resolve_path, settle
from groundhog.browser.session import Session
from groundhog.browser.snapshot import observe, selectors_for
from groundhog.cases.schema import Assertion, Case, Expect, Step
from groundhog.cases.store import derive_name, render, save
from groundhog.config import ws_path

ACTIONS = {"CLICK": "click", "HOVER": "hover", "TYPE": "fill", "PRESS_ENTER": "press"}
SEPARATORS = (", then ", " then ", ", and ", " and ", ", ")
VERIFY = re.compile(r"^(verify|check|confirm|ensure|make sure)\b", re.I)
QUOTED = re.compile(r"'([^']+)'|\"([^\"]+)\"")
# A line that is only digits/punctuation, or a date, is live data rather than evidence.
DATEY = re.compile(r"^[\d\W]|^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*\d|\bago\b|just now", re.I)


def embeds_value(selector: str, value: str | None) -> bool:
    """True when the selector contains the step's literal data value (a {{var}} does not count)."""
    return (bool(value) and "{{" not in value
            and len(value) >= 3 and value.lower() in selector.lower())


def _templatize(obj, vars: dict[str, str] | None):
    """Replace concrete var values with {{var}} placeholders, in strings, lists and dicts."""
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


def _clauses(intent: str) -> list[str]:
    parts = [intent]
    for sep in SEPARATORS:
        parts = [p.strip() for c in parts for p in c.split(sep) if p.strip()]
    return parts


def outcome_clauses(intent: str) -> list[str]:
    """The verification clauses of an intent: the DONE gate and the saved jev assertions."""
    parts = _clauses(intent)
    return [c for c in parts if VERIFY.match(c)] or parts[-1:]


def _candidates(live_intent: str, vars: dict[str, str] | None) -> list[dict]:
    out, seen = [], set()
    for k, v in (vars or {}).items():
        if v and v not in seen:
            seen.add(v)
            out.append({"value": v, "source": "goal variable {{" + k + "}}"})
    for m in QUOTED.finditer(live_intent):
        lit = m.group(1) or m.group(2)
        if lit not in seen:
            seen.add(lit)
            out.append({"value": lit, "source": "quoted in the goal"})
    return out


def _changed_query(before: str, after: str) -> str | None:
    old = dict(parse_qsl(urlsplit(before).query))
    for k, v in parse_qsl(urlsplit(after).query):
        if old.get(k) != v:
            return f"{k}={v}"
    return None


def _new_line(before_text: str, after_text: str, typed: str | None) -> str | None:
    seen = before_text or ""
    for raw in (after_text or "").splitlines():
        line = raw.strip()
        if (3 <= len(line) <= 60 and line not in seen and line != (typed or "")
                and not DATEY.match(line)):
            return line
    return None


def derive_expects(before, after, step: Step) -> Expect | None:
    """A cheap post-condition for one step, read off the before/after pages."""
    if step.action == "fill" or before is None or after is None:
        return None
    b, a = ws_path(before.url), ws_path(after.url)
    if b != a:
        # Navigating up to a prefix ("/templates/x" -> "/templates") would assert
        # something the earlier page already satisfied, so fall through to text.
        if not b.startswith(a):
            return Expect(kind="url_contains", value=a.removeprefix("/:ws") or "/")
    else:
        q = _changed_query(before.url, after.url)
        if q:
            return Expect(kind="url_contains", value=q)
    line = _new_line(before.text, after.text, step.value)
    return Expect(kind="text_visible", value=line) if line else None


def _entry(op: str, action: str, value=None, page_changed=False, error=None) -> dict:
    return {"op": op, "action": action, "value": (value or None) and value[:120],
            "page_changed": page_changed, "error": error}


def _observe_changed(page, before, timeout_ms: int = 2000):
    """Post-action snapshot. Drawers and dialogs render after settle() returns, so
    give the page a bounded moment to actually change before calling it a no-op."""
    deadline = time.monotonic() + timeout_ms / 1000
    while True:
        after = observe(page)
        if after.fingerprint != before.fingerprint or after.url != before.url or time.monotonic() > deadline:
            return after
        page.wait_for_timeout(250)


def _emit_decision(d, detail: str | None = None) -> None:
    events.emit("decision", operation=d.operation, label=d.element.label if d.element else "",
                probability=d.probability, confidence=d.confidence, latency_ms=d.latency_ms,
                detail=detail or d.detail)


def run_executor(page, ctx: Ctx, goal: str, outcomes: list[str], candidates: list[dict],
                 max_actions: int, trace: list[dict] | None = None) -> tuple[list[dict], str]:
    """Drive the live app until the goal is verifiably done. Returns (trace, reason)
    where reason is done | blocked | budget. Pass `trace` to keep the recorded actions
    when the loop raises; the caller can then dump them."""
    trace = [] if trace is None else trace
    history: list[dict] = []
    hints = [v for v in (ctx.vars or {}).values() if v]
    exclude: set = set()
    failed: dict = {}
    failures = done_rejections = no_change = waits = 0
    last_fill: Step | None = None

    for _ in range(max_actions):
        if failures >= 3:
            return trace, "blocked"
        if on_picker(page):
            recover_workspace(page)
        snap = observe(page)
        try:
            d = jev.choose(snap, goal, history, exclude)
        except (RuntimeError, ValueError) as e:
            failures += 1
            history.append(_entry("NONE", "decision failed", error=str(e).splitlines()[0]))
            continue
        _emit_decision(d)

        if d.operation in ("DONE", "WAIT", "NONE", "BLOCKED"):
            # Code owns the finish line: whenever Jev is unsure, check the goal's
            # outcomes first. An app that already did the work must not be waited on.
            try:
                ps = [jev.judge(snap, o, goal) for o in outcomes]
                if ps and min(ps) < config.JUDGE_THRESHOLD and d.operation in ("DONE", "BLOCKED"):
                    # The last action's effect may still be landing (a delete, a save):
                    # one short wait and a second look before giving up on it.
                    page.wait_for_timeout(1500)
                    settle(page)
                    ps = [jev.judge(observe(page), o, goal) for o in outcomes]
            except (RuntimeError, ValueError) as e:
                failures += 1
                history.append(_entry("DONE", "DONE check failed", error=str(e).splitlines()[0]))
                continue
            if not ps or min(ps) >= config.JUDGE_THRESHOLD:
                return trace, "done"
            if d.operation == "DONE":
                worst = outcomes[ps.index(min(ps))]
                done_rejections += 1
                history.append(_entry("DONE", f"DONE rejected: '{worst}' not visibly true yet (p={min(ps):.2f})"))
                if done_rejections >= 2:
                    return trace, "blocked"
                continue
        if d.operation == "BLOCKED":
            return trace, "blocked"
        if d.operation == "NONE":
            # Jev wants to type but trusts no offered field. With exactly one empty
            # field in view there is nothing to judge: code takes it.
            empty = [el for el in snap.elements if el.kind == "fill" and not el.value
                     and el.state.get("disabled") != "true" and (el.frame, el.node) not in exclude]
            if d.wanted == "TYPE" and len(empty) == 1:
                d = jev.Decision("TYPE", empty[0], d.confidence, d.probability, d.latency_ms, d.detail)
                _emit_decision(d, "the only empty field")
            else:
                failures += 1
                history.append(_entry("NONE", "no fitting target"))
                continue
        if d.operation == "WAIT":
            settle(page)
            page.wait_for_timeout(1000)
            history.append(_entry("WAIT", "waited for the page to update"))
            if observe(page).fingerprint == snap.fingerprint:
                waits += 1
                if waits >= 3:  # nothing is loading; waiting longer only burns the budget
                    return trace, "blocked"
            else:
                waits = 0
            continue

        el, op = d.element, d.operation
        if op == "PRESS_ENTER":
            if last_fill is None:
                failures += 1
                history.append(_entry(op, "press Enter", error="no field has been typed into yet"))
                continue
            step = Step(id="", action="press", selector=last_fill.selector, value="Enter",
                        fallback_selectors=last_fill.fallback_selectors, frame=last_fill.frame,
                        description="press " + last_fill.description.split(" ", 1)[1])
        else:
            try:
                # No verifiable selector means this node can't be recorded; treat it as
                # a failed iteration so the loop excludes it instead of saving a dead step.
                sels = selectors_for(page, el, hints=hints)
                value = jev.value(snap, goal, el, candidates, history) if op == "TYPE" else None
            except (RuntimeError, ValueError) as e:
                failures += 1
                history.append(_entry(op, f"{ACTIONS[op]} {el.role} {el.label}",
                                      error=str(e).splitlines()[0]))
                continue
            if op == "TYPE":
                if value is None:
                    value = text.compose(goal, el, snap, history)
                kept = [s for s in sels if not embeds_value(s, value)]
                sels = kept or sels[-1:]
            action = ACTIONS[op]
            step = Step(id="", action=action, selector=sels[0], fallback_selectors=sels[1:3],
                        frame=el.frame, value=value, description=f"{action} {el.role} {el.label}")

        try:
            perform(page, step, ctx)
        except Exception as e:
            error = str(e).splitlines()[0]
            events.emit("action", action=step.action, description=step.description, value=step.value,
                        ok=False, error=error)
            failures += 1
            history.append(_entry(op, step.description, step.value, error=error))
            if el is not None:
                key = (op, el.frame, el.node)
                failed[key] = failed.get(key, 0) + 1
                if failed[key] >= 2:
                    exclude.add((el.frame, el.node))
            continue

        after = observe(page) if step.action == "fill" else _observe_changed(page, snap)
        changed = after.fingerprint != snap.fingerprint or after.url != snap.url
        expects = None if step.action == "fill" else derive_expects(snap, after, step)
        trace.append({"action": step.action, "selector": step.selector, "frame": step.frame,
                      "fallback_selectors": step.fallback_selectors, "value": step.value,
                      "description": step.description,
                      "expects": expects.model_dump() if expects else None,
                      "url_before": snap.url, "url_after": after.url,
                      "fingerprint_before": snap.fingerprint, "page_changed": changed,
                      "decision": {"operation": op, "probability": d.probability,
                                   "confidence": d.confidence, "latency_ms": d.latency_ms}})
        history.append(_entry(op, step.description, step.value, page_changed=changed))
        events.emit("action", action=step.action, description=step.description, value=step.value, ok=True)
        events.shot(page)
        failures = 0
        if step.action == "fill":
            last_fill = step
        else:
            # A fill changes no roles or labels, so it can never prove progress here.
            no_change = 0 if changed else no_change + 1
            if no_change >= 3:
                return trace, "blocked"
        if ws_path(after.url) != ws_path(snap.url):
            failed.clear()
            exclude.clear()  # node ids restart in a new document

    return trace, "budget"


def _assemble(name: str, intent: str, trace: list[dict], outcomes: list[str],
              vars: dict[str, str] | None, start: str, final_text: str) -> Case:
    trace = _templatize(trace, vars)
    steps = []
    for t in trace:
        # A click that moved nothing and proved nothing is noise in the replay, unless it
        # targets an entity by {{var}}: selecting an already-selected row looks like a no-op.
        if (t["action"] in ("click", "hover") and not t["page_changed"] and not t["expects"]
                and "{{" not in (t["selector"] or "")):
            continue
        steps.append(Step(id=f"s{len(steps) + 1}", action=t["action"], selector=t["selector"],
                          fallback_selectors=t["fallback_selectors"], frame=t["frame"],
                          value=t["value"], description=t["description"],
                          expects=Expect(**t["expects"]) if t["expects"] else None,
                          page_fingerprint=t["fingerprint_before"]))
    assertions = [Assertion(assertion="text_visible:{{" + k + "}}", mode="deterministic")
                  for k, v in (vars or {}).items() if len(v) >= 3 and v in final_text]
    assertions += [Assertion(assertion=_templatize(o, vars), mode="jev") for o in outcomes]
    return Case(name=name, intent=intent, start_path=start, steps=steps, assertions=assertions)


def _drive(session: Session, intent: str, name: str, vars: dict[str, str] | None, start: str) -> Case:
    live_intent = render(intent, vars)
    outcomes = outcome_clauses(live_intent)
    ctx = Ctx(ws=session.ws, vars=vars)
    page = session.page
    goto_app(page, resolve_path(start, ctx))
    budget = max(config.EXECUTOR_MAX_ACTIONS, 8 * len(_clauses(live_intent)))
    trace: list[dict] = []
    try:
        _, reason = run_executor(page, ctx, live_intent, outcomes,
                                 _candidates(live_intent, vars), budget, trace)
    except Exception:
        if trace:
            events.record(partial_trace=trace)
            events.emit("note", level="warn", text="partial trace kept on the run")
        raise
    if reason != "done":
        events.record(partial_trace=trace)
        raise RuntimeError(f"authoring stopped ({reason}) before the goal was verified — "
                           "partial trace kept on the run")

    case = _assemble(name, intent, trace, outcomes, vars, start, observe(page).text)
    case.meta.created_at = datetime.now(timezone.utc).isoformat()
    save(case)
    events.emit("note", level="info", text=f"saved {name} — {len(case.steps)} steps, "
                                            f"{len(case.assertions)} assertions")
    return case


def author_case(intent: str, name: str | None = None, headless: bool = True,
                vars: dict[str, str] | None = None, session: Session | None = None,
                start: str = "/:ws/home") -> Case:
    """Author one case against the live app, in the given session or a new one."""
    name = name or derive_name(intent)
    if session is not None:
        return _drive(session, intent, name, vars, start)
    with Session(headless=headless) as owned:
        owned.ensure_logged_in()
        return _drive(owned, intent, name, vars, start)


def _verify_vars(vars: dict[str, str] | None, stamp: int) -> dict[str, str]:
    """Append a fresh suffix to each var so the verification replay creates new data."""
    return {k: f"{v}-v{stamp}" for k, v in (vars or {}).items()}


def verify_case(case: Case, vars: dict[str, str] | None = None, headless: bool = True):
    """Replay the case once without healing against fresh vars and return the RunResult."""
    from groundhog.runner.replay import run_case

    fresh = _verify_vars(vars, int(datetime.now(timezone.utc).timestamp()))
    events.emit("note", level="info", text=f"verify: replaying {case.name} once against fresh data"
                + (f" ({', '.join(fresh.values())})" if fresh else ""))
    with Session(headless=headless) as session:
        session.ensure_logged_in()
        result = run_case(case, session, vars=fresh, heal=False)
    if fresh:
        events.emit("note", level="warn", text=f"verification created {', '.join(fresh.values())}; "
                                                "delete them if you do not need them.")
    return result
