"""Everything a run says goes through here: one console line, and one event on the run document.

A worker process opens a run with start(), emits events while it works and closes it with
finish(). The API never writes events; it reads the document, so a run started from the
terminal is watched live in the console just the same.
"""

import uuid
from datetime import datetime, timezone

from bson import Binary
from rich.console import Console
from rich.markup import escape

from groundhog import db, jev
from groundhog.llm import client

console = Console()
MODE_STYLE = {"static": "dim", "fallback": "yellow", "healed": "magenta", "failed": "red", "skipped": "dim"}
LEVEL_STYLE = {"info": "", "warn": "yellow", "error": "red"}

_run_id: str | None = None
_seq = 0


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def start(run_id: str | None, kind: str, target: str, vars: dict | None = None, intent: str | None = None) -> str:
    """Open the run document as running and return its id."""
    global _run_id, _seq
    _run_id, _seq = run_id or uuid.uuid4().hex[:12], 0
    fields = {"kind": kind, "target": target, "vars": vars or {}, "status": "running", "started_at": now()}
    if intent:
        fields["intent"] = intent
    db.runs().update_one({"_id": _run_id}, {"$set": fields, "$setOnInsert": {"created_at": now(), "events": []}},
                         upsert=True)
    return _run_id


def emit(kind: str, **data) -> dict:
    """Record one event: print it for the terminal and append it to the open run."""
    global _seq
    _seq += 1
    event = {"seq": _seq, "at": now(), "kind": kind, **data}
    _print(event)
    if _run_id:
        db.runs().update_one({"_id": _run_id}, {"$push": {"events": event}})
    return event


def shot(page) -> None:
    """Keep a small JPEG of the page for the run's viewer; a page that cannot be captured is skipped."""
    if not _run_id:
        return
    try:
        jpeg = page.screenshot(type="jpeg", quality=45)
    except Exception:
        return
    event = emit("shot")
    db.shots().insert_one({"run_id": _run_id, "seq": event["seq"], "jpeg": Binary(jpeg)})


def record(**fields) -> None:
    """Set extra fields on the open run, such as a partial authoring trace."""
    if _run_id:
        db.runs().update_one({"_id": _run_id}, {"$set": fields})


def finish(status: str, **summary) -> None:
    """Close the run: status is passed, failed or error; summary holds what the lists show."""
    global _run_id
    if not _run_id:
        return
    # Empty on a fully static run.
    spent = {k: v for k, v in (("jev", jev.usage_snapshot()), ("anthropic", client.usage_snapshot())) if v}
    fields = {"status": status, "finished_at": now(), "usage": spent,
              "ai_calls": sum(u.get("calls", 0) for u in spent.values()), **summary}
    db.runs().update_one({"_id": _run_id}, {"$set": fields})
    _run_id = None


def _print(e: dict) -> None:
    kind = e["kind"]
    if kind == "step":
        error = f" [red]— {escape(e['error'])}[/]" if e.get("error") else ""
        style = MODE_STYLE.get(e["mode"], "")
        console.print(f"  [{style}]{e['mode']:>8}[/] {e['i']}. {escape(e['description'])}{error}")
    elif kind == "assertion":
        mark = "[green]✓[/]" if e["passed"] else "[red]✗[/]"
        console.print(f"  {mark} {escape(e['assertion'])} — {escape(e['reasoning'])}")
    elif kind == "decision":
        line = f"{e['operation'].lower():<6} {e['label']}  (p {e['probability']:.2f} · {e['latency_ms']}ms)"
        if e["probability"] < 0.7 and e.get("detail"):
            line += f"\n         {e['detail']}"
        console.print(f"  [cyan]→[/] {escape(line)}")
    elif kind == "action" and not e["ok"]:
        console.print(f"  [red]✗[/] {escape(e.get('error') or e['description'])}")
    elif kind == "case" and e["phase"] == "start":
        stage = " [dim](cleanup)[/]" if e.get("stage") == "cleanup" else ""
        console.print(f"\n[bold]{escape(e['case'])}[/]{stage}")
    elif kind == "case" and e.get("error"):
        console.print(f"  [red]✗[/] {escape(e['error'])}")
    elif kind == "note":
        style = LEVEL_STYLE.get(e["level"], "")
        text = escape(e["text"])
        console.print(f"[{style}]{text}[/]" if style else text, highlight=False)
