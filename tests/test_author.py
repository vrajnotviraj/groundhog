import json
from types import SimpleNamespace

import pytest

from groundhog import config
from groundhog.agent import author
from groundhog.browser.actions import Ctx
from groundhog.cases.schema import Step

INTENTS = {
    "create": "create an SMS template named gh-1 and verify it appears in the templates list",
    "delete": ("delete the template named gh-1 from the templates list, typing its name into the "
               "delete-confirmation dialog, and verify it no longer appears"),
    "search": "search the templates list for gh-1 and verify a matching template is shown",
    "route": ("create an omni-channel route named gh-1, then create an SMS template named gh-1 and save its "
              "SMS message content, then create a notification event named gh-1 of type Transactional, "
              "select the template gh-1 for it, map the rule to the omni-channel route gh-1, and save the event"),
}


# --- pure helpers ----------------------------------------------------------

def test_templatize_reverses_var_values_everywhere():
    trace = [{"action": "fill", "selector": '[placeholder="Enter Name"]', "value": "gh-lr1",
              "fallback_selectors": ['text="gh-lr1"'], "url_after": "/ws/routes/gh-lr1"}]
    out = author._templatize(trace, {"name": "gh-lr1"})
    assert out[0]["value"] == "{{name}}"
    assert out[0]["fallback_selectors"] == ['text="{{name}}"']
    assert out[0]["url_after"] == "/ws/routes/{{name}}"


def test_templatize_guards_short_and_missing_vars():
    assert author._templatize("a gh step", {"x": "gh"}) == "a gh step"  # <3 chars: too collision-prone
    assert author._templatize({"k": ["v"]}, None) == {"k": ["v"]}


def test_embeds_value_rejects_data_but_allows_placeholders():
    assert author.embeds_value('text="gh-1"', "gh-1")
    assert not author.embeds_value('text="{{name}}"', "{{name}}")
    assert not author.embeds_value('role=button[name="Save"]', "gh-1")


def test_verify_vars_appends_fresh_suffix_to_every_supplied_value():
    assert author._verify_vars({"name": "gh-1", "route": "gh-1"}, 42) == {"name": "gh-1-v42", "route": "gh-1-v42"}
    assert author._verify_vars(None, 42) == {}


def test_partial_trace_dump_writes_replayable_json(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path)
    trace = [{"action": "click", "selector": "#save", "description": "save"}]
    path = author._dump_partial("long-flow", trace)
    assert "long-flow-partial-" in path
    assert json.loads((tmp_path / path.rsplit("/", 1)[1]).read_text()) == trace


def test_outcome_clauses_on_the_saved_intents():
    assert author.outcome_clauses(INTENTS["create"]) == ["verify it appears in the templates list"]
    assert author.outcome_clauses(INTENTS["delete"]) == ["verify it no longer appears"]
    assert author.outcome_clauses(INTENTS["search"]) == ["verify a matching template is shown"]
    # no verify clause anywhere: the last clause is the outcome
    assert author.outcome_clauses(INTENTS["route"]) == ["save the event"]
    assert len(author._clauses(INTENTS["route"])) == 7


def test_candidates_cover_vars_and_quoted_literals():
    got = author._candidates("create a template named gh-1 with body 'hello there'", {"name": "gh-1"})
    assert got == [{"value": "gh-1", "source": "goal variable {{name}}"},
                   {"value": "hello there", "source": "quoted in the goal"}]


# --- derive_expects --------------------------------------------------------

def _snap(url, text=""):
    return SimpleNamespace(url=url, text=text)


def _step(action="click", value=None):
    return Step(id="", action=action, selector="#x", value=value)


def test_derive_expects_url_change_drops_the_workspace_segment():
    got = author.derive_expects(_snap("https://x/FYABCDEF/templates"),
                                _snap("https://x/FYABCDEF/templates/gh-1/v1"), _step())
    assert got == author.Expect(kind="url_contains", value="/templates/gh-1/v1")


