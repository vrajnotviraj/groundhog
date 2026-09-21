"""Playwright lifecycle + login.

`.auth/state.json` caches the session, so most runs log in with a single page
load. When it has expired, login goes through the app's own login API, run
inside the page on the app origin, so no browser form is driven and a login
page that only offers single sign-on buttons is never touched.
Credential values never leave this module.
"""

import json
import time
from urllib.parse import urlsplit

from playwright.sync_api import Page, sync_playwright

from groundhog import config
from groundhog.browser.actions import settle

STATE = config.AUTH_DIR / "state.json"

# Runs on the app origin: fetches the server's public key, wraps the credentials
# in the envelope the login endpoint expects, and posts it. The browser keeps the
# accessToken cookie the response sets.
SECURE_LOGIN_JS = """
async ({email, password}) => {
  const b64 = buf => { const u = new Uint8Array(buf); let s = ''; for (let i = 0; i < u.length; i += 32768) s += String.fromCharCode.apply(null, u.subarray(i, i + 32768)); return btoa(s); };
  const {key} = await (await fetch('/api/secure/public-key')).json();
  const pub = await crypto.subtle.importKey('spki', Uint8Array.from(atob(key), c => c.charCodeAt(0)), {name: 'RSA-OAEP', hash: 'SHA-256'}, false, ['encrypt']);
  const aes = await crypto.subtle.generateKey({name: 'AES-GCM', length: 256}, true, ['encrypt']);
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const nonce = b64(crypto.getRandomValues(new Uint8Array(16)));
  const enc = new TextEncoder();
  const body = enc.encode(JSON.stringify({action: 'login', data: {email, password}, params: {}, ts: Date.now(), nonce}));
  const payload = await crypto.subtle.encrypt({name: 'AES-GCM', iv, additionalData: enc.encode('login')}, aes, body);
  const envelope = {v: 1, key: b64(await crypto.subtle.encrypt({name: 'RSA-OAEP'}, pub, await crypto.subtle.exportKey('raw', aes))), iv: b64(iv), payload: b64(payload)};
  const r = await fetch('/api/secure/login', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(envelope), credentials: 'include'});
  return {status: r.status, text: await r.text()};
}
"""


def _storage_state() -> str | None:
    """Path to the cached session state, or None when missing or corrupt.
    A crash mid-write leaves truncated JSON; a fresh login costs one form fill,
    while feeding Playwright a broken file kills the whole run."""
    if not STATE.exists():
        return None
    try:
        json.loads(STATE.read_text())
    except ValueError:
        return None
    return str(STATE)


