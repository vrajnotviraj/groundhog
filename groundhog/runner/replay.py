"""Static replay with a Jev fallback only on failure.

Every run after authoring costs zero AI calls until the UI drifts: each step
walks selector → fallback_selectors deterministically; only a step that still
fails wakes Jev (one call). A successful heal is persisted into the case JSON
and the next run is fully static again. "jev" assertions are the exception:
they are judged by Jev on the final page.
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
from groundhog.cases.store import render, save

# A heal that flips a step's intent is worse than a failed step: it can delete
# the wrong thing or silently skip the action the test exists for.
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
    case: str
    passed: bool = False
    steps: list[StepResult] = field(default_factory=list)
    assertions: list[AssertionResult] = field(default_factory=list)
    healed: int = 0
    total_ms: int = 0
    started_at: str = ""


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
    """An absence outcome about a var value is a literal check code can settle:
    when every clause is negated and no var value is anywhere on the page, it holds."""
    values = [v for v in (ctx.vars or {}).values() if len(v) >= 3 and any(v in o for o in outcomes)]
    if not values or not all(NEGATED.search(o) for o in outcomes):
        return False
    haystack = snap.text + " ".join(el.label + " " + el.value for el in snap.elements)
    return not any(v in haystack for v in values)


def _judge(page, case: Case, a: Assertion, ctx: Ctx, retries: int = 2) -> AssertionResult:
    goal = render(case.intent, ctx.vars)
    # One Noul per condition: "is Transactional, has X and maps to Y" judged whole reads
    # as unsure, so a compound assertion is split and the weakest clause decides.
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
            # Async data (metrics, lists) can land after the step settles — re-judge.
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
    result = RunResult(case=case.name, started_at=datetime.now(timezone.utc).isoformat())
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

            # Heal only when nothing matched: a resolved selector whose expects failed is a
            # page problem (rejected submit, wrong state), and a new selector can't fix that.
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
                aborted = True  # linear flows can't recover once a step leaves the wrong state
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

    # Persist heals only on a passing run, so a wrong-element heal that merely
    # didn't throw can't poison every future run.
    if result.passed and healed_steps:
        _persist_heals(case, healed_steps)
    case.meta.runs += 1
    save(case)
    return result


def _contradicts(step, el) -> bool:
    """True when the picked element's label reverses the step's intent."""
    intent = f"{step.description} {step.selector or ''}"
    label = el.label or ""
    return bool((COMMITTING.search(intent) and BACKING_OUT.search(label))
                or (BACKING_OUT.search(intent) and COMMITTING.search(label)))


def _try_heal(page, step, ctx: Ctx) -> Heal | None:
    """One Jev call: it picks an element from the live table, code derives the
    selector. Returns a Heal when the replacement actually worked, else None."""
    try:
        el, p = jev.heal(observe(page), step)
        if el is None or p < config.HEAL_THRESHOLD or el.frame != step.frame or _contradicts(step, el):
            return None
        sel = selectors_for(page, el, hints=list((ctx.vars or {}).values()))[0]
        perform(page, step, ctx, selector=sel)
        if step.expects and not check_expects(page, step.expects, ctx):
            return None
    except Exception:
        return None  # no key, no network, or the replacement didn't work — fail honestly
    return Heal(step=step.id, old=step.selector or "", new=sel,
                at=datetime.now(timezone.utc).isoformat(),
                reason=f"jev picked [{el.role} {el.label}] p={p:.2f}")


def _persist_heals(case: Case, healed: list[tuple[str, Heal]]) -> None:
    by_id = {s.id: s for s in case.steps}
    for step_id, fix in healed:
        step = by_id[step_id]
        old = step.selector
        step.selector = fix.new
        if old and old not in step.fallback_selectors:
            step.fallback_selectors.append(old)  # keep the old one as a fallback
        step.healed_count += 1
        case.meta.heals.append(fix)