def test_derive_expects_prefix_navigation_falls_through_to_text():
    got = author.derive_expects(_snap("https://x/FYABCDEF/templates/gh-1/v1", "old"),
                                _snap("https://x/FYABCDEF/templates", "old\nTemplate deleted"), _step())
    assert got == author.Expect(kind="text_visible", value="Template deleted")


def test_derive_expects_query_only_change():
    got = author.derive_expects(_snap("https://x/FYABCDEF/t?range=7"),
                                _snap("https://x/FYABCDEF/t?range=28"), _step())
    assert got == author.Expect(kind="url_contains", value="range=28")


def test_derive_expects_text_diff_skips_typed_value_and_noise():
    before = _snap("https://x/a", "Templates")
    after = _snap("https://x/a", "Templates\n12\n2024-01-01\ngh-1\nTemplate created")
    got = author.derive_expects(before, after, _step(value="gh-1"))
    assert got == author.Expect(kind="text_visible", value="Template created")


def test_derive_expects_is_none_for_fills_and_for_no_diff():
    same = _snap("https://x/a", "Templates")
    assert author.derive_expects(same, same, _step("fill", "gh-1")) is None
    assert author.derive_expects(same, same, _step()) is None
    assert author.derive_expects(None, same, _step()) is None


# --- case assembly ---------------------------------------------------------

def _trace_entry(**kw):
    base = {"action": "click", "selector": "#x", "frame": None, "fallback_selectors": [],
            "value": None, "description": "click button x", "expects": None,
            "url_before": "/a", "url_after": "/a", "fingerprint_before": "sha256:a",
            "page_changed": True, "decision": {}}
    return {**base, **kw}


def test_assembly_drops_silent_no_ops_templatizes_and_emits_assertions():
    trace = [
        _trace_entry(page_changed=False),  # silent no-op click: dropped
        _trace_entry(action="fill", selector='[placeholder="Name"]', value="gh-1",
                     description="fill textbox Name", page_changed=False),
        _trace_entry(page_changed=False, expects={"kind": "text_visible", "value": "gh-1 created"}),
    ]
    case = author._assemble("c", "create {{name}}", trace, ["verify {{name}} appears"],
                            {"name": "gh-1"}, "/:ws/templates", "the list shows gh-1")
    assert [s.id for s in case.steps] == ["s1", "s2"]
    assert case.steps[0].value == "{{name}}"  # templatized back
    assert case.steps[0].page_fingerprint == "sha256:a"
    assert case.steps[1].expects.value == "{{name}} created"
    assert case.start_path == "/:ws/templates"
    assert [(a.assertion, a.mode) for a in case.assertions] == [
        ("text_visible:{{name}}", "deterministic"), ("verify {{name}} appears", "jev")]


def test_assembly_skips_the_var_assertion_when_the_value_is_absent():
    case = author._assemble("c", "i", [_trace_entry()], ["done"], {"name": "gh-1"}, "/", "nothing here")
    assert [a.mode for a in case.assertions] == ["jev"]


# --- the loop --------------------------------------------------------------

def _el(label="Create", role="button", kind="click", node=1, frame=None, value=""):
    return SimpleNamespace(id=f"e{node}", role=role, label=label, value=value, kind=kind,
                           attrs={}, state={}, scope=None, frame=frame, node=node)


def _decision(op, el=None, p=0.9):
    return author.jev.Decision(operation=op, element=el, confidence=0.8, probability=p, latency_ms=10)


class _Page:
    def __init__(self, url="https://x/FYABCDEF/home"):
        self.url = url
        self.fp = "sha256:a"
        self.text = ""
        self.mouse = SimpleNamespace(wheel=lambda dx, dy: None)

    def wait_for_timeout(self, ms):
        pass


