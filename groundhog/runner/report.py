"""Run reports: a markdown narrative + a JSON twin in runs/."""

import json
from dataclasses import asdict
from datetime import datetime, timezone

from groundhog import config
from groundhog.runner.flow import FlowResult
from groundhog.runner.replay import RunResult

MODE_ICON = {"static": "·", "fallback": "↪", "healed": "↻", "failed": "✗", "skipped": "⏭"}


def _case_lines(result: RunResult, heading: str = "##") -> list[str]:
    lines = [
        f"{heading} Steps",
        "| # | mode | step | selector | ms |",
        "|---|------|------|----------|----|",
    ]
    for i, s in enumerate(result.steps, 1):
        note = f" — {s.error}" if s.error else (" (drift)" if s.drift else "")
        lines.append(f"| {i} | {MODE_ICON.get(s.mode, '?')} {s.mode} | {s.description}{note} | `{s.selector or ''}` | {s.ms} |")
    if result.assertions:
        lines += ["", f"{heading} Assertions"]
        for a in result.assertions:
            conf = f", confidence {a.confidence:.2f}" if a.confidence is not None else ""
            lines.append(f"- {'✓' if a.passed else '✗'} [{a.mode}] {a.assertion} — {a.reasoning}{conf}")
    return lines


def _cost_lines(tokens: dict | None) -> list[str]:
    if tokens:
        return ["", "## Cost", "```json", json.dumps(tokens, indent=2), "```"]
    return ["", "## Cost", "Zero LLM calls — fully static run."]


def _write(name: str, payload: dict, lines: list[str]) -> str:
    """Write runs/<name>-<ts>.{md,json}; returns the markdown path."""
    config.RUNS_DIR.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    base = config.RUNS_DIR / f"{name}-{ts}"
    base.with_suffix(".json").write_text(json.dumps(payload, indent=2) + "\n")
    base.with_suffix(".md").write_text("\n".join(lines) + "\n")
    return str(base.with_suffix(".md"))


def write_report(result: RunResult, tokens: dict | None = None) -> str:
    lines = [
        f"# {result.case} — {'PASSED' if result.passed else 'FAILED'}",
        f"{result.started_at} · {result.total_ms}ms · {result.healed} healed step(s)",
        "",
    ] + _case_lines(result) + _cost_lines(tokens)
    return _write(result.case, {**asdict(result), "tokens": tokens or {}}, lines)


def write_flow_report(result: FlowResult, tokens: dict | None = None) -> str:
    """One report for the whole flow, a section per case run."""
    lines = [
        f"# flow {result.flow} — {'PASSED' if result.passed else 'FAILED'}",
        f"{result.started_at} · {result.total_ms}ms · {len(result.runs)} case(s)",
    ]
    for cr in result.runs:
        # error without a result: the case never ran at all (e.g. file missing)
        verdict = ("FAILED" if cr.error else "SKIPPED") if cr.result is None \
            else ("PASSED" if cr.result.passed else "FAILED")
        lines += ["", f"## {cr.name} ({cr.stage}) — {verdict}"]
        if cr.error:
            lines += [f"could not run: {cr.error}"]
        if cr.result:
            lines += [f"{cr.result.total_ms}ms · {cr.result.healed} healed step(s)", ""]
            lines += _case_lines(cr.result, heading="###")
    lines += _cost_lines(tokens)
    return _write(result.flow, {**asdict(result), "tokens": tokens or {}}, lines)
