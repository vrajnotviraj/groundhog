import types
from types import SimpleNamespace

from groundhog import config
from groundhog.browser.actions import StepOutcome
from groundhog.cases.schema import Assertion, Case, Expect, Step
from groundhog.runner import replay


def test_run_case_resolves_ws_and_vars_in_start_path(monkeypatch):
    """start_path must go through resolve_path (vars + :ws), not a manual
    .replace('/:ws', ...) that silently drops any {{var}} in the path."""
    monkeypatch.setattr(replay, "save", lambda case: None)
    captured = {}
    monkeypatch.setattr(replay, "goto_app", lambda page, url: captured.setdefault("url", url))
    case = Case(name="c", intent="i", start_path="/:ws/templates/{{name}}/v1", steps=[])
    session = types.SimpleNamespace(page=None, ws="FYABC123")

    replay.run_case(case, session, vars={"name": "gh-1"})

    assert captured["url"] == f"{config.BASE_URL}/FYABC123/templates/gh-1/v1"


# --- heal: one Jev call picks an element, code derives and verifies the selector ---


def _heal_stubs(monkeypatch, el, p, performed=None):
    monkeypatch.setattr(replay, "observe", lambda page, **kw: SimpleNamespace())
    monkeypatch.setattr(replay.jev, "heal", lambda snap, step: (el, p))
    monkeypatch.setattr(replay, "selectors_for", lambda page, el, hints=(): ["#new", "#alt"])
    monkeypatch.setattr(replay, "perform", performed or (lambda *a, **kw: None))


def _el(label="Delete", frame=None):
    return SimpleNamespace(role="button", label=label, frame=frame)


def test_heal_accepts_a_confident_matching_element(monkeypatch):
    _heal_stubs(monkeypatch, _el(), 0.91)
    step = Step(id="s1", action="click", selector="#old", description="click button Delete")

    fix = replay._try_heal(None, step, replay.Ctx())

    assert fix.new == "#new" and fix.old == "#old" and "p=0.91" in fix.reason


def test_heal_refuses_an_element_that_reverses_the_step(monkeypatch):
    # A Delete step must never heal onto Cancel, however confident Jev is.
    _heal_stubs(monkeypatch, _el(label="Cancel"), 0.99)
    step = Step(id="s1", action="click", selector="#old", description="click button Delete")
    assert replay._try_heal(None, step, replay.Ctx()) is None


def test_heal_refuses_below_the_threshold(monkeypatch):
    _heal_stubs(monkeypatch, _el(), config.HEAL_THRESHOLD - 0.01)
    step = Step(id="s1", action="click", selector="#old", description="click button Delete")
    assert replay._try_heal(None, step, replay.Ctx()) is None


def test_heal_refuses_an_element_in_another_frame(monkeypatch):
    # Same label, wrong document: the replacement selector wouldn't resolve.
    _heal_stubs(monkeypatch, _el(frame='iframe[name="editor"]'), 0.95)
    step = Step(id="s1", action="click", selector="#old", description="click button Delete")
    assert replay._try_heal(None, step, replay.Ctx()) is None


