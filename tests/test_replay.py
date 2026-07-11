import types

from groundhog import config
from groundhog.cases.schema import Case
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
