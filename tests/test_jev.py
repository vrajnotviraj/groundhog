from types import SimpleNamespace

import httpx
import pytest

from groundhog import config, jev


def _el(eid, role="button", label="Create", kind="click", value="", state=None, frame=None, node=None):
    return SimpleNamespace(id=eid, role=role, label=label, value=value, kind=kind, state=state or {},
                           frame=frame, node=node if node is not None else int(eid[-1]), attrs={})


def _snap(elements):
    return SimpleNamespace(url="https://app.example.com/FYABCDEF/templates", title="Templates", text="page text",
                           elements=elements)


def _choice(choice, probabilities, confidence=0.9):
    return {"type": "choice", "choice": choice, "probabilities": probabilities, "confidence": confidence}


def _answers(operation=None, **rest):
    """A reply whose operation answer is built from whatever operations were actually offered."""
    def reply(body):
        answers = dict(rest)
        if operation:
            offered = body["questions"]["operation"]["criteria"]
            answers["operation"] = _choice(operation, {k: float(k == operation) for k in offered})
        return {"model": "jev-1.13.0", "usage": {"input_tokens": 100}, "answers": answers}
    return reply


@pytest.fixture
def post(monkeypatch):
    def fake(body):
        fake.bodies.append(body)
        return fake.reply(body) if callable(fake.reply) else fake.reply
    fake.bodies = []
    fake.reply = {"model": "jev-1.13.0", "answers": {}, "usage": {"input_tokens": 100}}
    monkeypatch.setattr(jev, "_post", fake)
    monkeypatch.setattr(jev, "_USAGE", {"calls": 0, "input_tokens": 0, "latency_ms": 0, "model": None})
    monkeypatch.setattr(config, "TYPESAFE_API_KEY", "test-key")
    return fake


# --- validation -------------------------------------------------------------

@pytest.mark.parametrize("answer", [
    {},
    _choice("e9", {"e1": 1.0}),                                  # choice not offered
    _choice("e1", {"e1": 0.6, "e2": 0.4}),                       # probabilities keyed by unknown ids
    _choice("e1", {"e1": 1.0, "none": 0.0, "e2": 0.0}),          # extra key
    _choice("e1", {"e1": 1.5, "none": -0.5}),                    # out of range
    _choice("e1", {"e1": float("nan"), "none": 1.0}),            # not finite
    _choice("e1", {"e1": 0.4, "none": 0.2}),                     # does not sum to 1
    _choice("e1", {"e1": 0.3, "none": 0.7}),                     # not the argmax
    {"choice": "e1", "probabilities": {"e1": 1.0, "none": 0.0}},  # no confidence
    _choice("e1", {"e1": 1.0, "none": 0.0}, confidence="high"),  # confidence not a number
])
def test_invalid_choice_rejected(answer):
    with pytest.raises(ValueError, match="Invalid Jev response"):
        jev._validate_choice(answer, {"e1": "x", "none": "y"})


def test_valid_choice_passes():
    answer = _choice("e1", {"e1": 0.8, "none": 0.2})
    assert jev._validate_choice(answer, {"e1": "x", "none": "y"}) is answer


@pytest.mark.parametrize("answer", [
    {}, {"type": "noul"}, {"type": "choice", "noul": 0.5}, {"type": "noul", "noul": 1.4},
    {"type": "noul", "noul": float("inf")}, {"type": "noul", "noul": "yes"},
])
def test_invalid_noul_rejected(answer):
    with pytest.raises(ValueError, match="Invalid Jev response"):
        jev._validate_noul(answer)


def test_valid_noul_returns_probability():
    assert jev._validate_noul({"type": "noul", "noul": 0.82}) == pytest.approx(0.82)


# --- choose -----------------------------------------------------------------

