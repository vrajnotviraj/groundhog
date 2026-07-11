from groundhog.agent import optimizer
from groundhog.agent.optimizer import OptStep, OptimizedCase, optimize


def _traced(action, selector, fp, **extra):
    return {"action": action, "selector": selector, "fingerprint_before": fp, **extra}


def test_reused_selector_gets_its_own_occurrences_fingerprint(monkeypatch):
    """route-template-event.json-style trace: the same selector (e.g. the
    'Create' button, or a search box) is exercised twice at two different
    points in the page, each with its own authoring-time fingerprint. Each
    optimized step must carry the fingerprint of *its* occurrence, not the
    last one seen in the trace."""
    trace = [
        _traced("click", 'button:has-text("Create")', "fp-create-1"),
        _traced("fill", '[placeholder="Enter Name"]', "fp-name-1", value="gh-1"),
        _traced("click", 'button:has-text("Submit")', "fp-submit-1"),
        _traced("click", 'button:has-text("Create")', "fp-create-2"),
        _traced("fill", '[placeholder="Enter Name"]', "fp-name-2", value="gh-2"),
        _traced("click", 'button:has-text("Submit")', "fp-submit-2"),
    ]
    draft = OptimizedCase(
        start_path="/x",
        steps=[
            OptStep(action="click", selector='button:has-text("Create")'),
            OptStep(action="fill", selector='[placeholder="Enter Name"]', value="gh-1"),
            OptStep(action="click", selector='button:has-text("Submit")'),
            OptStep(action="click", selector='button:has-text("Create")'),
            OptStep(action="fill", selector='[placeholder="Enter Name"]', value="gh-2"),
            OptStep(action="click", selector='button:has-text("Submit")'),
        ],
        assertions=[],
    )
    monkeypatch.setattr(optimizer.client, "parse", lambda **kw: draft)

    case = optimize("n", "intent", trace, {})

    assert [s.page_fingerprint for s in case.steps] == [
        "fp-create-1", "fp-name-1", "fp-submit-1",
        "fp-create-2", "fp-name-2", "fp-submit-2",
    ]


def test_step_with_no_matching_trace_entry_gets_no_fingerprint(monkeypatch):
    """The optimizer can drop or invent steps; a step whose selector never
    shows up (forward of where we've already matched) must not inherit a
    stray fingerprint from an unrelated trace entry."""
    trace = [_traced("click", 'button:has-text("Create")', "fp-create-1")]
    draft = OptimizedCase(
        start_path="/x",
        steps=[OptStep(action="click", selector='button:has-text("Nope")')],
        assertions=[],
    )
    monkeypatch.setattr(optimizer.client, "parse", lambda **kw: draft)

    case = optimize("n", "intent", trace, {})

    assert case.steps[0].page_fingerprint is None
