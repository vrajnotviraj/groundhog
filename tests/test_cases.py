import re

import pytest
from pydantic import ValidationError

from groundhog import db
from groundhog.cases import store
from groundhog.cases.schema import NAME, Assertion, Case, Expect, Step


def _case():
    return Case(
        name="roundtrip",
        intent="create a template named {{name}}",
        start_path="/:ws/templates",
        steps=[Step(id="s1", action="click", selector='role=button[name="Create"]',
                    fallback_selectors=['[data-testid="create"]'],
                    expects=Expect(kind="text_visible", value="Template Name"),
                    page_fingerprint="sha256:abc")],
        assertions=[Assertion(assertion="url_contains:/templates", mode="deterministic"),
                    Assertion(assertion="the template appears", mode="jev")],
    )


def test_case_roundtrip():
    case = _case()
    store.save(case)
    assert store.load("roundtrip") == case
    assert store.list_cases() == [case]
    assert store.delete("roundtrip") and store.list_cases() == []
    with pytest.raises(KeyError):
        store.load("roundtrip")


def test_assertion_defaults_to_jev():
    assert Assertion(assertion="the template appears").mode == "jev"


def test_removed_actions_are_rejected():
    for action in ("drag", "select", "wait_for", "fill_secret"):
        with pytest.raises(ValidationError):
            Step(action=action)


def test_old_documents_load_and_drop_the_removed_step_keys():
    db.cases().insert_one({"_id": "old", "name": "old", "intent": "x", "assertions": [],
                           "steps": [{"id": "s1", "action": "fill", "selector": "#q", "value": "gh-1",
                                      "field": None, "to_selector": None}]})
    step = store.load("old").steps[0]
    assert step.selector == "#q"
    assert not hasattr(step, "to_selector") and not hasattr(step, "field")


def test_render_substitutes_only_known_vars():
    assert store.render("create {{name}} now", {"name": "gh-1"}) == "create gh-1 now"
    assert store.render("create {{name}} now", {}) == "create {{name}} now"
    assert store.render("no vars", None) == "no vars"
    # A literal selector passes through untouched; one with a var substitutes, so a step
    # can target something the test itself created.
    assert store.render('a[href*="/templates/gh-1"]', {"name": "gh-1"}) == 'a[href*="/templates/gh-1"]'
    assert store.render('a[href*="/templates/{{name}}"]', {"name": "gh-1"}) == 'a[href*="/templates/gh-1"]'


def test_missing_vars_lists_unsupplied_placeholders():
    case = _case()  # intent and a fallback selector use {{name}}
    assert store.missing_vars(case, None) == ["name"]
    assert store.missing_vars(case, {"name": "gh-1"}) == []
    assert store.missing_vars(case, {"name": ""}) == ["name"]


def test_derive_name_is_kebab_case_and_at_most_64_characters():
    assert store.derive_name("Create an SMS template named X") == "create-an-sms-template-named"
    long = store.derive_name(" ".join(["internationalization"] * 5))
    assert re.match(NAME, long)
