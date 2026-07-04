"""Run reports: a markdown narrative + a JSON twin in runs/."""

import json
from dataclasses import asdict
from datetime import datetime, timezone

from groundhog import config
from groundhog.runner.replay import RunResult

MODE_ICON = {"static": "·", "fallback": "↪", "healed": "↻", "failed": "✗", "skipped": "⏭"}


def write_report(result: RunResult, tokens: dict | None = None) -> str:
    """Write runs/<case>-<ts>.{md,json}; returns the markdown path."""
    config.RUNS_DIR.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    base = config.RUNS_DIR / f"{result.case}-{ts}"

    payload = {**asdict(result), "tokens": tokens or {}}
    base.with_suffix(".json").write_text(json.dumps(payload, indent=2) + "\n")

    lines = [
        f"# {result.case} — {'PASSED' if result.passed else 'FAILED'}",
        f"{result.started_at} · {result.total_ms}ms · {result.healed} healed step(s)",
        "",
        "## Steps",
        "| # | mode | step | selector | ms |",
        "|---|------|------|----------|----|",
    ]
    for i, s in enumerate(result.steps, 1):
        note = f" — {s.error}" if s.error else (" (drift)" if s.drift else "")
        lines.append(f"| {i} | {MODE_ICON.get(s.mode, '?')} {s.mode} | {s.description}{note} | `{s.selector or ''}` | {s.ms} |")
    if result.assertions:
        lines += ["", "## Assertions"]
        for a in result.assertions:
            conf = f", confidence {a.confidence:.2f}" if a.confidence is not None else ""
            lines.append(f"- {'✓' if a.passed else '✗'} [{a.mode}] {a.assertion} — {a.reasoning}{conf}")
    if tokens:
        lines += ["", "## Cost", "```json", json.dumps(tokens, indent=2), "```"]
    else:
        lines += ["", "## Cost", "Zero LLM calls — fully static run."]
    base.with_suffix(".md").write_text("\n".join(lines) + "\n")
    return str(base.with_suffix(".md"))
