"""Composer: turn an English chain description into a flow.

Composing decomposes the description into case-sized steps, reusing saved
cases verbatim and authoring the missing ones. The first pass runs live in ONE
session, in chain order: an existing case is replayed, a missing one is
authored — and since authoring performs the actions for real, the app state
advances exactly as a replay would, so each new case is built on top of what
the chain already created. The flow is saved after the pass; every later
`flow run` is a static replay.
"""

from pydantic import BaseModel, Field
from rich.console import Console

from groundhog.browser.session import Session
from groundhog.cases import store
from groundhog.cases.schema import Flow
from groundhog.cases.store import VAR
from groundhog.llm import client
from groundhog.runner.flow import shared_vars
from groundhog.runner.replay import run_case

console = Console()

COMPOSER = """\
You compose a flow: an ordered chain of case-sized test steps that run in one browser session, plus cleanup steps \
that always run afterwards.

You are given a catalog of saved cases (name: intent) and a plain-English description of the flow. Decompose the \
description into steps the size of one case each — one entity or one verified outcome per step (create the template; \
create the event that uses it; fire it from the playground; delete the event; delete the template). For each step \
produce either:

- reuse: a saved case name from the catalog, verbatim. FIRST scan the catalog for every step: when a saved case's \
intent already covers it, reuse that case — authoring a near-duplicate of a catalog case is wrong. Only catalog \
names may appear here; a name of your own goes in `name`, never in `reuse`.
- name + intent: a new case to author when nothing in the catalog fits. name is short kebab-case. intent is a \
plain-English test intent written like the catalog ones: self-sufficient (it must work in a fresh session starting \
from its own page, since it will also replay standalone), parameterized with {{var}} placeholders instead of literal \
data, and ending with a verifiable outcome ("...and verify X"). A delete intent must confirm any confirmation dialog \
and verify the entity no longer appears.

Sort the steps into:

- chain: the steps in the order the description implies.
- cleanup: steps that undo what the chain created, in reverse order of creation. These run even when the chain \
fails. Every chain step that creates an entity should have a matching delete here — reused from the catalog when one \
exists, authored otherwise — unless the description explicitly says to keep the data. A delete of something the \
chain created belongs in cleanup even when the description narrates it as the last step.

Also produce:

- name: a short kebab-case name for the flow, derived from the description.
- vars: REQUIRED — a default for every {{var}} that appears in any step's intent, reused catalog cases included \
(their {{var}}s are visible in their catalog lines). A created entity gets a per-run unique default by embedding \
{{stamp}} (a per-run timestamp): "name": "gh-{{stamp}}". A var that must carry another var's value references it: \
"query": "{{name}}" makes a search step look for the entity the chain created. vars is what wires the chain \
together; leaving it empty when any intent has a {{var}} is invalid.

Saved cases:
{{catalog}}"""


class DraftCase(BaseModel):
    """One step: either reuse a saved case (`reuse` alone) or author a new one
    (`name` + `intent`). Field descriptions guide the model — comments don't."""

    reuse: str = Field("", description="saved case name from the catalog, verbatim; "
                                       "empty when this step needs a new case")
    name: str = Field("", description="short kebab-case name for the new case to author; "
                                      "empty when reusing a saved case")
    intent: str = Field("", description="plain-English test intent for the new case, "
                                        "with {{var}} placeholders; required whenever reuse is empty")


class DraftVar(BaseModel):
    var: str = Field(description="var name as it appears inside {{ }}")
    value: str = Field(description="default value; embed {{stamp}} for per-run uniqueness "
                                   "(gh-{{stamp}}), or reference another var ({{name}})")


class FlowDraft(BaseModel):
    name: str = Field(description="short kebab-case name for the flow")
    # a list of pairs, not a dict: strict structured-output schemas drop
    # free-form object keys, which came back as {} no matter the prompt
    vars: list[DraftVar] = Field(default_factory=list,
                                 description="shared var defaults — one entry per {{var}} "
                                             "used by any step's intent")
    chain: list[DraftCase] = Field(description="the steps in order")
    cleanup: list[DraftCase] = Field(default_factory=list,
                                     description="steps that undo what the chain created; "
                                                 "run even when the chain fails")

    def var_map(self) -> dict[str, str]:
        return {v.var: v.value for v in self.vars}


