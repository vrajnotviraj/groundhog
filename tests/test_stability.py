import json
from types import SimpleNamespace

import pytest
import typer
from playwright.sync_api import TimeoutError as PWTimeout

from groundhog import config
from groundhog.browser import actions
from groundhog.cases.schema import Expect, Step


# --- fake page objects: exercise the browser layer without a real browser ---
# A locator "resolves" when its count is > 0; a click/fill waits (bounded by its
# own timeout) for that to happen, mirroring Playwright's actionability wait.


class _Clock:
    """Deterministic monotonic clock; wait_for_timeout is the only thing that
    advances it, so timing is exact regardless of the host's speed."""

    def __init__(self):
        self.t = 0.0

    def monotonic(self):
        return self.t

    def advance(self, ms):
        self.t += ms / 1000.0


class _Loc:
    def __init__(self, page, selector):
        self.page = page
        self.selector = selector

    @property
    def first(self):
        return self

    def _count(self):
        v = self.page.counts.get(self.selector, 0)
        return v() if callable(v) else v

    count = _count

    def aria_snapshot(self):
        self.page.aria_calls += 1
        return self.page.aria

    def wait_for(self, state=None, timeout=None):
        self.page.wait_fors.append((self.selector, state))
        hook = self.page.intercepts.get(("wait_for", self.selector))
        if hook:
            hook()

    def _act(self, kind, timeout):
        self.page.actions.append((kind, self.selector, timeout))
        deadline = self.page.clock.monotonic() + (timeout or 0) / 1000
        while self._count() == 0:
            if self.page.clock.monotonic() > deadline:
                raise PWTimeout(f"{kind}: Timeout {timeout}ms exceeded.")
            self.page.wait_for_timeout(config.READINESS_POLL_MS)
        hook = self.page.intercepts.get((kind, self.selector))
        if hook:
            hook()

    def click(self, timeout=None):
        self._act("click", timeout)

    def fill(self, value, timeout=None):
        self._act("fill", timeout)

    def hover(self, timeout=None):
        self._act("hover", timeout)


class _Page:
    def __init__(self, clock, url="/app/home", aria='- button "x"', counts=None):
        self.clock = clock
        self.url = url
        self.aria = aria
        self.counts = counts or {}
        self.aria_calls = 0
        self.actions = []       # (kind, selector, timeout) for every action attempt
        self.wait_fors = []     # (selector, state) for every wait_for
        self.load_states = []
        self.intercepts = {}    # (kind, selector) -> callable (may raise / mutate)
        self.slept = 0
        self.polls = 0

    def locator(self, selector):
        return _Loc(self, selector)

    def wait_for_timeout(self, ms):
        self.slept += ms
        self.polls += 1
        self.clock.advance(ms)

    def wait_for_load_state(self, state, timeout=None):
        self.load_states.append(state)


def _mk(monkeypatch, **kw):
    clock = _Clock()
    page = _Page(clock, **kw)
    monkeypatch.setattr(actions, "time", clock)
    return page


def test_readiness_labels_a_slow_primary_static_with_short_action_timeout(monkeypatch):
    # The primary hasn't rendered yet at step start but attaches after two polls;
    # it must still be used (mode "static", not a mislabelled "fallback") and the
    # action must run on the short probe budget, not the full step timeout.
    page = _mk(monkeypatch, counts={"#save": lambda: 1 if page.polls >= 2 else 0})
    step = Step(action="click", selector="#save", expects=Expect(kind="url_contains", value="home"))
    out = actions.run_step(page, step, actions.Ctx())
    assert out.ok and out.mode == "static" and out.selector == "#save"
    clicks = [a for a in page.actions if a[0] == "click"]
    assert clicks == [("click", "#save", config.ACTION_PROBE_MS)]  # short, not STEP_TIMEOUT_MS


