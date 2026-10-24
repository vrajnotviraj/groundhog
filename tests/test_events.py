"""The run document the worker writes: events in order, shots, summary fields."""

from groundhog import db, events


class _Page:
    def screenshot(self, **kw):
        return b"\xff\xd8jpeg"


def _run(run_id):
    return db.runs().find_one({"_id": run_id})


def test_emit_appends_events_to_the_run_in_order():
    run_id = events.start("abc123abc123", "run", "dashboard-data", {"name": "gh-1"})
    events.emit("note", level="info", text="first")
    events.emit("step", i=1, id="s1", description="click", mode="static", selector="#a", ms=5, drift=False,
                error=None)
    run = _run(run_id)
    assert (run["status"], run["target"], run["vars"]) == ("running", "dashboard-data", {"name": "gh-1"})
    assert [(e["seq"], e["kind"]) for e in run["events"]] == [(1, "note"), (2, "step")]


def test_start_without_an_id_still_creates_a_run():
    run_id = events.start(None, "author", "new-case", None, intent="create a template")
    run = _run(run_id)
    assert len(run_id) == 12 and run["intent"] == "create a template" and run["events"] == []


def test_shot_stores_a_jpeg_and_a_shot_event():
    run_id = events.start(None, "run", "c")
    events.shot(_Page())
    shot = db.shots().find_one({"run_id": run_id})
    assert shot["seq"] == 1 and bytes(shot["jpeg"]) == b"\xff\xd8jpeg"
    assert _run(run_id)["events"][0]["kind"] == "shot"


def test_record_sets_fields_on_the_open_run():
    run_id = events.start(None, "author", "c")
    events.record(partial_trace=[{"action": "click"}])
    assert _run(run_id)["partial_trace"] == [{"action": "click"}]


def test_finish_sets_status_summary_and_ai_calls(monkeypatch):
    monkeypatch.setattr(events.jev, "usage_snapshot", lambda: {"calls": 2})
    monkeypatch.setattr(events.client, "usage_snapshot", lambda: None)
    run_id = events.start(None, "run", "c")
    events.finish("passed", total_ms=12, healed=1, modes=["static", "healed"])
    run = _run(run_id)
    assert (run["status"], run["total_ms"], run["healed"], run["modes"]) == ("passed", 12, 1, ["static", "healed"])
    assert run["ai_calls"] == 2 and run["usage"] == {"jev": {"calls": 2}} and run["finished_at"]


def test_a_decision_shows_runners_up_only_when_hesitant(capsys):
    events.emit("decision", operation="CLICK", label="Create", probability=0.95, confidence=0.9, latency_ms=10,
                detail="ops CLICK=0.95")
    events.emit("decision", operation="WAIT", label="", probability=0.4, confidence=0.4, latency_ms=10,
                detail="ops WAIT=0.40 CLICK=0.35")
    out = capsys.readouterr().out
    assert "ops CLICK=0.95" not in out and "CLICK=0.35" in out
