"""SMART optimizer: executed trace → minimal case JSON (selectors verbatim)."""

import json
from typing import Literal

from pydantic import BaseModel, Field

from groundhog.cases.schema import Action, Assertion, Case, Expect, Step
from groundhog.llm import client


class OptStep(BaseModel):
    # The shared Action type, not a hand-copied list — a copy drifted once and
    # silently rejected hover steps the executor had just recorded.
    action: Action
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


def _step_fingerprints(trace: list[dict], steps: list[OptStep]) -> list[str | None]:
    """Align optimized steps to trace entries in order rather than by selector
    alone — a selector reused across steps (e.g. the same "Create" button
    clicked twice in one flow) would otherwise have every occurrence collapse
    onto whichever trace entry happens to be last. Walk the trace forward,
    consuming the next entry whose selector matches; a step whose selector
    never turns up ahead gets no fingerprint rather than a hallucinated one."""
    fps: list[str | None] = []
    pos = 0
    for s in steps:
        fp = None
        if s.selector:
            for j in range(pos, len(trace)):
                if trace[j].get("selector") == s.selector:
                    fp = trace[j].get("fingerprint_before")
                    pos = j + 1
                    break
        fps.append(fp)
    return fps


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
    fps = _step_fingerprints(trace, result.steps)
    steps = []
    for i, (s, fp) in enumerate(zip(result.steps, fps), 1):
        steps.append(Step(
            id=f"s{i}",
            **s.model_dump(),
            page_fingerprint=fp,
        ))
    return Case(name=name, intent=intent, start_path=result.start_path,
                steps=steps, assertions=result.assertions)
