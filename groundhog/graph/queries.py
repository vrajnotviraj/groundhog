"""Read side of the graph: planner slices, healer context, coverage, suggestions."""

import re

from groundhog.graph import store


def slice_for_intent(intent: str, max_pages: int = 5, max_elements: int = 12) -> str:
    """Pages (+ their elements + where those elements lead) relevant to the
    intent's words — the planner's ≤ ~1.5k-token context. Empty string when
    the graph knows nothing relevant."""
    words = [w for w in re.findall(r"[a-z]{3,}", intent.lower())
             if w not in {"the", "and", "verify", "that", "with", "named", "create", "new"}]
    if not words:
        return ""
    rows = store.run("""
        MATCH (p:Page)
        WITH p, size([w IN $words WHERE p.key CONTAINS w
                      OR toLower(coalesce(p.title,'')) CONTAINS w
                      OR coalesce(p.section,'') CONTAINS w]) AS hits
        WHERE hits > 0
        // One page per feature section — the shortest key is the list/entry
        // page, which holds the create/nav elements a plan needs. Detail pages
        // would otherwise crowd out other sections on multi-entity intents.
        WITH p, hits ORDER BY size(p.key) ASC, p.last_seen DESC
        WITH p.section AS sec, max(hits) AS hits, collect(p)[0] AS p
        ORDER BY hits DESC, size(p.key) ASC LIMIT $max_pages
        OPTIONAL MATCH (p)-[:HAS]->(e:Element)
        OPTIONAL MATCH (e)-[l:LEADS_TO]->(t:Page)
        RETURN p.key AS page, p.title AS title,
               collect({selector: e.selector, kind: e.kind, name: e.name,
                        description: e.description, to: t.key})[..$max_elements] AS elements""",
        words=words, max_pages=max_pages, max_elements=max_elements)
    if not rows:
        return ""
    lines = []
    for r in rows:
        lines.append(f"page {r['page']}" + (f" — {r['title']}" if r["title"] else ""))
        for e in r["elements"]:
            if not e["selector"]:
                continue
            to = f" → {e['to']}" if e["to"] else ""
            lines.append(f"  [{e['kind']}] {e['selector']} — {e['description'] or e['name']}{to}")
    # Docs-learned cross-feature hints for multi-entity flows; empty (zero
    # cost) until a docs pass has created Feature nodes.
    secs = sorted({store.section(r["page"]) for r in rows})
    feats = store.run("""
        MATCH (f:Feature)-[r:RELATED_TO]-(g:Feature) WHERE f.name IN $secs
        RETURN DISTINCT f.name AS a, g.name AS b, r.how AS how LIMIT 8""", secs=secs)
    if feats:
        lines.append("related features:")
        lines += [f"  {r['a']} — {r['b']}: {r['how']}" for r in feats]
    return "\n".join(lines)


def coverage_gaps() -> dict:
    """Structural gaps: uncovered pages, unexercised mutations, and section
    asymmetries (a covered flow one section has and a sibling section lacks)."""
    pages = [r["key"] for r in store.run(
        "MATCH (p:Page) WHERE NOT (:Case)-[:COVERS]->(p) RETURN p.key AS key ORDER BY p.key LIMIT 20")]
    mutations = [dict(r) for r in store.run("""
        MATCH (p:Page)-[:HAS]->(e:Element)
        WHERE e.kind IN ['mutation', 'destructive'] AND NOT (:Case)-[:EXERCISES]->(e)
        RETURN p.key AS page, e.selector AS selector, e.kind AS kind,
               coalesce(e.description, e.name) AS what
        ORDER BY e.kind DESC LIMIT 20""")]
    asymmetries = [dict(r) for r in store.run("""
        MATCH (c:Case)-[:EXERCISES]->(e:Element)<-[:HAS]-(p:Page)
        MATCH (p2:Page)-[:HAS]->(e2:Element)
        WHERE p2.section <> p.section AND e2.name = e.name AND e2.name <> ''
          AND NOT (:Case)-[:EXERCISES]->(e2)
        RETURN DISTINCT p.section AS covered_section, p2.section AS uncovered_section,
               e2.name AS control, p2.key AS page LIMIT 10""")]
    return {"uncovered_pages": pages, "unexercised_mutations": mutations, "asymmetries": asymmetries}


def suggestions() -> list[str]:
    """Coverage gaps phrased as runnable test intents — one SMART call."""
    import json

    from pydantic import BaseModel

    from groundhog.llm import client

    gaps = coverage_gaps()
    if not any(gaps.values()):
        return ["graph has no coverage gaps recorded — crawl first (groundhog crawl --scope /<feature>)"]

    class Suggestion(BaseModel):
        name: str
        intent: str

    class Suggestions(BaseModel):
        suggestions: list[Suggestion]

    system = ("You review test-coverage gaps for a notification-infrastructure web app "
              "(workspaces, templates, workflows, channels, analytics) and propose concrete "
              "browser test intents a QA engineer could author against the LIVE app.\n\n"
              "Each intent is ONE action-oriented flow with a verifiable outcome, e.g. "
              "\"create a workflow named {{name}} and verify it appears in the workflows list\". "
              "Prefer flows exercising the unexercised mutation elements and section asymmetries "
              "(a flow covered in one section but not its sibling). Avoid destructive flows on "
              "data you did not create. 3-6 high-value suggestions; names are short kebab-case.")
    result = client.parse(
        user=f"Coverage gaps from the app graph:\n{json.dumps(gaps, indent=2)}",
        output_model=Suggestions, system=system, model=client.SMART,
    )
    return [f"{s.name}: {s.intent}" for s in result.suggestions]
