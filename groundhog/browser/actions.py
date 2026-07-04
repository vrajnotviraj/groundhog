"""Execute one case Step deterministically: selector → fallbacks → expects → no-op check.

This is the zero-LLM path. Healing lives in the runner; this module only reports
what happened so the caller can decide to heal or fail.
"""

import time
from dataclasses import dataclass

from playwright.sync_api import Page

from groundhog import config
from groundhog.browser.snapshot import fingerprint, snapshot
from groundhog.cases.schema import Expect, Step
from groundhog.cases.store import render


@dataclass
class Ctx:
    """Per-run context: workspace id for :ws paths, template vars for values."""

    ws: str = ""
    vars: dict[str, str] | None = None


@dataclass
class StepOutcome:
    ok: bool
    selector: str | None = None  # the selector that actually worked
    mode: str = "static"  # static | fallback
    drift: bool = False  # page fingerprint differed from the stored one
    error: str | None = None


def settle(page: Page, timeout_ms: int = None) -> None:
    """Wait for the page to settle, bounded: networkidle may never fire on an
    app with websockets/polling."""
    timeout_ms = timeout_ms or config.SETTLE_TIMEOUT_MS
    try:
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except Exception:
        pass


def resolve_path(path: str, ctx: Ctx) -> str:
    path = render(path, ctx.vars)  # paths address entities the test created: /templates/{{name}}/v1
    if path.startswith("http"):
        return path
    path = path.replace("/:ws", f"/{ctx.ws}" if ctx.ws else "")
    return f"{config.BASE_URL}{path if path.startswith('/') else '/' + path}"


def _credential(field: str) -> str:
    return config.LOGIN_USER if field == "user" else config.LOGIN_PASS


def on_picker(page: Page) -> bool:
    """The app sometimes bounces to /workspaces(?forwardUrl=…) when the session
    loses workspace context — no step or crawl page legitimately starts there."""
    return "/workspaces" in page.url


def recover_workspace(page: Page) -> bool:
    if not (on_picker(page) and config.LOGIN_WORKSPACE):
        return False
    try:
        page.get_by_role("link", name=config.LOGIN_WORKSPACE).first.click(
            timeout=config.STEP_TIMEOUT_MS)
        settle(page)
        return True
    except Exception:
        return False


def goto_app(page: Page, url: str) -> None:
    """Navigate within the app, recovering from the workspace-picker bounce.
    The bounce is a client-side boot race that can re-fire on the very page a
    recovery lands on, so give it several rounds before giving up."""
    page.goto(url)
    settle(page)
    for _ in range(4):
        if not on_picker(page):
            return
        recover_workspace(page)
        page.wait_for_timeout(1500)  # the picked workspace forwards asynchronously
        if url.split("?")[0] not in page.url:
            page.goto(url)
            settle(page)


def perform(page: Page, step: Step, ctx: Ctx, selector: str | None = None) -> None:
    """One action against the live page. Throws on failure so callers decide
    whether to walk fallbacks, heal, or fail."""
    timeout = config.STEP_TIMEOUT_MS
    if step.action == "goto":
        goto_app(page, resolve_path(step.value or step.selector or "/", ctx))
        return
    # Selectors render {{var}} too, so a step can target an entity created
    # earlier in the same test by its per-run name. Literals never substitute.
    loc = page.locator(render(selector or step.selector or "", ctx.vars)).first
    value = render(step.value or "", ctx.vars)
    if step.action == "click":
        loc.click(timeout=timeout)
    elif step.action == "fill":
        loc.fill(value, timeout=timeout)
    elif step.action == "fill_secret":
        loc.fill(_credential(step.field or "user"), timeout=timeout)
    elif step.action == "select":
        loc.select_option(label=value, timeout=timeout)
    elif step.action == "press":
        loc.press(value or "Enter", timeout=timeout)
    elif step.action == "wait_for":
        loc.wait_for(state="visible", timeout=timeout)
    settle(page)


def check_expects(page: Page, expects: Expect, ctx: Ctx) -> bool:
    """Waits (bounded) rather than sampling — data often lands after settle."""
    value = render(expects.value, ctx.vars)
    if expects.kind == "url_contains":
        deadline = time.monotonic() + config.STEP_TIMEOUT_MS / 1000
        while value not in page.url:
            if time.monotonic() > deadline:
                return False
            page.wait_for_timeout(200)
        return True
    try:
        loc = page.get_by_text(value) if expects.kind == "text_visible" else page.locator(value)
        loc.first.wait_for(state="visible", timeout=config.STEP_TIMEOUT_MS)
        return True
    except Exception:
        return False


def run_step(page: Page, step: Step, ctx: Ctx) -> StepOutcome:
    """The static replay of one step: drift gate → selector → fallbacks →
    expects → no-op detection. Zero LLM calls."""
    drift = False
    if step.page_fingerprint:
        drift = fingerprint(snapshot(page)) != step.page_fingerprint

    if step.action == "goto":
        # A goto can "succeed" yet land elsewhere — the app redirects entity
        # pages that race their own creation back to a list. The expects is the
        # honest signal, and one settle-and-retry beats failing on the race.
        for attempt in range(2):
            try:
                perform(page, step, ctx)
            except Exception as e:
                return StepOutcome(ok=False, drift=drift, error=str(e))
            if not step.expects or check_expects(page, step.expects, ctx):
                return StepOutcome(ok=True, drift=drift)
            page.wait_for_timeout(1500)
        return StepOutcome(ok=False, drift=drift,
                           error=f"expects failed: {step.expects.kind}={step.expects.value!r}")

    if on_picker(page):
        recover_workspace(page)

    before_url, before_fp = page.url, fingerprint(snapshot(page))
    last_error = None
    for i, sel in enumerate([step.selector, *step.fallback_selectors]):
        if not sel:
            continue
        try:
            perform(page, step, ctx, selector=sel)
        except Exception as e:
            last_error = str(e).split("\n")[0]
            continue
        mode = "static" if i == 0 else "fallback"
        if step.expects and not check_expects(page, step.expects, ctx):
            return StepOutcome(ok=False, selector=sel, mode=mode, drift=drift,
                               error=f"expects failed: {step.expects.kind}={step.expects.value!r}")
        # A "successful" click that changed nothing is a silent no-op — fail it
        # so it can heal. Only when the step has no expects of its own.
        if step.action == "click" and not step.expects:
            if page.url == before_url and fingerprint(snapshot(page)) == before_fp:
                return StepOutcome(ok=False, selector=sel, mode=mode, drift=drift,
                                   error="no-op: click changed nothing on the page")
        return StepOutcome(ok=True, selector=sel, mode=mode, drift=drift)

    return StepOutcome(ok=False, drift=drift, error=last_error or "no usable selector")