def _decompose(intent: str) -> FlowDraft:
    cases = store.list_cases()
    catalog = "\n".join(f"- {c.name}: {c.intent}" for c in cases) or "(none yet)"
    draft = client.parse(
        user=f"Compose a flow for this description:\n\n{intent}",
        output_model=FlowDraft,
        system=store.render(COMPOSER, {"catalog": catalog}),
    )
    known = {c.name for c in cases}
    by_intent = {c.intent: c.name for c in cases}
    needed: set[str] = set()
    for dc in draft.chain + draft.cleanup:
        if dc.reuse and dc.reuse not in known:
            if not dc.intent:
                raise ValueError(f"composer referenced a saved case that does not exist: {dc.reuse}")
            # the model named a new case under reuse but gave an intent too —
            # recover by treating it as a case to author
            dc.name, dc.reuse = dc.name or dc.reuse, ""
        if not dc.reuse and dc.intent in by_intent:
            # a "new" case with a catalog intent verbatim is a reuse in disguise
            dc.reuse, dc.name, dc.intent = by_intent[dc.intent], "", ""
        if not dc.reuse and not dc.intent:
            raise ValueError("composer produced a step with neither a saved case nor an intent")
        intent_text = next(c.intent for c in cases if c.name == dc.reuse) if dc.reuse else dc.intent
        needed |= set(VAR.findall(intent_text))
    missing = needed - {"stamp"} - draft.var_map().keys()
    if missing:
        raise ValueError(f"composer left {{{{var}}}}s without defaults: {sorted(missing)} — "
                         "rerun `groundhog flow new`")
    return draft


def _run_one(session: Session, dc: DraftCase, case_name: str, vars: dict[str, str]) -> None:
    """Replay an existing case or author a missing one; raises on failure."""
    from groundhog.agent.author import author_case

    if dc.reuse:
        console.print(f"\n[bold]{case_name}[/] [dim](replaying saved case)[/]")
        if not run_case(store.load(dc.reuse), session, vars=vars).passed:
            raise RuntimeError(f"saved case {dc.reuse} failed during the composing pass")
    else:
        console.print(f"\n[bold]{case_name}[/] [dim](authoring new case)[/]")
        author_case(dc.intent, name=case_name, vars=vars, session=session)


def compose_flow(intent: str, name: str | None = None, headless: bool = True) -> Flow:
    from groundhog.agent.author import _derive_name

    draft = _decompose(intent)
    flow = Flow(name=name or draft.name, intent=intent, vars=draft.var_map(),
                chain=[dc.reuse or dc.name or _derive_name(dc.intent) for dc in draft.chain],
                cleanup=[dc.reuse or dc.name or _derive_name(dc.intent) for dc in draft.cleanup])
    chain = list(zip(draft.chain, [fc.case for fc in flow.chain]))
    cleanup = list(zip(draft.cleanup, [fc.case for fc in flow.cleanup]))
    vars = shared_vars(flow)  # concrete values for the pass; cases stay parameterized

    with Session(headless=headless) as session:
        session.ensure_logged_in()
        try:
            for dc, case_name in chain:
                _run_one(session, dc, case_name, vars)
        except Exception as e:
            # the pass still owes the app a cleanup: replay the cleanup cases
            # that already exist so data isn't stranded, then report. Cases
            # authored before the failure stay saved — only the flow isn't.
            for dc, case_name in cleanup:
                if dc.reuse:
                    console.print(f"\n[bold]{case_name}[/] [dim](cleanup after failure)[/]")
                    try:
                        run_case(store.load(dc.reuse), session, vars=vars)
                    except Exception:
                        pass
            raise RuntimeError(f"{e} — flow not saved (already-authored cases were kept)")
        for dc, case_name in cleanup:
            _run_one(session, dc, case_name, vars)

    store.save_flow(flow)
    return flow