class Session:
    def __init__(self, headless: bool | None = None):
        self.headless = config.HEADLESS if headless is None else headless
        self.ws = ""  # workspace id parsed from the post-login URL

    def __enter__(self) -> "Session":
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless)
        self._context = self._browser.new_context(storage_state=_storage_state())
        self.page: Page = self._context.new_page()
        return self

    def __exit__(self, *exc) -> None:
        self._context.close()
        self._browser.close()
        self._pw.stop()

    def _path(self) -> str:
        return self.page.url.removeprefix(config.BASE_URL)

    def _authenticated(self) -> bool:
        """Right after goto+settle the SPA may not have rendered the login form
        yet, so a bare password-input count races to a false "authenticated".
        Wait (bounded) for the first definite signal: a workspace/picker URL
        (logged in), or a login path / password field (not). Cheap when the
        state is already obvious: the first check returns immediately.
        Unknown counts as not logged in — that costs one login attempt and a
        clear error, where a wrong "yes" runs the whole case on a login page."""
        deadline = time.monotonic() + config.STEP_TIMEOUT_MS / 1000
        while True:
            path = self._path()
            if config.WS_ID.search(path) or "/workspaces" in path:
                return True
            if "/login" in path or self.page.locator('input[type="password"]').count() > 0:
                return False
            if time.monotonic() > deadline:
                return False
            self.page.wait_for_timeout(250)

    def _capture(self) -> None:
        config.AUTH_DIR.mkdir(exist_ok=True)
        self._context.storage_state(path=str(STATE))
        m = config.WS_ID.search(self._path())
        if m:
            self.ws = m.group(0).strip("/")

    def _select_workspace(self) -> None:
        """A cached session can land on the /workspaces picker rather than a
        workspace home — pick the configured one so `ws` is always known.
        The SPA can also boot at `/` and only redirect a beat later, so wait
        (bounded) for it to land on a workspace before capturing state."""
        if config.WS_ID.search(self._path()):
            return  # already in a workspace (the direct open landed there)
        if config.WORKSPACE_ID:
            self.page.goto(f"{config.BASE_URL}/{config.WORKSPACE_ID}/home")
            settle(self.page)
            return
        clicked = False
        deadline = time.monotonic() + config.STEP_TIMEOUT_MS / 1000
        while time.monotonic() < deadline:
            path = self._path()
            if config.WS_ID.search(path):
                return
            if "/workspaces" in path and config.LOGIN_WORKSPACE and not clicked:
                self.page.get_by_role("link", name=config.LOGIN_WORKSPACE).first.click(
                    timeout=config.STEP_TIMEOUT_MS)
                settle(self.page)
                clicked = True
            else:
                self.page.wait_for_timeout(250)


    def _login(self) -> None:
        """Call the app's login API from inside the page, so the browser keeps the
        cookies it sets. The password only ever travels to the app origin."""
        if not (config.LOGIN_USER and config.LOGIN_PASS):
            raise RuntimeError("LOGIN_USER / LOGIN_PASS are not set — add them to .env")
        self.page.goto(config.BASE_URL + "/login")
        settle(self.page)
        res = self.page.evaluate(
            SECURE_LOGIN_JS, {"email": config.LOGIN_USER, "password": config.LOGIN_PASS})
        try:
            body = json.loads(res["text"])
        except ValueError:
            body = {}
        if res["status"] != 200 or body.get("status") != "ok":
            # Only the server's own message, never the credentials that produced it.
            message = body.get("_message") or f"HTTP {res['status']}"
            raise RuntimeError(f"login failed: {message} — check LOGIN_USER / LOGIN_PASS in .env")
        # The API sets the auth cookie; the SPA also wants this plain marker before
        # it treats the session as logged in.
        self._context.add_cookies([{"name": "userId", "value": "true",
                                    "domain": urlsplit(config.BASE_URL).netloc, "path": "/"}])
        self.page.goto(config.BASE_URL)
        settle(self.page)
        if not self._authenticated():
            raise RuntimeError("login succeeded but the app did not open an authenticated page")

    def _open_app(self) -> None:
        """First page load, retried once: a slow dev environment can take longer than
        Playwright's default and must fail with a plain message, not a traceback."""
        # With a known workspace, land there in one load instead of via the picker.
        url = f"{config.BASE_URL}/{config.WORKSPACE_ID}/home" if config.WORKSPACE_ID else config.BASE_URL
        for attempt in range(2):
            try:
                self.page.goto(url, timeout=config.PAGE_LOAD_MS)
                settle(self.page)
                return
            except Exception:
                if attempt:
                    raise RuntimeError(f"the app did not load within {config.PAGE_LOAD_MS // 1000}s: {config.BASE_URL}")

    def ensure_logged_in(self) -> None:
        """Reach an authenticated page: cached session → login API → error."""
        self._open_app()
        if not self._authenticated():
            self._login()
        self._select_workspace()
        # Without a workspace id every later /:ws path is wrong, so say so here
        # rather than cache the state and report a green, workspace-less login.
        if not config.WS_ID.search(self._path()):
            raise RuntimeError("login succeeded but no workspace was selected: "
                               "check LOGIN_WORKSPACE in .env")
        self._capture()
