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
