"""SMART composer: map an English chain description onto saved cases.

Composing a flow is pure selection — no browser, no new steps. The model only
picks from the saved-case catalog; a name it invents is rejected here, never
silently created.
"""

from pydantic import BaseModel, Field

from groundhog.cases import store
from groundhog.cases.schema import Flow
from groundhog.llm import client


class FlowDraft(BaseModel):
    name: str
    vars: dict[str, str] = Field(default_factory=dict)
    chain: list[str]
    cleanup: list[str] = Field(default_factory=list)


def compose_flow(intent: str, name: str | None = None) -> Flow:
    cases = store.list_cases()
    if not cases:
        raise ValueError("no saved cases yet — author some with `groundhog new` first")
    catalog = "\n".join(f"- {c.name}: {c.intent}" for c in cases)

    draft = client.parse(
        user=f"Compose a flow for this description:\n\n{intent}",
        output_model=FlowDraft,
        system=client.prompt("composer", catalog=catalog),
        model=client.SMART,
    )

    known = {c.name for c in cases}
    unknown = [n for n in draft.chain + draft.cleanup if n not in known]
    if unknown:
        raise ValueError(f"no saved case named {', '.join(unknown)} — author it with "
                         "`groundhog new` first (`groundhog list` shows what exists)")

    flow = Flow(name=name or draft.name, intent=intent, vars=draft.vars,
                chain=draft.chain, cleanup=draft.cleanup)
    store.save_flow(flow)
    return flow
