"""SMART optimizer: executed trace → minimal case JSON (selectors verbatim)."""

import json
from typing import Literal

from pydantic import BaseModel, Field

from groundhog.cases.schema import Assertion, Case, Expect, Step
from groundhog.llm import client


class OptStep(BaseModel):
    action: Literal["goto", "click", "fill", "fill_secret", "select", "press", "wait_for", "drag"]
    selector: str | None = None
    fallback_selectors: list[str] = Field(default_factory=list)
    to_selector: str | None = None
    value: str | None = None
    field: Literal["user", "pass"] | None = None
    description: str = ""
    expects: Expect | None = None


class OptimizedCase(BaseModel):
    start_path: str
    steps: list[OptStep]
    assertions: list[Assertion]


def optimize(name: str, intent: str, trace: list[dict], suggested: dict) -> Case:
    """trace: executed action records; suggested: the executor's done() payload."""
    # Fingerprints are attached mechanically below — hide them from the model.
    lean = [{k: v for k, v in t.items() if k != "fingerprint_before"} for t in trace]
    context = (f"Intent: {intent}\n\n"
               f"Executed trace:\n{json.dumps(lean, indent=2)}\n\n"
               f"Agent's suggested start_path: {suggested.get('start_path', '')}\n"
               f"Agent's suggested assertions: {json.dumps(suggested.get('assertions', []))}")
    result = client.parse(
        user="Produce the final minimal case.",
        output_model=OptimizedCase,
        system=client.prompt("optimizer", context=context),
        model=client.SMART,
        max_tokens=min(32768, 8192 + 200 * len(trace)),  # output scales with long flows
    )

    # Attach authoring-time fingerprints from the trace — never LLM-invented.
    fp_by_selector = {t["selector"]: t.get("fingerprint_before") for t in trace if t.get("selector")}
    steps = []
    for i, s in enumerate(result.steps, 1):
        steps.append(Step(
            id=f"s{i}",
            **s.model_dump(),
            page_fingerprint=fp_by_selector.get(s.selector),
        ))
    return Case(name=name, intent=intent, start_path=result.start_path,
                steps=steps, assertions=result.assertions)
