"""Replay a saved case step by step, asking Jev only to heal a step no selector matches and to judge "jev" assertions.

Each step tries its selector, then its fallback selectors. A heal from a passing run is saved into the case.
"""

import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Literal

from groundhog import config, events, jev
from groundhog.browser.actions import Ctx, check_expects, goto_app, perform, resolve_path, run_step, settle
from groundhog.browser.session import Session
from groundhog.browser.snapshot import observe, selectors_for
from groundhog.cases.schema import Assertion, Case, Expect, Heal
from groundhog.cases.store import count_run, render, save

# Words that mark a committing or a backing-out action; a heal must not swap one for the other.
COMMITTING = re.compile(r"delete|remove|submit|confirm|save|create", re.I)
BACKING_OUT = re.compile(r"cancel|close|back|dismiss|discard", re.I)


@dataclass
class StepResult:
    id: str
    description: str
    mode: Literal["static", "fallback", "healed", "failed", "skipped"]
    selector: str | None
    ms: int
    drift: bool = False
    error: str | None = None


@dataclass
class AssertionResult:
    assertion: str
    mode: Literal["deterministic", "jev"]
    passed: bool
    reasoning: str = ""
    confidence: float | None = None


@dataclass
class RunResult:
    passed: bool = False
    steps: list[StepResult] = field(default_factory=list)
    assertions: list[AssertionResult] = field(default_factory=list)
    healed: int = 0
    total_ms: int = 0


def _check_deterministic(page, a: Assertion, ctx: Ctx) -> AssertionResult:
    kind, _, value = a.assertion.partition(":")
    ok = check_expects(page, Expect(kind=kind, value=value), ctx)
    return AssertionResult(assertion=a.assertion, mode="deterministic", passed=ok,
                           reasoning=f"{kind}={value!r} is {'true' if ok else 'false'} on the live page")


VERBS = r"(?=(?:has|is|was|are|maps|shows|appears|contains|no longer)\b)"
CLAUSE = re.compile(rf",\s*and\s+|\s+and\s+{VERBS}|,\s+{VERBS}")


def _clauses(text: str) -> list[str]:
    parts = [c.strip() for c in CLAUSE.split(text) if c.strip()]
    return parts or [text]


NEGATED = re.compile(r"\b(no longer|not|never|absent|gone|removed|deleted|disappear)", re.I)


def _absent(outcomes: list[str], snap, ctx: Ctx) -> bool:
    """True when every outcome is negated and none of the var values it names is on the page."""
    values = [v for v in (ctx.vars or {}).values() if len(v) >= 3 and any(v in o for o in outcomes)]
    if not values or not all(NEGATED.search(o) for o in outcomes):
        return False
    haystack = snap.text + " ".join(el.label + " " + el.value for el in snap.elements)
    return not any(v in haystack for v in values)


def _judge(page, case: Case, a: Assertion, ctx: Ctx, retries: int = 2) -> AssertionResult:
    goal = render(case.intent, ctx.vars)
    # Judge each clause of a compound assertion separately; the weakest clause decides.
    outcomes = _clauses(render(a.assertion, ctx.vars))
    try:
        snap = observe(page)
        if _absent(outcomes, snap, ctx):
            return AssertionResult(assertion=a.assertion, mode="jev", passed=True, confidence=1.0,
                                   reasoning="the named value is nowhere on the page")
        p = min(jev.judge(snap, o, goal) for o in outcomes)
        for _ in range(retries):
            if p >= config.JUDGE_THRESHOLD:
                break
            # Data can load after the step settles, so judge again.
            page.wait_for_timeout(1500)
            settle(page)
            p = min(jev.judge(observe(page), o, goal) for o in outcomes)
    except Exception as e:
        # A judge that cannot run is a failed assertion, never a dead run.
        return AssertionResult(assertion=a.assertion, mode="jev", passed=False, reasoning=str(e)[:200])
    return AssertionResult(assertion=a.assertion, mode="jev", passed=p >= config.JUDGE_THRESHOLD,
                           reasoning=f"jev p={p:.2f}", confidence=p)