def test_heal_refuses_when_the_replacement_does_not_work(monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("selector resolved 0 elements")

    _heal_stubs(monkeypatch, _el(), 0.95, performed=boom)
    step = Step(id="s1", action="click", selector="#old", description="click button Delete")
    assert replay._try_heal(None, step, replay.Ctx()) is None


def test_heal_refuses_when_the_step_expects_still_fail(monkeypatch):
    _heal_stubs(monkeypatch, _el(), 0.95)
    monkeypatch.setattr(replay, "check_expects", lambda page, expects, ctx: False)
    step = Step(id="s1", action="click", selector="#old", description="click button Delete",
                expects=Expect(kind="url_contains", value="/templates"))
    assert replay._try_heal(None, step, replay.Ctx()) is None


def _healing_run(monkeypatch, steps, outcomes):
    """run_case over `steps` where run_step returns `outcomes` in order and the
    first step always heals."""
    monkeypatch.setattr(replay, "save", lambda case: None)
    monkeypatch.setattr(replay, "goto_app", lambda page, url: None)
    queue = list(outcomes)
    monkeypatch.setattr(replay, "run_step", lambda page, step, ctx: queue.pop(0))
    fix = replay.Heal(step="s1", old="#old", new="#new", at="now", reason="jev picked [button Delete] p=0.91")
    monkeypatch.setattr(replay, "_try_heal", lambda page, step, ctx: fix if step.id == "s1" else None)
    case = Case(name="c", intent="i", steps=steps)
    return case, replay.run_case(case, types.SimpleNamespace(page=None, ws=""))


def test_heal_is_persisted_on_a_passing_run(monkeypatch):
    steps = [Step(id="s1", action="click", selector="#old", description="click button Delete")]
    case, result = _healing_run(monkeypatch, steps, [StepOutcome(ok=False, error="boom")])

    assert result.passed and result.healed == 1
    assert case.steps[0].selector == "#new"
    assert "#old" in case.steps[0].fallback_selectors  # kept as a fallback
    assert case.steps[0].healed_count == 1 and len(case.meta.heals) == 1


def test_heal_is_not_persisted_when_a_later_step_fails(monkeypatch):
    # A heal that "worked" on a run that still failed may well be the wrong
    # element, so the JSON stays untouched.
    steps = [Step(id="s1", action="click", selector="#old", description="click button Delete"),
             Step(id="s2", action="click", selector="#other", description="click button Confirm")]
    case, result = _healing_run(monkeypatch, steps,
                                [StepOutcome(ok=False, error="boom"), StepOutcome(ok=False, error="gone")])

    assert not result.passed
    assert case.steps[0].selector == "#old" and case.meta.heals == []


# --- jev assertions ---


def _judged(monkeypatch, probabilities):
    queue = list(probabilities)
    monkeypatch.setattr(replay, "observe", lambda page, **kw: SimpleNamespace())
    monkeypatch.setattr(replay, "settle", lambda page: None)
    monkeypatch.setattr(replay.jev, "judge", lambda snap, outcome, goal: queue.pop(0))
    page = SimpleNamespace(wait_for_timeout=lambda ms: None)
    case = Case(name="c", intent="create {{name}}", steps=[])
    return replay._judge(page, case, Assertion(assertion="{{name}} is listed"), replay.Ctx(vars={"name": "gh-1"}))


def test_jev_assertion_passes_at_the_threshold(monkeypatch):
    r = _judged(monkeypatch, [config.JUDGE_THRESHOLD])
    assert r.passed and r.mode == "jev" and r.confidence == config.JUDGE_THRESHOLD


def test_jev_assertion_rejudges_after_a_settle(monkeypatch):
    # Async data can land after the step settles, so a low first read is retried.
    r = _judged(monkeypatch, [0.2, 0.95])
    assert r.passed and r.confidence == 0.95


def test_judge_failure_becomes_a_failed_assertion(monkeypatch):
    # No key, no network: the assertion fails, the run does not die.
    monkeypatch.setattr(replay, "observe", lambda page, **kw: SimpleNamespace())

    def boom(*a, **kw):
        raise RuntimeError("Jev is unavailable; no action executed.")

    monkeypatch.setattr(replay.jev, "judge", boom)
    r = replay._judge(None, Case(name="c", intent="i", steps=[]), Assertion(assertion="x"), replay.Ctx())
    assert not r.passed and "unavailable" in r.reasoning


def test_compound_assertion_is_judged_clause_by_clause():
    assert replay._clauses("the event named gh-1 has the template gh-1 selected and is mapped to the route gh-1") == [
        "the event named gh-1 has the template gh-1 selected", "is mapped to the route gh-1"]
    assert replay._clauses("verify gh-1 appears in the Simulator accounts list") == [
        "verify gh-1 appears in the Simulator accounts list"]
    assert replay._clauses("the template named gh-1 no longer appears in the templates list") == [
        "the template named gh-1 no longer appears in the templates list"]


def test_negated_outcome_about_an_absent_value_needs_no_judge():
    from types import SimpleNamespace

    snap = SimpleNamespace(text="Accounts 0 / 5\nAdd account",
                           elements=[SimpleNamespace(label="Add account", value="")])
    ctx = replay.Ctx(vars={"name": "gh-1"})
    assert replay._absent(["gh-1 no longer appears in the accounts list"], snap, ctx)
    present = SimpleNamespace(text="G gh-1\nAccounts 1 / 5", elements=[])
    assert not replay._absent(["gh-1 no longer appears in the accounts list"], present, ctx)
    assert not replay._absent(["gh-1 appears in the list"], snap, ctx)  # positive outcomes still go to Jev


def test_run_case_emits_a_shot_after_each_step_it_ran_but_not_a_skipped_one(monkeypatch):
    from groundhog import db, events

    monkeypatch.setattr(replay, "save", lambda case: None)
    monkeypatch.setattr(replay, "goto_app", lambda page, url: None)
    monkeypatch.setattr(replay, "run_step", lambda page, step, ctx: StepOutcome(
        ok=False, mode="failed", selector="#a", error="gone"))
    page = SimpleNamespace(screenshot=lambda **kw: b"jpeg")
    case = Case(name="c", intent="i", steps=[Step(id="s1", action="click", selector="#a"),
                                             Step(id="s2", action="click", selector="#b")])
    run_id = events.start(None, "run", "c", {})
    replay.run_case(case, SimpleNamespace(page=page, ws="FY1"), heal=False)
    kinds = [e["kind"] for e in db.runs().find_one({"_id": run_id})["events"]]
    assert kinds == ["step", "shot", "step"]