def _install(monkeypatch, page, decisions, perform=None, judge=0.9, value="gh-1"):
    """Wire the loop to fakes; returns the list of (history, exclude) seen by choose."""
    seen = []
    it = iter(decisions)

    def choose(snap, goal, history, exclude=frozenset()):
        seen.append((list(history), set(exclude)))
        d = next(it)
        if isinstance(d, Exception):
            raise d
        return d

    monkeypatch.setattr(author, "observe", lambda pg: SimpleNamespace(
        url=pg.url, title="t", text=pg.text, elements=[], omitted=0, fingerprint=pg.fp))
    monkeypatch.setattr(author, "on_picker", lambda pg: False)
    monkeypatch.setattr(author, "settle", lambda pg: None)
    monkeypatch.setattr(author, "selectors_for",
                        lambda pg, el, hints=(): [f'role={el.role}[name="{el.label}"]', f"#{el.id}"])
    monkeypatch.setattr(author, "perform", perform or (lambda pg, step, ctx: None))
    monkeypatch.setattr(author.jev, "choose", choose)
    monkeypatch.setattr(author.jev, "judge", lambda *a, **k: judge)
    monkeypatch.setattr(author.jev, "value", lambda *a, **k: value)
    return seen


def _run(page, trace=None):
    return author.run_executor(page, Ctx(ws="FY1", vars={"name": "gh-1"}), "goal",
                               ["it appears"], [{"value": "gh-1", "source": "goal variable {{name}}"}],
                               10, trace)


def test_done_accepted_at_the_threshold(monkeypatch):
    page = _Page()
    _install(monkeypatch, page, [_decision("DONE")], judge=config.JUDGE_THRESHOLD)
    assert _run(page) == ([], "done")


def test_done_rejected_continues_then_blocks_on_the_second_rejection(monkeypatch):
    page = _Page()
    seen = _install(monkeypatch, page, [_decision("DONE"), _decision("DONE")], judge=0.31)
    trace, reason = _run(page)
    assert (trace, reason) == ([], "blocked")
    assert len(seen) == 2  # the first rejection did not stop the loop
    assert "DONE rejected" in seen[1][0][0]["action"] and "0.31" in seen[1][0][0]["action"]


def test_three_consecutive_failures_block(monkeypatch):
    page = _Page()

    def boom(pg, step, ctx):
        raise RuntimeError("selector resolved 0 elements\nmore noise")

    seen = _install(monkeypatch, page, [_decision("CLICK", _el())] * 5, perform=boom)
    assert _run(page) == ([], "blocked")
    assert len(seen) == 3
    assert seen[1][0][0]["error"] == "selector resolved 0 elements"


def test_two_failures_of_one_node_exclude_it_and_a_path_change_clears_it(monkeypatch):
    page = _Page()
    bad, good = _el("Bad", node=1), _el("Good", node=2)

    def perform(pg, step, ctx):
        if "Bad" in step.description:
            raise RuntimeError("nope")
        pg.url = "https://x/FYABCDEF/templates"
        pg.fp = "sha256:b"

    seen = _install(monkeypatch, page, [_decision("CLICK", bad), _decision("CLICK", bad),
                                        _decision("CLICK", good), _decision("BLOCKED")], perform=perform, judge=0.1)
    trace, reason = _run(page)
    assert reason == "blocked" and len(trace) == 1
    assert seen[2][1] == {(None, 1)}  # excluded after the second failure of the same node
    assert seen[3][1] == set()  # cleared: node ids restart in the new document


def test_press_enter_reuses_the_last_fill_selector(monkeypatch):
    page = _Page()
    field = _el("Search Templates", role="textbox", kind="fill", node=3)
    _install(monkeypatch, page, [_decision("TYPE", field), _decision("PRESS_ENTER"), _decision("DONE")])
    trace, reason = _run(page)
    assert reason == "done"
    assert trace[0]["value"] == "gh-1" and trace[0]["description"] == "fill textbox Search Templates"
    assert trace[1]["action"] == "press" and trace[1]["value"] == "Enter"
    assert trace[1]["selector"] == trace[0]["selector"]
    assert trace[1]["description"] == "press textbox Search Templates"