def test_choose_sends_one_body_with_operation_and_heads(post):
    snap = _snap([_el("e1"), _el("e2", role="textbox", label="Name", kind="fill", value="old")])
    post.reply = _answers("CLICK", target=_choice("e1", {"e1": 0.93, "e2": 0.05, "none": 0.02}))
    decision = jev.choose(snap, "create a template", [])
    body = post.bodies[0]
    assert len(post.bodies) == 1
    assert set(body["questions"]) == {"operation", "target", "type_target"}
    assert set(body["questions"]["target"]["criteria"]) == {"e1", "e2", "none"}
    assert set(body["questions"]["type_target"]["criteria"]) == {"e2", "none"}
    assert body["questions"]["target"]["criteria"]["e1"] == {"element": "[e1] button · Create"}
    assert body["questions"]["operation"]["instructions"]["rules"] == jev.NEXT_ACTION
    assert body["questions"]["target"]["instructions"]["rules"] == [jev.NEXT_ACTION, jev.TARGET]
    # Empty value/state/frame are omitted from the state rows.
    assert body["state"]["elements"] == [{"index": "e1", "role": "button", "label": "Create"},
                                         {"index": "e2", "role": "textbox", "label": "Name", "value": "old"}]
    assert decision.operation == "CLICK"
    assert decision.element.id == "e1"
    assert decision.probability == pytest.approx(0.93)
    assert decision.confidence == pytest.approx(0.9)
    assert decision.latency_ms >= 0


def test_choose_offers_no_type_target_without_fill_elements(post):
    post.reply = _answers("WAIT")
    decision = jev.choose(_snap([_el("e1")]), "goal", [])
    assert "TYPE" not in post.bodies[0]["questions"]["operation"]["criteria"]
    assert "type_target" not in post.bodies[0]["questions"]
    assert decision.operation == "WAIT" and decision.element is None
    assert decision.probability == pytest.approx(1.0)


def test_choose_consumes_only_the_head_of_the_chosen_operation(post):
    snap = _snap([_el("e1"), _el("e2", role="textbox", label="Name", kind="fill")])
    post.reply = _answers("TYPE", target={"garbage": True},
                          type_target=_choice("e2", {"e2": 0.88, "none": 0.12}))
    decision = jev.choose(snap, "goal", [])
    assert decision.operation == "TYPE" and decision.element.id == "e2"
    assert decision.probability == pytest.approx(0.88)


def test_choose_omits_excluded_nodes(post):
    snap = _snap([_el("e1", node=1), _el("e2", label="Delete", node=2, frame='iframe[name="f"]')])
    post.reply = _answers("CLICK", target=_choice("e1", {"e1": 0.9, "none": 0.1}))
    jev.choose(snap, "goal", [], exclude={('iframe[name="f"]', 2)})
    assert set(post.bodies[0]["questions"]["target"]["criteria"]) == {"e1", "none"}
    assert [row["index"] for row in post.bodies[0]["state"]["elements"]] == ["e1"]


def test_choose_returns_none_when_the_head_answers_none(post):
    post.reply = _answers("CLICK", target=_choice("none", {"e1": 0.2, "none": 0.8}))
    decision = jev.choose(_snap([_el("e1")]), "goal", [])
    assert decision.operation == "NONE" and decision.element is None
    assert decision.probability == pytest.approx(0.8)


def test_choose_rejects_a_malformed_head_it_uses(post):
    post.reply = _answers("CLICK", target={"garbage": True})
    with pytest.raises(ValueError, match="Invalid Jev response"):
        jev.choose(_snap([_el("e1")]), "goal", [])


def _ops(post):
    return set(post.bodies[-1]["questions"]["operation"]["criteria"])


@pytest.mark.parametrize("history,offered", [
    ([], False),
    ([{"op": "CLICK", "error": None}], False),
    ([{"op": "TYPE", "error": None}], True),
    ([{"op": "TYPE", "error": None}, {"op": "CLICK", "error": None}], False),
    # The click failed, so the most recent successful entry is still the TYPE.
    ([{"op": "TYPE", "error": None}, {"op": "CLICK", "error": "boom"}], True),
])
def test_press_enter_offered_only_after_a_successful_type(post, history, offered):
    post.reply = _answers("BLOCKED")
    jev.choose(_snap([_el("e1")]), "goal", history)
    assert ("PRESS_ENTER" in _ops(post)) is offered


