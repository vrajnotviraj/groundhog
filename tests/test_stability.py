from types import SimpleNamespace

import pytest
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

    def filter(self, visible=None):
        return self

    def _count(self):
        v = self.page.counts.get(self.selector, 0)
        return v() if callable(v) else v

    count = _count

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
        self.page.fills.append((self.selector, value))

    def hover(self, timeout=None):
        self._act("hover", timeout)


class _FrameLoc:
    """A fake FrameLocator: .locator(sel) returns a normal _Loc keyed on the
    inner selector, mirroring Playwright — so one existence/action path serves
    both top-document and in-frame locators."""

    def __init__(self, page, frame_sel):
        self.page = page
        self.frame_sel = frame_sel

    def locator(self, selector):
        return _Loc(self.page, selector)


class _Page:
    def __init__(self, clock, url="/app/home", aria='- button "x"', counts=None):
        self.clock = clock
        self.url = url
        self.aria = aria
        self.counts = counts or {}
        self.observes = 0
        self.actions = []       # (kind, selector, timeout) for every action attempt
        self.fills = []         # (selector, value) for every fill
        self.wait_fors = []     # (selector, state) for every wait_for
        self.load_states = []
        self.intercepts = {}    # (kind, selector) -> callable (may raise / mutate)
        self.slept = 0
        self.polls = 0
        self.frame_locators = []  # frame selectors passed to frame_locator()
        self.gotos = []         # every url passed to goto()
        self.evaluates = []     # (js, arg) for every evaluate()
        self.eval_result = None  # what evaluate() hands back
        self.url_waits = []     # timeout of every wait_for_url()

    def locator(self, selector):
        return _Loc(self, selector)

    def get_by_role(self, role, name=None, exact=False):
        return _Loc(self, f'role={role}[name="{name}"]')

    def goto(self, url, timeout=None):
        self.gotos.append(url)
        self.url = url
        hook = self.intercepts.get(("goto", url))
        if hook:
            hook()

    def evaluate(self, js, arg=None):
        self.evaluates.append((js, arg))
        return self.eval_result

    def frame_locator(self, selector):
        self.frame_locators.append(selector)
        return _FrameLoc(self, selector)

    def wait_for_timeout(self, ms):
        self.slept += ms
        self.polls += 1
        self.clock.advance(ms)

    def wait_for_load_state(self, state, timeout=None):
        self.load_states.append(state)

    def wait_for_url(self, predicate, timeout=None):
        self.url_waits.append(timeout)
        if not predicate(self.url):
            raise PWTimeout(f"wait_for_url: Timeout {timeout}ms exceeded.")


def _observe(page):
    """Stand-in for the real snapshot: the fake page's aria string IS its
    fingerprint, so a test changes the page by changing page.aria."""
    page.observes += 1
    return SimpleNamespace(fingerprint=page.aria, url=page.url)


def _mk(monkeypatch, **kw):
    clock = _Clock()
    page = _Page(clock, **kw)
    monkeypatch.setattr(actions, "time", clock)
    monkeypatch.setattr(actions, "observe", _observe)
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


def test_step_with_frame_resolves_locator_inside_the_iframe(monkeypatch):
    # An element only reachable inside an iframe: the step's frame selector must
    # route existence + action through page.frame_locator(frame).locator(sel).
    page = _mk(monkeypatch, counts={"#editor-body": 1})
    page.intercepts[("click", "#editor-body")] = lambda: setattr(page, "url", "/app/edited")
    step = Step(action="click", selector="#editor-body", frame='iframe[title="Editor"]')
    out = actions.run_step(page, step, actions.Ctx())
    assert out.ok and out.selector == "#editor-body"
    # every locator resolution routed through the frame; none against the top document
    assert page.frame_locators and set(page.frame_locators) == {'iframe[title="Editor"]'}
    assert ("click", "#editor-body", config.ACTION_PROBE_MS) in page.actions


def test_exists_but_not_actionable_click_gets_a_next_strategy_hint(monkeypatch):
    # A label-wrapped Ant checkbox: it passes the existence probe but every click
    # times out. The raw Playwright timeout must gain the actionable hint so the
    # heal step switches strategy instead of retrying the same dead selector.
    sel = 'role=checkbox[name="SMS"]'
    page = _mk(monkeypatch, counts={sel: 1})
    page.intercepts[("click", sel)] = lambda: (_ for _ in ()).throw(
        PWTimeout("click: Timeout 10000ms exceeded."))
    out = actions.run_step(page, Step(action="click", selector=sel), actions.Ctx())
    assert not out.ok
    assert "never became actionable" in out.error
    assert "Timeout 10000ms exceeded" in out.error  # original first line kept


