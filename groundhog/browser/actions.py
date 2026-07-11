"""Execute one case Step deterministically: selector → fallbacks → expects → no-op check.

This is the zero-LLM path. Healing lives in the runner; this module only reports
what happened so the caller can decide to heal or fail.
"""

import time
from dataclasses import dataclass

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout

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


# Generic, app-agnostic loading indicators. Networkidle can settle while one of
# these still covers the content it fetched, so a step acts too early.
LOADING = '[aria-busy="true"], [role=progressbar], .ant-spin-spinning'


def settle(page: Page, timeout_ms: int = None) -> None:
    """Wait for the page to settle, bounded: networkidle may never fire on an
    app with websockets/polling."""
    timeout_ms = timeout_ms or config.SETTLE_TIMEOUT_MS
    try:
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except Exception:
        pass
    # One short bounded wait for obvious spinners to detach. wait_for(hidden)
    # resolves instantly when nothing matches, so this is a no-op on a still
    # page and never stacks a second full timeout onto the networkidle wait.
    try:
        page.locator(LOADING).first.wait_for(state="hidden", timeout=timeout_ms)
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


def _resolves(loc, timeout_ms: int) -> bool:
    """Poll a locator's existence cheaply until it resolves or the bound expires.
    A slow-rendering element still gets to attach; a selector that matches
    nothing fails fast instead of waiting out a full action timeout."""
    deadline = time.monotonic() + timeout_ms / 1000
    while loc.count() == 0:
        if time.monotonic() > deadline:
            return False
        loc.page.wait_for_timeout(config.READINESS_POLL_MS)
    return True


def perform(page: Page, step: Step, ctx: Ctx, selector: str | None = None,
            timeout_ms: int | None = None) -> None:
    """One action against the live page. Throws on failure so callers decide
    whether to walk fallbacks, heal, or fail."""
    timeout = timeout_ms or config.STEP_TIMEOUT_MS
    if step.action == "goto":
        goto_app(page, resolve_path(step.value or step.selector or "/", ctx))
        return
    # Selectors render {{var}} too, so a step can target an entity created
    # earlier in the same test by its per-run name. Literals never substitute.
    loc = page.locator(render(selector or step.selector or "", ctx.vars)).first
    value = render(step.value or "", ctx.vars)
    # Fail-fast existence probe: a bad selector (a wrong agent guess) otherwise
    # burns the full action timeout. wait_for waits for visibility itself, so it
    # keeps the full budget. Once existence is established the action below gets
    # its normal timeout, so a slow page still works.
    if step.action != "wait_for" and not _resolves(loc, config.ACTION_PROBE_MS):
        raise PlaywrightTimeout(
            f"selector resolved 0 elements after {config.ACTION_PROBE_MS}ms: "
            f"{render(selector or step.selector or '', ctx.vars)}")
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
    elif step.action == "hover":
        # reveals hover-only controls (e.g. row action buttons) for the next step
        loc.hover(timeout=timeout)
    elif step.action == "drag":
        # drag_to covers HTML5-dnd palettes but no-ops silently on d3-drag
        # handles (it does not throw) — an unchanged fingerprint after settle
        # triggers a manual mouse drag, with intermediate move events while
        # pressed, which is what d3-drag needs to register.
        dst = page.locator(render(step.to_selector or "", ctx.vars)).first
        fp_before = fingerprint(snapshot(page))
        loc.drag_to(dst, timeout=timeout)
        settle(page)
        if fingerprint(snapshot(page)) == fp_before:
            loc.hover(timeout=timeout)
            page.mouse.down()
            box = dst.bounding_box()
            if box:
                page.mouse.move(box["x"] + box["width"] / 2,
                                box["y"] + box["height"] / 2, steps=15)
            page.mouse.up()
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


def _await_ready(page: Page, ctx: Ctx, candidates: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """One shared bounded readiness wait for the whole candidate set: poll every
    candidate's existence cheaply until the first resolves or the step budget
    expires, then return the resolved ones in order. Without this each candidate
    would burn a full action timeout on a page that simply hasn't rendered yet,
    multiplying the wait by the fallback count. Zero LLM calls."""
    deadline = time.monotonic() + config.STEP_TIMEOUT_MS / 1000
    while True:
        ready = []
        for i, sel in candidates:
            try:
                if page.locator(render(sel, ctx.vars)).first.count() > 0:
                    ready.append((i, sel))
            except Exception:
                pass  # invalid selector never resolves; the walk surfaces the error
        if ready or time.monotonic() > deadline:
            return ready
        page.wait_for_timeout(config.READINESS_POLL_MS)


def _perform_settle_retry(page: Page, step: Step, ctx: Ctx, sel: str) -> None:
    """Act with a short timeout — existence is already established, so the action
    itself is quick. On an actionability timeout (a toast/overlay intercepts the
    pointer, or hydration is late) settle once and retry the same candidate;
    bounded, no loop."""
    try:
        perform(page, step, ctx, selector=sel, timeout_ms=config.ACTION_PROBE_MS)
    except PlaywrightTimeout:
        settle(page)
        # Full budget on the retry: an element that exists but is slow to become
        # actionable (animation, late enable) must not fail faster than before.
        perform(page, step, ctx, selector=sel)


def run_step(page: Page, step: Step, ctx: Ctx) -> StepOutcome:
    """The static replay of one step: drift gate → selector → fallbacks →
    expects → no-op detection. Zero LLM calls."""
    # One aria_snapshot per step: it is expensive on a big page, so compute the
    # fingerprint once and reuse it for both the drift gate and the no-op baseline.
    need_fp = bool(step.page_fingerprint) or step.action != "goto"
    current_fp = fingerprint(snapshot(page)) if need_fp else None
    drift = bool(step.page_fingerprint) and current_fp != step.page_fingerprint

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

    before_url, before_fp = page.url, current_fp
    candidates = [(i, sel) for i, sel in enumerate([step.selector, *step.fallback_selectors]) if sel]
    ready = _await_ready(page, ctx, candidates)
    # When nothing resolved within the budget, still attempt the primary once so
    # a real Playwright error (not a bare "no selector") reaches report and healer.
    last_error = None
    for i, sel in ready or candidates[:1]:
        try:
            _perform_settle_retry(page, step, ctx, sel)
        except Exception as e:
            last_error = str(e).split("\n")[0]
            continue
        mode = "static" if i == 0 else "fallback"
        if step.expects and not check_expects(page, step.expects, ctx):
            return StepOutcome(ok=False, selector=sel, mode=mode, drift=drift,
                               error=f"expects failed: {step.expects.kind}={step.expects.value!r}")
        # A "successful" click or drag that changed nothing is a silent no-op —
        # fail it so it gets reported. Only when the step has no expects of its own.
        if step.action in ("click", "drag") and not step.expects:
            if page.url == before_url and fingerprint(snapshot(page)) == before_fp:
                return StepOutcome(ok=False, selector=sel, mode=mode, drift=drift,
                                   error=f"no-op: {step.action} changed nothing on the page")
        return StepOutcome(ok=True, selector=sel, mode=mode, drift=drift)

    return StepOutcome(ok=False, drift=drift, error=last_error or "no usable selector")
