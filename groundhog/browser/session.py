"""Playwright lifecycle + login.

Two-layer login port from groundloop:
1. `.auth/state.json` — the session cookies/storage. When still valid, login is
   a single page load.
2. `.auth/login.json` — the login FLOW as replayable case steps. When the
   session expired, replay it deterministically (no agent, no tokens).
   fill_secret steps store only the field name — credentials stay in env.

The flow file lives next to the session, not in cases/, so it never shows up in
`groundhog list` as a normal test.
"""

import json
import re

from playwright.sync_api import Page, sync_playwright

from groundhog import config
from groundhog.browser.actions import Ctx, perform, settle
from groundhog.cases.schema import Step

STATE = config.AUTH_DIR / "state.json"
FLOW = config.AUTH_DIR / "login.json"

WS_ID = re.compile(r"^/(FY[A-Z0-9]{6,})/")


class Session:
    def __init__(self, headless: bool | None = None):
        self.headless = config.HEADLESS if headless is None else headless
        self.ws = ""  # workspace id parsed from the post-login URL

    def __enter__(self) -> "Session":
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless)
        state = str(STATE) if STATE.exists() else None
        self._context = self._browser.new_context(storage_state=state)
        self.page: Page = self._context.new_page()
        return self

    def __exit__(self, *exc) -> None:
        self._context.close()
        self._browser.close()
        self._pw.stop()

    def _authenticated(self) -> bool:
        return self.page.locator('input[type="password"]').count() == 0

    def _capture(self) -> None:
        config.AUTH_DIR.mkdir(exist_ok=True)
        self._context.storage_state(path=str(STATE))
        m = WS_ID.match(self.page.url.removeprefix(config.BASE_URL))
        if m:
            self.ws = m.group(1)

    def _select_workspace(self) -> None:
        """A cached session can land on the /workspaces picker rather than a
        workspace home — pick the configured one so `ws` is always known."""
        if WS_ID.match(self.page.url.removeprefix(config.BASE_URL)):
            return
        if "/workspaces" in self.page.url and config.LOGIN_WORKSPACE:
            self.page.get_by_role("link", name=config.LOGIN_WORKSPACE).first.click()
            settle(self.page)

    def ensure_logged_in(self) -> None:
        """Reach an authenticated page: cached session → replayed flow → error."""
        self.page.goto(config.BASE_URL)
        settle(self.page)
        if self._authenticated():
            self._select_workspace()
            self._capture()
            return

        if not FLOW.exists():
            raise RuntimeError(
                f"not logged in and no cached login flow at {FLOW} — "
                "seed one (see README) or author it with the agent"
            )
        flow = json.loads(FLOW.read_text())
        ctx = Ctx()
        for raw in flow.get("steps", []):
            step = Step.model_validate(raw)
            try:
                perform(self.page, step, ctx)
            except Exception:
                # e.g. the workspace picker only shows sometimes — a failed
                # click is fatal only if we still aren't authenticated at the end.
                pass
        settle(self.page)
        if not self._authenticated():
            raise RuntimeError("cached login flow did not reach an authenticated page")
        self._select_workspace()
        self._capture()
