"""Static replay with agent-fallback-only-on-failure.

Every run after authoring costs zero tokens until the UI drifts: each step walks
selector → fallback_selectors deterministically; only a step that still fails
wakes the healer (one FAST call). A successful heal is persisted into the case
JSON and the next run is fully static again.
"""

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from rich.console import Console

from groundhog.browser.actions import Ctx, check_expects, goto_app, resolve_path, run_step, settle
from groundhog.browser.session import Session
from groundhog.cases.schema import Assertion, Case, Expect, Heal
from groundhog.cases.store import render, save

console = Console()
MODE_STYLE = {"static": "dim", "fallback": "yellow", "healed": "magenta", "failed": "red", "skipped": "dim"}


@dataclass
class StepResult:
    id: str
    description: str
    mode: str  # static | fallback | healed | failed | skipped
    selector: str | None
    ms: int
    drift: bool = False
    error: str | None = None


@dataclass
class AssertionResult:
    assertion: str
    mode: str  # deterministic | llm
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


def _judge_llm(page, a: Assertion, ctx: Ctx, retries: int = 2) -> AssertionResult:
    from groundhog.agent.judge import judge  # lazy: static runs never import the LLM stack

    verdict = judge(page, render(a.assertion, ctx.vars))
    for _ in range(retries):
        if verdict.passed:
            break
        # Async data (metrics, lists) can land after the step settles — re-judge.
        page.wait_for_timeout(1500)
        settle(page)
        verdict = judge(page, render(a.assertion, ctx.vars))
    return AssertionResult(assertion=a.assertion, mode="llm", passed=verdict.passed,
                           reasoning=verdict.reasoning, confidence=verdict.confidence)


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

            # drag never heals: two endpoints double the wrong-element risk, and a
            # mis-healed edge silently rewires the workflow — fail honestly instead.
            if not outcome.ok and heal and step.action not in ("goto", "drag"):
                fix = _try_heal(page, step, ctx, error)
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
        style = MODE_STYLE.get(s.mode, "")
        console.print(f"  [{style}]{s.mode:>8}[/] {i}. {s.description}" + (f" [red]— {s.error}[/]" if s.error else ""))

    if not aborted:
        for a in case.assertions:
            r = _check_deterministic(page, a, ctx) if a.mode == "deterministic" else _judge_llm(page, a, ctx)
            result.assertions.append(r)
            console.print(f"  [{'green' if r.passed else 'red'}]{'✓' if r.passed else '✗'}[/] {r.assertion} — {r.reasoning}")

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
    try:
        from groundhog.graph.ingest import ingest_run

        ingest_run(case, result.passed)
    except Exception:
        pass  # graph is an accelerator, never a prerequisite
    return result


def _try_heal(page, step, ctx: Ctx, error: str | None):
    """One FAST call: replacement selector or refusal. Returns a Heal or None."""
    try:
        from groundhog.agent.healer import heal_step

        fix = heal_step(page, step, ctx, error)
    except Exception:
        return None  # healer unavailable (no API key, network) — fail the step honestly
    if not fix:
        return None
    try:  # the graph learns the healed element too
        from groundhog.graph import store as graph

        graph.upsert_element(graph.page_key(page.url), fix.selector,
                             kind="nav", description=step.description)
    except Exception:
        pass
    return Heal(step=step.id, old=step.selector or "", new=fix.selector,
                at=datetime.now(timezone.utc).isoformat(), reason=fix.reasoning)


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