def test_a_step_with_expects_never_observes_and_reports_no_drift(monkeypatch):
    page = _mk(monkeypatch, counts={"#save": 1})
    step = Step(action="click", selector="#save", page_fingerprint="sha256:abc",
                expects=Expect(kind="url_contains", value="home"))
    out = actions.run_step(page, step, actions.Ctx())
    assert out.ok and not out.drift and page.observes == 0
    assert page.url_waits == [config.STEP_TIMEOUT_MS]


def test_a_click_without_expects_observes_a_baseline_and_reports_drift(monkeypatch):
    page = _mk(monkeypatch, counts={"#save": 1})
    page.intercepts[("click", "#save")] = lambda: setattr(page, "aria", "- dialog")
    out = actions.run_step(page, Step(action="click", selector="#save", page_fingerprint="sha256:abc"),
                           actions.Ctx())
    assert out.ok and out.drift and page.observes == 2  # baseline plus the no-op check


def test_url_expects_fail_when_the_url_never_matches(monkeypatch):
    page = _mk(monkeypatch)
    assert not actions.check_expects(page, Expect(kind="url_contains", value="/saved"), actions.Ctx())


def test_wait_for_change_returns_on_a_late_render(monkeypatch):
    # A drawer that renders a beat after the click must not be read as a no-op.
    page = _mk(monkeypatch)
    before = SimpleNamespace(fingerprint=page.aria, url=page.url)
    original = page.wait_for_timeout

    def render_after_two_polls(ms):
        original(ms)
        if page.polls == 2:
            page.aria = "- dialog"

    page.wait_for_timeout = render_after_two_polls
    after = actions.wait_for_change(page, before, timeout_ms=5000)
    assert after.fingerprint == "- dialog" and page.polls == 2


def test_wait_for_change_gives_up_at_the_bound(monkeypatch):
    page = _mk(monkeypatch)
    after = actions.wait_for_change(page, SimpleNamespace(fingerprint=page.aria, url=page.url), timeout_ms=1000)
    assert after.fingerprint == page.aria and page.slept <= 1250


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
    assert page.polls == 1  # it saw the field on the first poll, it did not time out


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


def _login_session(monkeypatch, tmp_path, page):
    from groundhog.browser import session

    monkeypatch.setattr(config, "AUTH_DIR", tmp_path)
    monkeypatch.setattr(config, "BASE_URL", "https://app.example.com")
    monkeypatch.setattr(config, "LOGIN_USER", "you@example.com")
    monkeypatch.setattr(config, "LOGIN_PASS", "placeholder")
    monkeypatch.setattr(config, "WORKSPACE_ID", "")
    s = session.Session.__new__(session.Session)
    s.ws = ""
    s.page = page
    s.cookies = []
    s._context = SimpleNamespace(storage_state=lambda path: None,
                                 add_cookies=s.cookies.extend)
    return session, s


def _lands_on(page, url):
    """Intercept for the post-login goto: only the navigation after the login
    call lands on a session, so the first goto still finds a logged-out app."""
    return lambda: page.evaluates and (
        setattr(page, "url", url),
        page.counts.__setitem__('input[type="password"]', 0))


def test_login_calls_the_login_api_and_captures_the_workspace(monkeypatch, tmp_path):
    page = _mk(monkeypatch, url="https://app.example.com/login",
               counts={'input[type="password"]': 1})
    session, s = _login_session(monkeypatch, tmp_path, page)
    page.eval_result = {"status": 200, "text": '{"status":"ok"}'}
    page.intercepts[("goto", "https://app.example.com")] = _lands_on(
        page, "https://app.example.com/FYABCDEF/home")

    s.ensure_logged_in()

    js, arg = page.evaluates[0]
    assert js is session.SECURE_LOGIN_JS
    assert arg == {"email": "you@example.com", "password": "placeholder"}
    # The SPA only reads the session as live with this marker cookie beside the
    # auth cookie the API set.
    assert s.cookies == [{"name": "userId", "value": "true",
                          "domain": "app.example.com", "path": "/"}]
    assert page.fills == []  # no login form is driven
    assert s.ws == "FYABCDEF"


