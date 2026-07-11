"""Case JSON schema — the contract between the authoring agent and static replay."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

Action = Literal["goto", "click", "fill", "fill_secret", "select", "press", "wait_for", "drag"]


class Expect(BaseModel):
    """Cheap deterministic post-condition checked after a step executes."""

    kind: Literal["text_visible", "url_contains", "selector_visible"]
    value: str


class Step(BaseModel):
    id: str = ""
    action: Action
    selector: str | None = None
    # Ranked alternates captured at authoring time, so most drift heals with
    # zero LLM calls — just walk the list.
    fallback_selectors: list[str] = Field(default_factory=list)
    # Drop target for drag; healing never rewrites it.
    to_selector: str | None = None
    value: str | None = None
    # fill_secret stores only the field name; the value is injected from env.
    field: Literal["user", "pass"] | None = None
    description: str = ""
    expects: Expect | None = None
    # Hash of the pruned snapshot seen at authoring time — the replay drift gate.
    page_fingerprint: str | None = None
    healed_count: int = 0


class Assertion(BaseModel):
    assertion: str
    # deterministic: "url_contains:/x" / "text_visible:X" checked directly.
    # llm: plain English judged against the final snapshot.
    mode: Literal["deterministic", "llm"] = "llm"


class Heal(BaseModel):
    step: str
    old: str
    new: str
    at: str
    reason: str


class Meta(BaseModel):
    created_at: str = ""
    runs: int = 0
    heals: list[Heal] = Field(default_factory=list)


class Case(BaseModel):
    name: str
    intent: str
    start_path: str = "/"
    steps: list[Step]
    assertions: list[Assertion] = Field(default_factory=list)
    meta: Meta = Field(default_factory=Meta)


class FlowCase(BaseModel):
    """One saved case inside a flow. In flow JSON a bare string is enough;
    the object form adds per-case var overrides."""

    case: str
    # Rendered against the flow's shared vars, so a case can derive its value
    # from a shared one (e.g. query: "{{name}}").
    vars: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _from_name(cls, value):
        return {"case": value} if isinstance(value, str) else value


class Flow(BaseModel):
    """An ordered chain of saved cases run in one browser session.

    vars are shared by every case — the glue that lets an event case pick the
    template a previous case created. cleanup cases run even when the chain
    fails, so a create is always paired with its delete."""

    name: str
    intent: str = ""
    # Values may use {{stamp}} (a per-run UTC timestamp) so each run creates
    # uniquely-named data instead of colliding with leftovers.
    vars: dict[str, str] = Field(default_factory=dict)
    chain: list[FlowCase]
    cleanup: list[FlowCase] = Field(default_factory=list)
