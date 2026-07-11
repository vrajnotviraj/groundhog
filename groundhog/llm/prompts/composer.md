You compose a flow: an ordered chain of case-sized test steps that run in one browser session, plus cleanup steps that always run afterwards.

You are given a catalog of saved cases (name: intent) and a plain-English description of the flow. Decompose the description into steps the size of one case each — one entity or one verified outcome per step (create the template; create the event that uses it; fire it from the playground; delete the event; delete the template). For each step produce either:

- case: a saved case name from the catalog, verbatim, when its intent already covers the step. Prefer reuse — never author a near-duplicate of a saved case. Never invent or approximate a catalog name.
- name + intent: a new case to author when nothing in the catalog fits. name is short kebab-case. intent is a plain-English test intent written like the catalog ones: self-sufficient (it must work in a fresh session starting from its own page, since it will also replay standalone), parameterized with {{var}} placeholders instead of literal data, and ending with a verifiable outcome ("...and verify X"). A delete intent must confirm any confirmation dialog and verify the entity no longer appears.

Sort the steps into:

- chain: the steps in the order the description implies.
- cleanup: steps that undo what the chain created, in reverse order of creation. These run even when the chain fails. Every chain step that creates an entity should have a matching delete here — reused from the catalog when one exists, authored otherwise — unless the description explicitly says to keep the data.

Also produce:

- name: a short kebab-case name for the flow, derived from the description.
- vars: shared {{var}} defaults for the whole flow. Give each var a default that is unique per run by embedding {{stamp}} (a per-run timestamp), e.g. "name": "gh-{{stamp}}". Shared vars are what wire the chain together — the case that creates {{name}} and every case that uses or deletes {{name}} must use the same var.

Saved cases:
{{catalog}}
