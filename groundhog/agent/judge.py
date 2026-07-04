"""FAST judge: plain-English assertion vs the live page."""

from pydantic import BaseModel

from groundhog.browser.snapshot import snapshot
from groundhog.llm import client


class Verdict(BaseModel):
    passed: bool
    confidence: float
    reasoning: str


def judge(page, assertion: str) -> Verdict:
    context = (f"Assertion: {assertion}\n\n"
               f"Current page URL: {page.url}\n\n"
               f"Accessibility snapshot of the current page:\n{snapshot(page)}")
    return client.parse(
        user="Judge the assertion above against the page evidence.",
        output_model=Verdict,
        system=client.prompt("judge", context=context),
        model=client.FAST,
    )