def test_no_scroll_operations_are_offered(post):
    post.reply = _answers("BLOCKED")
    jev.choose(_snap([_el("e1")]), "goal", [])
    assert not [o for o in _ops(post) if o.startswith("SCROLL")]


def test_choose_passes_the_last_ten_history_entries_untouched(post):
    history = [{"op": "CLICK", "action": f"click {i}", "value": None, "page_changed": True, "error": None}
               for i in range(12)]
    post.reply = _answers("BLOCKED")
    jev.choose(_snap([_el("e1")]), "goal", history)
    assert post.bodies[0]["state"]["recent_actions"] == history[-10:]


# --- value / judge / heal ---------------------------------------------------

def test_value_maps_the_chosen_index_to_its_candidate(post):
    candidates = [{"value": "gh-1", "source": "goal variable {{name}}"},
                  {"value": "hello", "source": "quoted in the goal"}]
    post.reply = _answers(value=_choice("2", {"1": 0.2, "2": 0.7, "compose": 0.1}))
    field = _el("e1", role="textbox", label="Name", kind="fill")
    assert jev.value(_snap([field]), "goal", field, candidates, []) == "hello"
    assert set(post.bodies[0]["questions"]["value"]["criteria"]) == {"1", "2", "compose"}
    assert post.bodies[0]["state"]["field"]["label"] == "Name"
    assert "url" not in post.bodies[0]["state"]["page"]


def test_value_returns_none_for_compose(post):
    post.reply = _answers(value=_choice("compose", {"1": 0.1, "compose": 0.9}))
    field = _el("e1", role="textbox", label="Body", kind="fill")
    assert jev.value(_snap([field]), "goal", field, [{"value": "gh-1", "source": "x"}], []) is None


def test_judge_returns_the_noul(post):
    post.reply = _answers(outcome={"type": "noul", "noul": 0.91})
    assert jev.judge(_snap([_el("e1")]), "the template appears", "goal") == pytest.approx(0.91)
    assert post.bodies[0]["questions"]["outcome"]["type"] == "noul"
    assert post.bodies[0]["state"]["elements"] == ["button · Create"]


def test_heal_returns_none_and_its_probability(post):
    post.reply = _answers(heal=_choice("none", {"e1": 0.3, "none": 0.7}))
    step = SimpleNamespace(action="click", description="click button Delete", value=None, selector="#gone")
    element, probability = jev.heal(_snap([_el("e1")]), step)
    assert element is None and probability == pytest.approx(0.7)
    assert post.bodies[0]["questions"]["heal"]["instructions"]["step"]["original_selector"] == "#gone"


def test_heal_offers_only_fill_elements_for_a_fill_step(post):
    snap = _snap([_el("e1"), _el("e2", role="textbox", label="Name", kind="fill")])
    post.reply = _answers(heal=_choice("e2", {"e2": 0.8, "none": 0.2}))
    step = SimpleNamespace(action="fill", description="fill textbox Name", value="gh-1", selector="#gone")
    element, probability = jev.heal(snap, step)
    assert set(post.bodies[0]["questions"]["heal"]["criteria"]) == {"e2", "none"}
    assert element.id == "e2" and probability == pytest.approx(0.8)


# --- transport --------------------------------------------------------------

def test_usage_counter_accumulates_and_records_the_model(post):
    assert jev.usage_snapshot() is None
    post.reply = _answers(outcome={"type": "noul", "noul": 0.5})
    jev.judge(_snap([]), "x", "goal")
    jev.judge(_snap([]), "x", "goal")
    usage = jev.usage_snapshot()
    assert usage["calls"] == 2 and usage["input_tokens"] == 200 and usage["model"] == "jev-1.13.0"
    assert usage["latency_ms"] >= 0


