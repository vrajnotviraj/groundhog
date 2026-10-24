"""Run a flow: its chain of cases in one session with shared vars, then its cleanup cases.

The chain stops at the first failing case; cleanup always runs.
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
    result: RunResult | None  # None when skipped or not loadable
    error: str | None = None  # why the case could not be loaded


@dataclass
class FlowResult:
    passed: bool = False
    runs: list[CaseRun] = field(default_factory=list)
    total_ms: int = 0


def shared_vars(flow: Flow, cli_vars: dict[str, str] | None = None) -> dict[str, str]:
    """The flow's vars with {{stamp}} rendered, overridden by CLI vars, then rendered against each other."""
    stamp = {"stamp": datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")}
    merged = {k: render(v, stamp) for k, v in flow.vars.items()} | (cli_vars or {})
    return {k: render(v, merged) for k, v in merged.items()}


def case_vars(shared: dict[str, str], fc: FlowCase) -> dict[str, str]:
    """The shared vars plus the case's own overrides, rendered against the shared vars."""
    return shared | {k: render(v, shared) for k, v in fc.vars.items()}


def _load_case(fc: FlowCase):
    """Load a case; return (None, error) instead of raising."""
    try:
        return store.load(fc.case), None
    except Exception as e:
        return None, str(e)


def _run_flow_case(fc: FlowCase, stage: str, session: Session, shared: dict[str, str], heal: bool) -> CaseRun:
    """Run one case of the flow, emitting a case start and a case end event."""
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
    result = FlowResult()
    clock = time.monotonic()

    chain_failed = False
    for fc in flow.chain:
        if chain_failed:
            events.emit("case", phase="start", case=fc.case, stage="chain")
            events.emit("case", phase="end", case=fc.case, stage="chain", passed=False,
                        error="skipped — an earlier chain case failed")
            result.runs.append(CaseRun(fc.case, "chain", None))
            continue
        cr = _run_flow_case(fc, "chain", session, shared, heal)
        result.runs.append(cr)
        chain_failed = cr.result is None or not cr.result.passed
    for fc in flow.cleanup:
        result.runs.append(_run_flow_case(fc, "cleanup", session, shared, heal))

    # A failed cleanup case fails the flow too.
    result.passed = all(cr.result is not None and cr.result.passed for cr in result.runs)
    result.total_ms = int((time.monotonic() - clock) * 1000)
    return result