def test_fallback_walk_does_not_multiply_wait_by_candidate_count(monkeypatch):
    # No candidate ever resolves. Total wall-time must stay bounded and must not
    # grow with the number of fallbacks — the old code paid a full timeout each.
    monkeypatch.setattr(config, "STEP_TIMEOUT_MS", 300)
    monkeypatch.setattr(config, "ACTION_PROBE_MS", 100)
    monkeypatch.setattr(config, "READINESS_POLL_MS", 50)

    def slept_with(n_fallbacks):
        page = _mk(monkeypatch, counts={})  # nothing resolves
        step = Step(action="click", selector="#a",
                    fallback_selectors=[f"#f{i}" for i in range(n_fallbacks)])
        actions.run_step(page, step, actions.Ctx())
        return page.slept

    one, three = slept_with(1), slept_with(3)
    assert one == three               # independent of fallback count
    assert three <= 300 + 4 * 100     # ~one budget + a bounded primary probe/retry


def test_click_settles_and_retries_once_on_actionability_timeout(monkeypatch):
    # The element exists but the first click is intercepted (toast/overlay); after
    # a settle the retry lands. One retry, no loop.
    page = _mk(monkeypatch, counts={"#save": 1})
    hits = {"n": 0}

    def flaky():
        hits["n"] += 1
        if hits["n"] == 1:
            raise PWTimeout("click: Timeout 2000ms exceeded.")
        page.url = "/app/saved"  # the retry changes the page, so it's not a no-op

    page.intercepts[("click", "#save")] = flaky
    step = Step(action="click", selector="#save")
    out = actions.run_step(page, step, actions.Ctx())
    assert out.ok and out.mode == "static"
    # Attempted exactly twice: short first, full budget on the retry so a
    # slow-to-become-actionable element never fails faster than before.
    assert [a for a in page.actions if a[0] == "click"] == [
        ("click", "#save", config.ACTION_PROBE_MS),
        ("click", "#save", config.STEP_TIMEOUT_MS)]
    assert page.load_states  # a settle ran between the two attempts


def test_run_step_snapshots_the_page_once(monkeypatch):
    # The drift gate and the no-op baseline share one aria_snapshot instead of
    # computing it back-to-back twice.
    page = _mk(monkeypatch, counts={"#save": 1})
    step = Step(action="click", selector="#save", page_fingerprint="sha256:abc",
                expects=Expect(kind="url_contains", value="home"))
    actions.run_step(page, step, actions.Ctx())
    assert page.aria_calls == 1


def test_settle_waits_for_loading_indicators_and_never_throws(monkeypatch):
    # settle adds a bounded wait for spinners to detach, and a failure there is a
    # no-op — settle must never throw.
    page = _mk(monkeypatch)
    page.intercepts[("wait_for", actions.LOADING)] = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    actions.settle(page)  # does not raise
    assert (actions.LOADING, "hidden") in page.wait_fors


def _session_with(monkeypatch, url, pw_counts):
    from groundhog.browser import session

    page = _Page(_Clock(), url=url, counts={'input[type="password"]': pw_counts})
    s = session.Session.__new__(session.Session)
    s.page = page
    return s, page


def test_authenticated_waits_out_the_login_form_render_race(monkeypatch):
    # Password input hasn't rendered yet at first check but appears a poll later —
    # a bare count would race to a false "authenticated"; the wait catches it.
    from groundhog import config as cfg

    url = cfg.BASE_URL
    s, page = _session_with(monkeypatch, url, lambda: 1 if page.polls >= 1 else 0)
    assert s._authenticated() is False


def test_authenticated_is_cheap_when_state_is_already_obvious(monkeypatch):
    from groundhog import config as cfg

    # Already on a workspace URL: authenticated immediately, no polling.
    s, page = _session_with(monkeypatch, f"{cfg.BASE_URL}/FYABCDEF/home", 0)
    assert s._authenticated() is True and page.polls == 0
    # Password field present up front: not authenticated, no polling.
    s, page = _session_with(monkeypatch, cfg.BASE_URL, 1)
    assert s._authenticated() is False and page.polls == 0


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
