from groundhog.agent.executor import _ELIDED, _elide_stale_states, _templatize


def _state(i: int) -> str:
    return f"Current URL: /page{i}\n\nAccessibility snapshot:\n- button 'x{i}'"


def _messages():
    return [
        {"role": "user", "content": f"Intent: x\n\n{_state(0)}"},
        {"role": "assistant", "content": "…"},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "1", "content": f"error: boom\n\n{_state(1)}"}]},
        {"role": "assistant", "content": "…"},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "2", "content": f"ok\n\n{_state(2)}"}]},
    ]


def test_elide_keeps_newest_states_and_outcome_lines():
    messages = _messages()
    _elide_stale_states(messages, keep=2)
    # Oldest state (initial user message) collapsed; its preamble survives.
    assert messages[0]["content"] == f"Intent: x\n\n{_ELIDED}"
    # Newest two states untouched — including the error line before the state.
    assert messages[2]["content"][0]["content"] == f"error: boom\n\n{_state(1)}"
    assert messages[4]["content"][0]["content"] == f"ok\n\n{_state(2)}"


def test_templatize_reverses_var_values_everywhere():
    trace = [{"action": "fill", "selector": '[placeholder="Enter Name"]', "value": "gh-lr1",
              "fallback_selectors": ['text="gh-lr1"'], "url_after": "/ws/routes/gh-lr1"}]
    done = {"assertions": ["the event gh-lr1 appears in the list"]}
    out_trace = _templatize(trace, {"name": "gh-lr1"})
    out_done = _templatize(done, {"name": "gh-lr1"})
    assert out_trace[0]["value"] == "{{name}}"
    assert out_trace[0]["fallback_selectors"] == ['text="{{name}}"']
    assert out_trace[0]["url_after"] == "/ws/routes/{{name}}"
    assert out_done["assertions"] == ["the event {{name}} appears in the list"]


def test_resolve_path_renders_vars_and_workspace():
    from groundhog import config
    from groundhog.browser.actions import Ctx, resolve_path

    got = resolve_path("/:ws/templates/{{name}}/v1", Ctx(ws="FY1", vars={"name": "gh-x"}))
    assert got == f"{config.BASE_URL}/FY1/templates/gh-x/v1"


def test_templatize_guards_short_and_missing_vars():
    assert _templatize("a gh step", {"x": "gh"}) == "a gh step"  # <3 chars: too collision-prone
    assert _templatize({"k": ["v"]}, None) == {"k": ["v"]}


def test_elide_is_idempotent():
    messages = _messages()
    _elide_stale_states(messages, keep=1)
    once = [str(m["content"]) for m in messages]
    _elide_stale_states(messages, keep=1)
    assert [str(m["content"]) for m in messages] == once


def test_execute_rejects_hallucinated_tool_names():
    from groundhog.agent.executor import _execute
    from groundhog.browser.actions import Ctx

    # page=None: an unknown tool must bounce before the browser is touched
    result = _execute(None, Ctx(), "triple_click", {"selector": "x"}, [], {})
    assert not result["ok"]
    assert "unknown tool 'triple_click'" in result["text"]


def test_run_executor_escalates_to_smart_after_three_consecutive_failures(monkeypatch):
    """A FAST agent that keeps guessing wrong should get one shot with the SMART
    model, then drop back to FAST once an action lands."""
    from types import SimpleNamespace

    from groundhog.agent import executor
    from groundhog.browser.actions import Ctx

    # keep the browser out of it entirely
    monkeypatch.setattr(executor, "snapshot", lambda page: "- button 'x'")

    models: list[str] = []

    def fake_message(messages, system, tools=None, model=None, max_tokens=2048):
        models.append(model)
        return SimpleNamespace(content=[SimpleNamespace(
            type="tool_use", name="click", id=f"t{len(models)}",
            input={"selector": 'role=button[name="x"]', "description": "click x"})])

    monkeypatch.setattr(executor.client, "message", fake_message)

    # first four actions fail (crossing the ≥3 threshold), then two succeed
    outcomes = iter([False, False, False, False, True, True])
    monkeypatch.setattr(executor, "_execute",
                        lambda page, ctx, action, inp, trace, failed: {"ok": next(outcomes), "text": "ok"})

    page = SimpleNamespace(url="/x")
    executor.run_executor(page, Ctx(), "intent", ["step one"], max_actions=6)

    FAST, SMART = executor.client.FAST, executor.client.SMART
    # cf before each call: 0,1,2,3,4,0 -> escalate only once cf hits 3, drop back after a success
    assert models == [FAST, FAST, FAST, SMART, SMART, FAST]


def test_verify_vars_appends_fresh_suffix_to_every_supplied_value():
    from groundhog.agent.executor import _verify_vars

    # each value gets the same -v{seconds} suffix so a re-run of a create case
    # hits fresh data instead of the name authoring just claimed
    assert _verify_vars({"name": "gh-1", "route": "gh-1"}, 42) == {"name": "gh-1-v42", "route": "gh-1-v42"}
    assert _verify_vars(None, 42) == {}


def test_verify_case_replays_statically_against_fresh_vars(monkeypatch):
    from groundhog.agent import executor
    from groundhog.cases.schema import Case, Step
    from groundhog.runner import replay

    class _FakeSession:
        ws = "FY1"

        def __init__(self, headless=None):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            pass

        def ensure_logged_in(self):
            pass

    monkeypatch.setattr(executor, "Session", _FakeSession)
    seen: dict = {}

    def fake_run_case(case, session, vars=None, heal=True):
        seen["vars"], seen["heal"] = dict(vars or {}), heal
        return replay.RunResult(case=case.name, passed=True)

    monkeypatch.setattr(replay, "run_case", fake_run_case)

    case = Case(name="c", intent="create route {{name}}",
                steps=[Step(id="s1", action="click", selector="button")])
    result = executor.verify_case(case, vars={"name": "gh-1"}, headless=True)

    assert result.passed
    assert seen["vars"]["name"].startswith("gh-1-v")  # fresh-suffixed value
    assert seen["heal"] is False  # verification is a pure static proof, no healer
