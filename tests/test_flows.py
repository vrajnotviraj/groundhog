from groundhog.cases import store
from groundhog.cases.schema import Case, Flow, FlowCase, Step
from groundhog.runner import flow as flow_runner
from groundhog.runner.flow import case_vars, run_flow, shared_vars
from groundhog.runner.replay import RunResult


def _flow():
    return Flow(
        name="template-lifecycle",
        intent="create a template, verify it in search, then delete it",
        vars={"name": "gh-{{stamp}}"},
        chain=["create-template", {"case": "search-templates", "vars": {"query": "{{name}}"}}],
        cleanup=["delete-template"],
    )


def test_flow_chain_entries_coerce_from_plain_strings():
    flow = _flow()
    assert flow.chain[0] == FlowCase(case="create-template")
    assert flow.chain[1] == FlowCase(case="search-templates", vars={"query": "{{name}}"})
    assert flow.cleanup == [FlowCase(case="delete-template")]


def test_flow_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "FLOWS_DIR", tmp_path)
    flow = _flow()
    store.save_flow(flow)
    assert store.load_flow("template-lifecycle") == flow
    assert store.list_flows() == [flow]


def test_shared_vars_render_stamp_and_cli_wins():
    flow = _flow()
    merged = shared_vars(flow, {"extra": "1"})
    assert merged["extra"] == "1"
    # {{stamp}} renders to a per-run timestamp so created data never collides
    assert merged["name"].startswith("gh-") and "{{" not in merged["name"]
    # an explicit --var beats the flow default
    assert shared_vars(flow, {"name": "gh-fixed"})["name"] == "gh-fixed"


def test_shared_vars_resolve_references_between_vars():
    flow = Flow(name="f", vars={"name": "gh-{{stamp}}", "query": "{{name}}"},
                chain=["create-template"])
    merged = shared_vars(flow)
    assert merged["query"] == merged["name"] and merged["name"].startswith("gh-")
    # a --var override propagates into vars that reference it
    assert shared_vars(flow, {"name": "gh-x"})["query"] == "gh-x"


def test_case_vars_render_against_shared_and_win():
    shared = {"name": "gh-1", "query": "unused"}
    fc = FlowCase(case="search-templates", vars={"query": "{{name}}"})
    assert case_vars(shared, fc) == {"name": "gh-1", "query": "gh-1"}
    assert case_vars(shared, FlowCase(case="create-template")) == shared


def _stub_cases(tmp_path, monkeypatch, names):
    monkeypatch.setattr(store, "CASES_DIR", tmp_path)
    for n in names:
        store.save(Case(name=n, intent=n, steps=[Step(id="s1", action="click", selector="button")]))


def _fake_run_case(outcomes: dict[str, bool], calls: list):
    def fake(case, session, vars=None, heal=True):
        calls.append((case.name, dict(vars or {})))
        return RunResult(case=case.name, passed=outcomes[case.name])

    return fake


def test_run_flow_passes_and_shares_vars(tmp_path, monkeypatch):
    _stub_cases(tmp_path, monkeypatch, ["create-template", "search-templates", "delete-template"])
    calls = []
    monkeypatch.setattr(flow_runner, "run_case", _fake_run_case(
        {"create-template": True, "search-templates": True, "delete-template": True}, calls))
    result = run_flow(_flow(), session=None, vars={"name": "gh-1"})
    assert result.passed
    assert [c.name for c in result.runs] == ["create-template", "search-templates", "delete-template"]
    assert [(cr.stage, cr.result.passed) for cr in result.runs] == [
        ("chain", True), ("chain", True), ("cleanup", True)]
    # every case saw the shared name; search-templates derived its query from it
    assert all(v["name"] == "gh-1" for _, v in calls)
    assert calls[1][1]["query"] == "gh-1"


def test_run_flow_skips_rest_of_chain_but_always_runs_cleanup(tmp_path, monkeypatch):
    _stub_cases(tmp_path, monkeypatch, ["create-template", "search-templates", "delete-template"])
    calls = []
    monkeypatch.setattr(flow_runner, "run_case", _fake_run_case(
        {"create-template": False, "search-templates": True, "delete-template": True}, calls))
    result = run_flow(_flow(), session=None)
    assert not result.passed
    ran = [name for name, _ in calls]
    assert ran == ["create-template", "delete-template"]  # search skipped, cleanup still ran
    skipped = [cr for cr in result.runs if cr.result is None]
    assert [cr.name for cr in skipped] == ["search-templates"]


def test_run_flow_fails_when_cleanup_fails(tmp_path, monkeypatch):
    _stub_cases(tmp_path, monkeypatch, ["create-template", "search-templates", "delete-template"])
    monkeypatch.setattr(flow_runner, "run_case", _fake_run_case(
        {"create-template": True, "search-templates": True, "delete-template": False}, []))
    # leftover data is a real failure, not a footnote
    assert not run_flow(_flow(), session=None).passed


class _FakeSession:
    def __init__(self, headless=None):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def ensure_logged_in(self):
        pass


def _composer(monkeypatch, draft, run_outcomes=None, authored=None):
    from groundhog.agent import composer

    monkeypatch.setattr(composer.client, "parse", lambda **kw: draft)
    monkeypatch.setattr(composer, "Session", _FakeSession)
    calls = []
    monkeypatch.setattr(composer, "run_case", lambda case, session, vars=None, heal=True: (
        calls.append(("replay", case.name, dict(vars or {}))),
        RunResult(case=case.name, passed=(run_outcomes or {}).get(case.name, True)))[1])

    def fake_author(intent, name=None, vars=None, session=None):
        assert session is not None  # authoring must reuse the flow's session
        calls.append(("author", name, dict(vars or {})))
        if authored is not None:
            authored.append(name)

    import groundhog.agent.executor as executor
    monkeypatch.setattr(executor, "author_case", fake_author)
    return composer, calls


