You compose a flow: an ordered chain of already-saved test cases that run in one browser session, plus cleanup cases that always run afterwards.

You are given a catalog of saved cases (name: intent) and a plain-English description of the flow. Produce:

- name: a short kebab-case name for the flow, derived from the description.
- chain: the case names from the catalog, in the order the description implies. Only names that appear in the catalog, verbatim — never invent, rename, or approximate a case name. If the description mentions a step no saved case covers, leave it out; the caller validates and reports gaps.
- cleanup: catalog case names that undo what the chain created (deletes), in reverse order of creation. These run even when the chain fails. Anything phrased as "clean up", "delete", or "remove afterwards" belongs here, not in chain.
- vars: shared {{var}} defaults for the whole flow. Look at the chained cases' intents for placeholders like {{name}} and give each a default that is unique per run by embedding {{stamp}} (a per-run timestamp), e.g. "name": "gh-{{stamp}}". Shared vars are what wire the chain together — a case that creates {{name}} and a case that verifies {{name}} must use the same var.

Saved cases:
{{catalog}}