def test_fill_selectors_never_embed_the_typed_value(monkeypatch):
    page = _Page()
    field = _el("gh-1 option", role="option", kind="fill", node=4)
    _install(monkeypatch, page, [_decision("TYPE", field), _decision("DONE")])
    monkeypatch.setattr(author, "selectors_for",
                        lambda pg, el, hints=(): ['text="gh-1"', '[value="gh-1"]'])
    trace, _ = _run(page)
    # both candidates embed "gh-1"; the last one survives so the step still has a selector
    assert trace[0]["selector"] == '[value="gh-1"]' and trace[0]["fallback_selectors"] == []


def test_type_without_a_candidate_and_without_an_anthropic_key_raises_clearly(monkeypatch):
    page = _Page()
    field = _el("Message", role="textbox", kind="fill", node=5)
    _install(monkeypatch, page, [_decision("TYPE", field)], value=None)
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "")
    with pytest.raises(RuntimeError, match="add it to the intent"):
        _run(page)


def test_a_raising_choose_counts_as_a_failed_iteration(monkeypatch):
    page = _Page()
    seen = _install(monkeypatch, page, [RuntimeError("Jev is unavailable; no action executed.")] * 3)
    assert _run(page) == ([], "blocked")
    assert len(seen) == 3 and seen[2][0][0]["error"].startswith("Jev is unavailable")


def test_fills_never_trip_the_no_change_guard(monkeypatch):
    page = _Page()
    field = _el("Name", role="textbox", kind="fill", node=6)
    _install(monkeypatch, page, [_decision("TYPE", field)] * 5 + [_decision("DONE")])
    trace, reason = _run(page)
    assert reason == "done" and len(trace) == 5  # a form fill changes no roles or labels


def test_three_silent_clicks_block(monkeypatch):
    page = _Page()
    _install(monkeypatch, page, [_decision("CLICK", _el())] * 4)
    trace, reason = _run(page)
    assert reason == "blocked" and len(trace) == 3


def test_budget_exhaustion_is_reported(monkeypatch):
    page = _Page()

    def perform(pg, step, ctx):
        pg.fp += "x"  # every click moves the page, so the no-change guard never fires

    _install(monkeypatch, page, [_decision("CLICK", _el())] * 5, perform=perform)
    trace, reason = author.run_executor(page, Ctx(ws="FY1"), "goal", ["x"], [], 2)
    assert reason == "budget" and len(trace) == 2


def test_wait_is_not_recorded_and_checks_the_goal_first(monkeypatch):
    # An unsure Jev (WAIT) triggers the outcome check: not yet true → wait and go on;
    # true → finish without Jev ever saying DONE.
    page = _Page()
    seen = _install(monkeypatch, page, [_decision("WAIT"), _decision("WAIT")])
    verdicts = iter([0.2, 0.9])
    monkeypatch.setattr(author.jev, "judge", lambda *a, **k: next(verdicts))
    trace, reason = _run(page)
    assert (trace, reason) == ([], "done")
    assert [h["op"] for h in seen[1][0]] == ["WAIT"]


def test_a_raising_judge_counts_as_a_failed_iteration(monkeypatch):
    page = _Page()
    seen = _install(monkeypatch, page, [_decision("DONE")] * 3)

    def boom(*a, **k):
        raise RuntimeError("Jev returned HTTP 500: upstream")

    monkeypatch.setattr(author.jev, "judge", boom)
    assert _run(page) == ([], "blocked")
    assert len(seen) == 3 and seen[2][0][0]["error"].startswith("Jev returned HTTP 500")


def test_an_unverifiable_selector_is_a_failed_iteration_not_a_saved_step(monkeypatch):
    page = _Page()
    seen = _install(monkeypatch, page, [_decision("CLICK", _el())] * 3)

    def boom(pg, el, hints=()):
        raise RuntimeError("no verifiable selector for [button Save]")

    monkeypatch.setattr(author, "selectors_for", boom)
    assert _run(page) == ([], "blocked")
    assert seen[2][0][0]["error"].startswith("no verifiable selector")