def test_compose_flow_rejects_unknown_case_references(tmp_path, monkeypatch):
    import pytest

    from groundhog.agent import composer

    _stub_cases(tmp_path, monkeypatch, ["create-template"])
    draft = composer.FlowDraft(name="f", chain=[
        composer.DraftCase(reuse="create-template"), composer.DraftCase(reuse="no-such-case")])
    monkeypatch.setattr(composer.client, "parse", lambda **kw: draft)
    with pytest.raises(ValueError, match="no-such-case"):
        composer.compose_flow("create a template then vanish")


def test_decompose_converts_verbatim_duplicate_intents_to_reuse_and_requires_vars(tmp_path, monkeypatch):
    import pytest

    from groundhog.agent import composer

    monkeypatch.setattr(store, "CASES_DIR", tmp_path)
    store.save(Case(name="create-template", intent="create a template named {{name}}",
                    steps=[Step(id="s1", action="click", selector="button")]))
    draft = composer.FlowDraft(
        name="f", vars=[composer.DraftVar(var="name", value="gh-{{stamp}}")],
        chain=[composer.DraftCase(name="create-template-2", intent="create a template named {{name}}")])
    monkeypatch.setattr(composer.client, "parse", lambda **kw: draft)
    out = composer._decompose("create a template")
    assert out.chain[0].reuse == "create-template"  # duplicate intent folded into reuse

    bare = composer.FlowDraft(name="f", chain=[
        composer.DraftCase(name="c", intent="delete the template named {{name}}")])
    monkeypatch.setattr(composer.client, "parse", lambda **kw: bare)
    with pytest.raises(ValueError, match="without defaults.*name"):
        composer._decompose("delete a template")


def test_compose_flow_recovers_when_new_case_lands_in_reuse_field(tmp_path, monkeypatch):
    from groundhog.agent.composer import DraftCase, DraftVar, FlowDraft

    _stub_cases(tmp_path, monkeypatch, ["create-template"])
    monkeypatch.setattr(store, "FLOWS_DIR", tmp_path)
    draft = FlowDraft(name="f", vars=[DraftVar(var="name", value="gh-{{stamp}}")], chain=[
        DraftCase(reuse="create-template"),
        DraftCase(reuse="delete-template-v2", intent="delete the template named {{name}}")])
    composer, calls = _composer(monkeypatch, draft)
    flow = composer.compose_flow("create then delete")
    assert [(kind, name) for kind, name, _ in calls] == [
        ("replay", "create-template"), ("author", "delete-template-v2")]
    assert [fc.case for fc in flow.chain] == ["create-template", "delete-template-v2"]


def test_compose_flow_replays_existing_and_authors_missing_in_order(tmp_path, monkeypatch):
    from groundhog.agent.composer import DraftCase, DraftVar, FlowDraft

    _stub_cases(tmp_path, monkeypatch, ["create-template", "delete-template"])
    monkeypatch.setattr(store, "FLOWS_DIR", tmp_path)
    draft = FlowDraft(name="template-event", vars=[DraftVar(var="name", value="gh-{{stamp}}")],
                      chain=[DraftCase(reuse="create-template"),
                             DraftCase(name="create-event", intent="create an event using template {{name}}")],
                      cleanup=[DraftCase(name="delete-event", intent="delete the event named {{name}}"),
                               DraftCase(reuse="delete-template")])
    composer, calls = _composer(monkeypatch, draft)
    flow = composer.compose_flow("create a template, an event on it, then clean up")
    assert [(kind, name) for kind, name, _ in calls] == [
        ("replay", "create-template"), ("author", "create-event"),
        ("author", "delete-event"), ("replay", "delete-template")]
    # every step of the pass saw the same concrete shared vars
    assert len({tuple(sorted(v.items())) for _, _, v in calls}) == 1
    assert "{{" not in calls[0][2]["name"]
    assert [fc.case for fc in flow.chain] == ["create-template", "create-event"]
    assert [fc.case for fc in flow.cleanup] == ["delete-event", "delete-template"]
    assert store.load_flow("template-event") == flow


def test_compose_flow_failure_runs_existing_cleanup_and_keeps_flow_unsaved(tmp_path, monkeypatch):
    import pytest

    from groundhog.agent.composer import DraftCase, DraftVar, FlowDraft

    _stub_cases(tmp_path, monkeypatch, ["create-template", "delete-template"])
    monkeypatch.setattr(store, "FLOWS_DIR", tmp_path)
    draft = FlowDraft(name="template-event",
                      chain=[DraftCase(reuse="create-template")],
                      cleanup=[DraftCase(name="delete-event", intent="delete the event"),
                               DraftCase(reuse="delete-template")])
    composer, calls = _composer(monkeypatch, draft, run_outcomes={"create-template": False})
    with pytest.raises(RuntimeError, match="flow not saved"):
        composer.compose_flow("doomed")
    # existing cleanup still replayed; the un-authored delete-event was not
    assert [(kind, name) for kind, name, _ in calls] == [
        ("replay", "create-template"), ("replay", "delete-template")]
    assert not (tmp_path / "template-event.json").exists()