def test_missing_key_raises_before_any_request(monkeypatch):
    monkeypatch.setattr(config, "TYPESAFE_API_KEY", "")
    monkeypatch.setattr(httpx, "post", lambda *a, **k: pytest.fail("no request may be made"))
    monkeypatch.setattr(httpx, "get", lambda *a, **k: pytest.fail("no request may be made"))
    with pytest.raises(RuntimeError, match="TYPESAFE_API_KEY is not set"):
        jev._post({})
    with pytest.raises(RuntimeError, match="TYPESAFE_API_KEY is not set"):
        jev.ping()


def _response(status, payload=None, text=""):
    return SimpleNamespace(status_code=status, is_error=status >= 400, text=text, json=lambda: payload or {})


def test_ping_returns_the_first_model_and_a_latency(monkeypatch):
    monkeypatch.setattr(config, "TYPESAFE_API_KEY", "test-key")
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _response(200, {"models": [{"name": "jev-latest"}]}))
    result = jev.ping()
    assert result["model"] == "jev-latest" and isinstance(result["latency_ms"], int)


def test_ping_reports_a_rejected_key(monkeypatch):
    monkeypatch.setattr(config, "TYPESAFE_API_KEY", "bad")
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _response(401, {"detail": {"message": "nope"}}))
    with pytest.raises(RuntimeError, match="TYPESAFE_API_KEY was rejected"):
        jev.ping()


def test_post_retries_on_429_then_succeeds(monkeypatch):
    monkeypatch.setattr(config, "TYPESAFE_API_KEY", "test-key")
    monkeypatch.setattr(jev.time, "sleep", lambda s: None)
    responses = [_response(429), _response(200, {"answers": {}})]
    monkeypatch.setattr(httpx, "post", lambda *a, **k: responses.pop(0))
    assert jev._post({}) == {"answers": {}}
    assert not responses


def test_post_raises_with_the_status_and_body(monkeypatch):
    monkeypatch.setattr(config, "TYPESAFE_API_KEY", "test-key")
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _response(400, text="bad question"))
    with pytest.raises(RuntimeError, match="HTTP 400: bad question"):
        jev._post({})


def test_network_failure_becomes_a_runtime_error(monkeypatch):
    monkeypatch.setattr(config, "TYPESAFE_API_KEY", "test-key")

    def boom(*a, **k):
        raise httpx.ConnectError("no route")

    monkeypatch.setattr(httpx, "post", boom)
    with pytest.raises(RuntimeError, match="Jev request failed"):
        jev._post({})


# --- config -----------------------------------------------------------------

@pytest.mark.parametrize("url,expected", [
    ("https://app.example.com/FYABCDEF/templates?x=1", "/:ws/templates"),
    ("https://app.example.com/FYABCDEF", "/:ws"),
    ("/FYABCDEF/templates/gh-1/v1#top", "/:ws/templates/gh-1/v1"),
    ("/", "/"),
    ("https://app.example.com", "/"),
    ("/login", "/login"),
])
def test_ws_path_drops_origin_query_and_the_workspace_id(url, expected):
    assert config.ws_path(url) == expected


def test_disabled_elements_are_shown_but_never_offered(monkeypatch):
    disabled = _el("e9", "button", "Delete", state={"disabled": "true"})
    live = _el("e1", "button", "Cancel")
    sent = {}

    def fake(state, questions):
        sent.update(state=state, questions=questions)
        return {"operation": _choice("CLICK", {"CLICK": 1.0, "HOVER": 0.0, "WAIT": 0.0, "DONE": 0.0, "BLOCKED": 0.0}),
                "target": _choice("e1", {"e1": 1.0, "none": 0.0})}, 5

    monkeypatch.setattr(jev, "_ask", fake)
    d = jev.choose(_snap([live, disabled]), "goal", [])
    assert d.element.id == "e1"
    assert [r["index"] for r in sent["state"]["elements"]] == ["e1", "e9"]
    assert "e9" not in sent["questions"]["target"]["criteria"]
