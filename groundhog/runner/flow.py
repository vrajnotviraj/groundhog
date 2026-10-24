"""Chain saved cases into one run: shared vars, always-run cleanup.

A flow reuses one logged-in browser session across its cases and gives them a
common var namespace, so a case can act on data an earlier case created. The
chain stops at the first failing case (later cases would act on state that
never materialized), but cleanup cases run regardless — a flow that creates
data always gets its chance to delete it.
"""

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

from groundhog import events
from groundhog.browser.session import Session
from groundhog.cases import store
from groundhog.cases.schema import Flow, FlowCase
from groundhog.cases.store import render
from groundhog.runner.replay import RunResult, run_case


@dataclass
class CaseRun:
    name: str
    stage: Literal["chain", "cleanup"]
    result: RunResult | None  # None: skipped, or the case itself failed to load
    error: str | None = None  # set when the case file couldn't be loaded/run at all


@dataclass
class FlowResult:
    flow: str
    passed: bool = False
    runs: list[CaseRun] = field(default_factory=list)
    total_ms: int = 0
    started_at: str = ""


def shared_vars(flow: Flow, cli_vars: dict[str, str] | None = None) -> dict[str, str]:
    """Flow var defaults (with {{stamp}} rendered to a per-run timestamp for
    collision-free data), overridden by explicit --var values. A second render
    pass lets one var reference another — "query": "{{name}}" wires the search
    case to the template the chain created."""
    stamp = {"stamp": datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")}
    merged = {k: render(v, stamp) for k, v in flow.vars.items()} | (cli_vars or {})
    return {k: render(v, merged) for k, v in merged.items()}


def case_vars(shared: dict[str, str], fc: FlowCase) -> dict[str, str]:
    """Per-case overrides render against the shared vars and win over them."""
    return shared | {k: render(v, shared) for k, v in fc.vars.items()}


def _load_case(fc: FlowCase):
    """A deleted/renamed case file must not kill the whole flow — report it
    as an honest failure for this case and let the chain/cleanup loop react,
    same as any other failing case."""
    try:
        return store.load(fc.case), None
    except Exception as e:
        return None, str(e)


def _run_one(fc: FlowCase, stage: str, session: Session, shared: dict[str, str], heal: bool) -> CaseRun:
    """Run one case of the flow between a case start and a case end event."""
    events.emit("case", phase="start", case=fc.case, stage=stage)
    case, err = _load_case(fc)
    if case is None:
        events.emit("case", phase="end", case=fc.case, stage=stage, passed=False,
                    error=f"could not load case — {err}")
        return CaseRun(fc.case, stage, None, error=err)
    r = run_case(case, session, vars=case_vars(shared, fc), heal=heal)
    events.emit("case", phase="end", case=fc.case, stage=stage, passed=r.passed,
                healed=r.healed, total_ms=r.total_ms)
    return CaseRun(fc.case, stage, r)


def run_flow(flow: Flow, session: Session, vars: dict[str, str] | None = None,
             heal: bool = True) -> FlowResult:
    shared = shared_vars(flow, vars)
    result = FlowResult(flow=flow.name, started_at=datetime.now(timezone.utc).isoformat())
    clock = time.monotonic()

    chain_failed = False
    for fc in flow.chain:
        if chain_failed:
            events.emit("case", phase="start", case=fc.case, stage="chain")
            events.emit("case", phase="end", case=fc.case, stage="chain", passed=False,
                        error="skipped — an earlier chain case failed")
            result.runs.append(CaseRun(fc.case, "chain", None))
            continue
        cr = _run_one(fc, "chain", session, shared, heal)
        result.runs.append(cr)
        chain_failed = cr.result is None or not cr.result.passed
    for fc in flow.cleanup:
        result.runs.append(_run_one(fc, "cleanup", session, shared, heal))

    # Leftover data is a real failure: a cleanup miss fails the flow too.
    result.passed = all(cr.result is not None and cr.result.passed for cr in result.runs)
    result.total_ms = int((time.monotonic() - clock) * 1000)
    return result