def run_case(case: Case, session: Session, vars: dict[str, str] | None = None,
             heal: bool = True) -> RunResult:
    page = session.page
    ctx = Ctx(ws=session.ws, vars=vars)
    result = RunResult()
    clock = time.monotonic()

    goto_app(page, resolve_path(case.start_path, ctx))

    healed_steps: list[tuple[str, Heal]] = []
    aborted = False
    for i, step in enumerate(case.steps, 1):
        if aborted:
            s = StepResult(step.id, step.description, "skipped", step.selector, 0)
        else:
            t0 = time.monotonic()
            outcome = run_step(page, step, ctx)
            mode, selector, error = outcome.mode, outcome.selector or step.selector, outcome.error

            # Heal only when no selector matched; a failed expectation is a page problem.
            if not outcome.ok and heal and step.action != "goto" and outcome.selector is None:
                fix = _try_heal(page, step, ctx)
                if fix:
                    mode, selector, error = "healed", fix.new, None
                    healed_steps.append((step.id, fix))
                    outcome.ok = True

            ms = int((time.monotonic() - t0) * 1000)
            if outcome.ok:
                s = StepResult(step.id, step.description, mode, selector, ms, outcome.drift)
            else:
                s = StepResult(step.id, step.description, "failed", selector, ms, outcome.drift, error)
                aborted = True  # later steps depend on this one
        result.steps.append(s)
        events.emit("step", i=i, **asdict(s))
        if s.mode != "skipped":
            events.shot(page)

    if not aborted:
        for a in case.assertions:
            r = _check_deterministic(page, a, ctx) if a.mode == "deterministic" else _judge(page, case, a, ctx)
            result.assertions.append(r)
            events.emit("assertion", **asdict(r))

    result.healed = len(healed_steps)
    result.passed = (not aborted
                     and all(s.mode != "failed" for s in result.steps)
                     and all(a.passed for a in result.assertions))
    result.total_ms = int((time.monotonic() - clock) * 1000)

    # Save heals only from a passing run.
    if result.passed and healed_steps:
        _save_heals(case, healed_steps)
    count_run(case.name)
    return result


def _contradicts(step, el) -> bool:
    """True when the picked element's label reverses the step's intent."""
    intent = f"{step.description} {step.selector or ''}"
    label = el.label or ""
    return bool((COMMITTING.search(intent) and BACKING_OUT.search(label))
                or (BACKING_OUT.search(intent) and COMMITTING.search(label)))


def _try_heal(page, step, ctx: Ctx) -> Heal | None:
    """Ask Jev for a replacement element once; return a Heal when its selector works, else None."""
    try:
        el, p = jev.heal(observe(page), step)
        if el is None or p < config.HEAL_THRESHOLD or el.frame != step.frame or _contradicts(step, el):
            return None
        sel = selectors_for(page, el, hints=list((ctx.vars or {}).values()))[0]
        perform(page, step, ctx, selector=sel)
        if step.expects and not check_expects(page, step.expects, ctx):
            return None
    except Exception:
        return None  # no key, no network, or the new selector did not work
    return Heal(step=step.id, old=step.selector or "", new=sel,
                at=datetime.now(timezone.utc).isoformat(),
                reason=f"jev picked [{el.role} {el.label}] p={p:.2f}")


def _save_heals(case: Case, healed: list[tuple[str, Heal]]) -> None:
    by_id = {s.id: s for s in case.steps}
    for step_id, fix in healed:
        step = by_id[step_id]
        old = step.selector
        step.selector = fix.new
        if old and old not in step.fallback_selectors:
            step.fallback_selectors.append(old)  # keep the old one as a fallback
        step.healed_count += 1
        case.meta.heals.append(fix)
    save(case)
