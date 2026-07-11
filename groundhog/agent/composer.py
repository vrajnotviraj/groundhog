"""SMART composer/orchestrator: turn an English chain description into a flow.

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


class DraftCase(BaseModel):
    """One step: either reuse a saved case (`reuse` alone) or author a new one
    (`name` + `intent`). Field descriptions guide the model — comments don't."""

    reuse: str = Field("", description="saved case name from the catalog, verbatim; "
                                       "empty when this step needs a new case")
    name: str = Field("", description="short kebab-case name for the new case to author; "
                                      "empty when reusing a saved case")
    intent: str = Field("", description="plain-English test intent for the new case, "
                                        "with {{var}} placeholders; required whenever reuse is empty")


class FlowDraft(BaseModel):
    name: str = Field(description="short kebab-case name for the flow")
    vars: dict[str, str] = Field(default_factory=dict,
                                 description="shared {{var}} defaults for every case in the flow, "
                                             "e.g. {\"name\": \"gh-{{stamp}}\"}")
    chain: list[DraftCase] = Field(description="the steps in order")
    cleanup: list[DraftCase] = Field(default_factory=list,
                                     description="steps that undo what the chain created; "
                                                 "run even when the chain fails")


def _decompose(intent: str) -> FlowDraft:
    cases = store.list_cases()
    catalog = "\n".join(f"- {c.name}: {c.intent}" for c in cases) or "(none yet)"
    draft = client.parse(
        user=f"Compose a flow for this description:\n\n{intent}",
        output_model=FlowDraft,
        system=client.prompt("composer", catalog=catalog),
        model=client.SMART,
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
    missing = needed - {"stamp"} - draft.vars.keys()
    if missing:
        raise ValueError(f"composer left {{{{var}}}}s without defaults: {sorted(missing)} — "
                         "rerun `groundhog flow new`")
    return draft


def _run_one(session: Session, dc: DraftCase, case_name: str, vars: dict[str, str]) -> None:
    """Replay an existing case or author a missing one; raises on failure."""
    from groundhog.agent.executor import author_case

    if dc.reuse:
        console.print(f"\n[bold]{case_name}[/] [dim](replaying saved case)[/]")
        if not run_case(store.load(dc.reuse), session, vars=vars).passed:
            raise RuntimeError(f"saved case {dc.reuse} failed during the composing pass")
    else:
        console.print(f"\n[bold]{case_name}[/] [dim](authoring new case)[/]")
        author_case(dc.intent, name=case_name, vars=vars, session=session)


def compose_flow(intent: str, name: str | None = None, headless: bool = True) -> Flow:
    from groundhog.agent.executor import _derive_name

    draft = _decompose(intent)
    flow = Flow(name=name or draft.name, intent=intent, vars=draft.vars,
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
