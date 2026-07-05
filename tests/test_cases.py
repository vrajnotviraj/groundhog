from groundhog.cases import store
from groundhog.cases.schema import Assertion, Case, Expect, Step


def _case():
    return Case(
        name="roundtrip",
        intent="create a template named {{name}}",
        start_path="/:ws/templates",
        steps=[Step(id="s1", action="click", selector='role=button[name="Create"]',
                    fallback_selectors=['text="Create"'],
                    expects=Expect(kind="text_visible", value="Template Name"),
                    page_fingerprint="sha256:abc")],
        assertions=[Assertion(assertion="url_contains:/templates", mode="deterministic"),
                    Assertion(assertion="the template appears", mode="llm")],
    )


def test_case_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "CASES_DIR", tmp_path)
    case = _case()
    store.save(case)
    loaded = store.load("roundtrip")
    assert loaded == case
    assert store.list_cases() == [case]


def test_drag_step_roundtrip_keeps_to_selector(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "CASES_DIR", tmp_path)
    to_sel = '.react-flow__node:has-text("SMS") .react-flow__handle.target'
    case = Case(name="drag-roundtrip", intent="connect trigger to SMS",
                steps=[Step(id="s1", action="drag",
                            selector='.react-flow__node:has-text("Trigger") .react-flow__handle.source',
                            to_selector=to_sel)])
    store.save(case)
    loaded = store.load("drag-roundtrip")
    assert loaded == case
    assert loaded.steps[0].to_selector == to_sel
    # A literal to_selector passes through render untouched at replay time,
    # while a {{var}} inside one substitutes — same contract as selector, so a
    # drag can target a node the test itself created.
    assert store.render(to_sel, {"name": "gh-1"}) == to_sel
    assert store.render('.react-flow__node:has-text("{{name}}")', {"name": "gh-1"}) \
        == '.react-flow__node:has-text("gh-1")'


def test_render_substitutes_only_known_vars():
    assert store.render("create {{name}} now", {"name": "gh-1"}) == "create gh-1 now"
    assert store.render("create {{name}} now", {}) == "create {{name}} now"
    assert store.render("no vars", None) == "no vars"