def test_login_failure_names_the_env_vars_and_never_the_password(monkeypatch, tmp_path):
    # The API says why; the value that produced the error must not be echoed.
    page = _mk(monkeypatch, url="https://app.example.com/login",
               counts={'input[type="password"]': 1})
    session, s = _login_session(monkeypatch, tmp_path, page)
    page.eval_result = {"status": 400,
                        "text": '{"status":"error","_message":"Email or Password is invalid"}'}
    with pytest.raises(RuntimeError) as err:
        s.ensure_logged_in()
    assert "Email or Password is invalid" in str(err.value)
    assert "LOGIN_USER / LOGIN_PASS in .env" in str(err.value)
    assert "placeholder" not in str(err.value)


def test_a_configured_workspace_id_is_opened_directly(monkeypatch, tmp_path):
    # With WORKSPACE_ID set the picker is skipped, so the login also works when
    # the picker is slow or the workspace name is ambiguous.
    page = _mk(monkeypatch, url="https://app.example.com/login",
               counts={'input[type="password"]': 1})
    session, s = _login_session(monkeypatch, tmp_path, page)
    monkeypatch.setattr(config, "WORKSPACE_ID", "FYABCDEF")
    page.eval_result = {"status": 200, "text": '{"status":"ok"}'}
    page.intercepts[("goto", "https://app.example.com")] = _lands_on(
        page, "https://app.example.com/workspaces")

    s.ensure_logged_in()

    assert page.gotos[-1] == "https://app.example.com/FYABCDEF/home"
    assert s.ws == "FYABCDEF"


def test_the_picker_is_left_through_the_configured_workspace_link(monkeypatch, tmp_path):
    link = 'role=link[name="Your Workspace"]'
    page = _mk(monkeypatch, url="https://app.example.com/workspaces", counts={link: 1})
    session, s = _login_session(monkeypatch, tmp_path, page)
    monkeypatch.setattr(config, "LOGIN_WORKSPACE", "Your Workspace")
    page.intercepts[("click", link)] = lambda: setattr(page, "url", "https://app.example.com/FYABCDEF/home")
    s._select_workspace()
    assert [a[:2] for a in page.actions] == [("click", link)]


def test_login_without_a_workspace_names_the_env_var(monkeypatch, tmp_path):
    # The picker link never leads anywhere: a workspace-less "success" would cache
    # state and build every later /:ws path with an empty id.
    link = 'role=link[name="Your Workspace"]'
    page = _mk(monkeypatch, url="https://app.example.com/login",
               counts={'input[type="password"]': 1, link: 1})
    session, s = _login_session(monkeypatch, tmp_path, page)
    page.eval_result = {"status": 200, "text": '{"status":"ok"}'}
    page.intercepts[("goto", "https://app.example.com")] = _lands_on(
        page, "https://app.example.com/workspaces")
    monkeypatch.setattr(config, "LOGIN_WORKSPACE", "Your Workspace")
    monkeypatch.setattr(config, "STEP_TIMEOUT_MS", 20)
    with pytest.raises(RuntimeError, match="LOGIN_WORKSPACE"):
        s.ensure_logged_in()


def test_a_login_page_is_never_read_as_authenticated(monkeypatch):
    # The password field can be a step away, so "no password input" is not proof
    # of a session; the login path is.
    from groundhog import config as cfg

    s, page = _session_with(monkeypatch, f"{cfg.BASE_URL}/login", 0)
    assert s._authenticated() is False and page.polls == 0


def test_missing_credentials_fail_before_calling_the_login_api(monkeypatch, tmp_path):
    page = _mk(monkeypatch, url="https://app.example.com/login",
               counts={'input[type="password"]': 1})
    session, s = _login_session(monkeypatch, tmp_path, page)
    monkeypatch.setattr(config, "LOGIN_PASS", "")
    with pytest.raises(RuntimeError, match="are not set"):
        s.ensure_logged_in()
    assert page.evaluates == []


def test_focusing_click_on_a_field_is_not_a_no_op_failure(monkeypatch):
    # Clicking a search box before typing changes nothing visible; that is fine.
    sel = '[placeholder="Search Templates"]'
    page = _mk(monkeypatch, counts={sel: 1})
    out = actions.run_step(page, Step(action="click", selector=sel), actions.Ctx())
    assert out.ok
