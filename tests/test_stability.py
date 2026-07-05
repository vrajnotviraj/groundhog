import json
from types import SimpleNamespace

import pytest
import typer


def test_storage_state_falls_back_on_missing_or_corrupt_json(tmp_path, monkeypatch):
    from groundhog.browser import session

    state = tmp_path / "state.json"
    monkeypatch.setattr(session, "STATE", state)
    assert session._storage_state() is None  # missing → fresh login
    state.write_text('{"cookies": [')  # truncated by a crash mid-write
    assert session._storage_state() is None  # corrupt → fresh login, not a crash
    state.write_text('{"cookies": []}')
    assert session._storage_state() == str(state)


def test_llm_client_uses_sdk_native_retries(monkeypatch):
    from groundhog.llm import client

    monkeypatch.setattr(client, "_client", None)
    c = client._anthropic()
    assert c.max_retries == 5


def test_partial_trace_dump_writes_replayable_json(tmp_path, monkeypatch):
    from groundhog import config
    from groundhog.agent import executor

    monkeypatch.setattr(config, "RUNS_DIR", tmp_path)
    trace = [{"action": "click", "selector": "#save", "description": "save"}]
    path = executor._dump_partial("long-flow", trace)
    assert "long-flow-partial-" in path
    assert json.loads((tmp_path / path.rsplit("/", 1)[1]).read_text()) == trace


def test_run_executor_records_into_caller_supplied_trace(monkeypatch):
    from groundhog.agent import executor

    # A response with no tool calls: after two nudges the loop gives up, so we
    # exercise the loop end-to-end without a browser or an API key.
    monkeypatch.setattr(executor.client, "message",
                        lambda *a, **k: SimpleNamespace(content=[]))
    monkeypatch.setattr(executor, "snapshot", lambda page: "- button 'x'")
    page = SimpleNamespace(url="/home")
    trace: list[dict] = []
    got, done = executor.run_executor(page, ctx=None, intent="x", plan_steps=[],
                                      max_actions=5, trace=trace)
    assert got is trace  # the caller's list survives a mid-loop crash
    assert done is None


def test_crawl_keyboard_interrupt_keeps_partial_stats(monkeypatch):
    from groundhog.crawl import crawler

    class FakeSession:
        ws = "FY1"
        page = None

        def __init__(self, headless):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def ensure_logged_in(self):
            pass

    def interrupt(page, url):
        raise KeyboardInterrupt

    monkeypatch.setattr(crawler, "Session", FakeSession)
    monkeypatch.setattr(crawler, "goto_app", interrupt)
    stats = crawler.crawl(scope="/templates", max_pages=3)
    assert stats == {"pages": 0, "elements": 0, "transitions": 0}


def test_need_llm_exits_when_key_missing(monkeypatch):
    from groundhog import cli, config

    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "")
    with pytest.raises(typer.Exit):
        cli._need_llm()


def test_need_graph_exits_when_neo4j_down(monkeypatch):
    from groundhog import cli
    from groundhog.graph import store

    def down():
        raise ConnectionError("refused")

    monkeypatch.setattr(store, "driver", down)
    with pytest.raises(typer.Exit):
        cli._need_graph()
