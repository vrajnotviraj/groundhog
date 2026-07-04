"""FAST healer: one call on step failure — replacement selector or refusal.

Never forces a stale selector: the replacement must come from the current
snapshot, must not contradict the step intent (a Delete step must never heal
to Cancel), and must actually execute before it is accepted.
"""

from pydantic import BaseModel, Field

from groundhog.browser.actions import Ctx, check_expects, perform
from groundhog.browser.selectors import is_weak
from groundhog.browser.snapshot import snapshot
from groundhog.cases.schema import Step
from groundhog.llm import client


class Fix(BaseModel):
    selector: str = Field(description="one resilient locator from the snapshot, or empty to refuse")
    reasoning: str


def heal_step(page, step: Step, ctx: Ctx, error: str | None) -> Fix | None:
    """Returns a verified Fix, or None (refusal / replacement didn't work)."""
    context = (f"Step intent: {step.description or step.action}\n"
               f"Action: {step.action}"
               + (f" (value: {step.value})" if step.value else "") + "\n"
               f"Original selector (no longer matches): {step.selector}\n"
               f"Failure: {error or 'selector did not resolve'}\n\n"
               f"Accessibility snapshot of the current page:\n{snapshot(page)}")
    fix = client.parse(
        user="Propose the replacement selector, or refuse with an empty selector.",
        output_model=Fix,
        system=client.prompt("healer", context=context),
        model=client.FAST,
    )
    if not fix.selector.strip() or is_weak(fix.selector):
        return None

    # A heal is only a heal if it actually works right now.
    try:
        perform(page, step, ctx, selector=fix.selector)
    except Exception:
        return None
    if step.expects and not check_expects(page, step.expects, ctx):
        return None
    return fix