def test_a_raising_loop_keeps_the_actions_recorded_so_far(monkeypatch):
    page = _Page()
    field = _el("Message", role="textbox", kind="fill", node=7)
    _install(monkeypatch, page, [_decision("CLICK", _el()), _decision("TYPE", field)], value=None)
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "")
    trace = []
    with pytest.raises(RuntimeError, match="add it to the intent"):
        _run(page, trace)
    assert len(trace) == 1 and trace[0]["description"] == "click button Create"


def test_observe_changed_waits_for_a_late_render(monkeypatch):
    # A drawer that renders a beat after the click must not be read as a no-op.
    from types import SimpleNamespace

    snaps = iter([("same", "/a"), ("same", "/a"), ("drawer", "/a")])
    monkeypatch.setattr(author, "observe",
                        lambda page: SimpleNamespace(**dict(zip(("fingerprint", "url"), next(snaps)))))
    page = SimpleNamespace(wait_for_timeout=lambda ms: None)
    after = author._observe_changed(page, SimpleNamespace(fingerprint="same", url="/a"), timeout_ms=5000)
    assert after.fingerprint == "drawer"


def test_new_line_skips_relative_times_and_numbers():
    assert author._new_line("", "27s ago\n3 minutes ago\njust now\n12\nAccounts", None) == "Accounts"


def test_three_waits_with_no_change_end_the_run(monkeypatch):
    page = _Page()
    _install(monkeypatch, page, [_decision("WAIT")] * 4, judge=0.1)
    assert _run(page) == ([], "blocked")


def test_decision_line_shows_runners_up_only_when_hesitant():
    sure = SimpleNamespace(operation="CLICK", element=_el(), probability=0.95, latency_ms=10, detail="ops CLICK=0.95")
    unsure = SimpleNamespace(operation="WAIT", element=None, probability=0.4, latency_ms=10,
                             detail="ops WAIT=0.40 CLICK=0.35")
    assert "ops" not in author._decision_line(sure) and "CLICK=0.35" in author._decision_line(unsure)


def test_var_targeting_click_is_kept_even_when_it_changed_nothing():
    trace = [{"action": "click", "selector": 'role=button[name*="gh-1"]', "frame": None, "fallback_selectors": [],
              "value": None, "description": "click button G gh-1", "expects": None, "url_before": "u",
              "url_after": "u", "fingerprint_before": "f", "page_changed": False, "decision": {}},
             {"action": "click", "selector": 'role=button[name="Noise"]', "frame": None, "fallback_selectors": [],
              "value": None, "description": "click button Noise", "expects": None, "url_before": "u",
              "url_after": "u", "fingerprint_before": "f", "page_changed": False, "decision": {}}]
    case = author._assemble("c", "i", trace, [], {"name": "gh-1"}, "/:ws/x", "")
    assert [s.selector for s in case.steps] == ['role=button[name*="{{name}}"]']


def test_a_lone_empty_field_is_typed_into_when_jev_rejects_every_target(monkeypatch):
    page = _Page()
    field = _el("Enter integration account name", role="textbox", kind="fill", node=7)
    none = SimpleNamespace(operation="NONE", element=None, confidence=0.5, probability=0.8, latency_ms=5,
                           detail="", wanted="TYPE")
    _install(monkeypatch, page, [none, _decision("DONE")])
    verdicts = iter([0.1, 0.9])  # not done before the fill, done after it
    monkeypatch.setattr(author.jev, "judge", lambda *a, **k: next(verdicts))
    monkeypatch.setattr(author, "observe", lambda pg: SimpleNamespace(
        url=pg.url, title="t", text=pg.text, elements=[field], omitted=0, fingerprint=pg.fp))
    trace, reason = _run(page)
    assert reason == "done" and [t["action"] for t in trace] == ["fill"] and trace[0]["value"] == "gh-1"
