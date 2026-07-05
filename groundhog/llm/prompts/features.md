You read product documentation for a notification-infrastructure web app and distill it into a small feature-relationship map for a test-planning graph.

You are given several docs pages, each under a `## <slug>` header. The app's feature vocabulary is fixed — use ONLY these feature names, exactly as written:

{{sections}}

Return:
- features: each listed feature the docs actually describe, with a one-line summary of what it does.
- relations: how features depend on or feed each other (e.g. an integration feeds routing, routing consumes events, templates render inside events).
  - from_feature / to_feature: names from the list above. Never invent a name; if the docs use a synonym, map it to the closest listed name or omit the relation.
  - how: one sentence a tester can act on (e.g. "a route needs a template of the matching channel before it can fire").
  - source: the `## <slug>` header of the page the claim came from.

One edge per pair of features. Omit relations the docs do not state — an invented edge misleads every future test plan.
