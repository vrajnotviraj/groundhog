"""FAST page observation: snapshot in → cataloged interactive elements out."""

from typing import Literal

from pydantic import BaseModel, Field

from groundhog.browser.snapshot import snapshot
from groundhog.llm import client


class ObservedElement(BaseModel):
    selector: str
    role: str = ""
    name: str = ""
    kind: Literal["nav", "modal", "mutation", "destructive"]
    description: str = ""


class Observation(BaseModel):
    elements: list[ObservedElement] = Field(default_factory=list)


def observe(page) -> list[ObservedElement]:
    context = (f"Page URL: {page.url}\n\n"
               f"Accessibility snapshot:\n{snapshot(page)}")
    result = client.parse(
        user="Catalog the interactive elements.",
        output_model=Observation,
        system=client.prompt("observe", context=context),
        model=client.FAST,
        max_tokens=8192,
    )
    from groundhog.browser.selectors import is_weak

    return [e for e in result.elements if not is_weak(e.selector)]
