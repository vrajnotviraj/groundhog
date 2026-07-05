"""Neo4j driver + upserts — the single write path for every writer
(crawl, executor, healer). Re-crawls and re-runs upsert by key, so ingestion
is idempotent; last_seen marks staleness.

Schema:
  (:Page    {key, url_pattern, title, section, last_seen})
  (:Element {key, selector, role, name, kind, description, last_seen})
  (:Case    {name, intent, file, last_run, status})
  (:Feature {name, summary, last_seen})   — name is always a Page.section value
  (:Page)-[:HAS]->(:Element)   (:Page)-[:IN_FEATURE]->(:Feature)
  (:Feature)-[:RELATED_TO {how, source, last_seen}]->(:Feature)
  (:Element)-[:LEADS_TO {action}]->(:Page)
  (:Case)-[:COVERS]->(:Page)   (:Case)-[:EXERCISES]->(:Element)
"""

import re

from groundhog import config

WS_ID = re.compile(r"/FY[A-Z0-9]{6,}(?=/|$)")

_driver = None


def driver():
    global _driver
    if _driver is None:
        from neo4j import GraphDatabase

        _driver = GraphDatabase.driver(config.NEO4J_URI,
                                       auth=(config.NEO4J_USER, config.NEO4J_PASS))
        _driver.verify_connectivity()
    return _driver


def run(query: str, **params):
    with driver().session() as s:
        return list(s.run(query, **params))


def page_key(url: str) -> str:
    """Normalized stateKey: /FYAP…/home → /:ws/home. Strips origin, query, hash."""
    path = re.sub(r"^https?://[^/]+", "", url).split("?")[0].split("#")[0]
    path = WS_ID.sub("/:ws", path)
    return path.rstrip("/") or "/"


def section(key: str) -> str:
    """First feature segment: /:ws/templates/new → templates."""
    parts = [p for p in key.split("/") if p and p != ":ws"]
    return parts[0] if parts else "home"


def element_key(page: str, selector: str) -> str:
    return f"{page}|{selector}"


def upsert_page(key: str, title: str = "") -> None:
    run("""MERGE (p:Page {key: $key})
           SET p.url_pattern = $key, p.section = $section, p.last_seen = datetime()
           FOREACH (_ IN CASE WHEN $title <> '' THEN [1] ELSE [] END | SET p.title = $title)""",
        key=key, title=title, section=section(key))


def upsert_element(page: str, selector: str, role: str = "", name: str = "",
                   kind: str = "nav", description: str = "") -> None:
    run("""MERGE (p:Page {key: $page})
           ON CREATE SET p.url_pattern = $page, p.section = $section, p.last_seen = datetime()
           MERGE (e:Element {key: $ekey})
           SET e.selector = $selector, e.role = $role, e.name = $name,
               e.kind = $kind, e.description = $description, e.last_seen = datetime()
           MERGE (p)-[:HAS]->(e)""",
        page=page, section=section(page), ekey=element_key(page, selector),
        selector=selector, role=role, name=name, kind=kind, description=description)


def upsert_transition(page: str, selector: str, action: str, to_page: str) -> None:
    run("""MERGE (e:Element {key: $ekey})
           SET e.last_seen = datetime()
           MERGE (t:Page {key: $to})
           ON CREATE SET t.url_pattern = $to, t.section = $tsection, t.last_seen = datetime()
           MERGE (e)-[r:LEADS_TO]->(t)
           SET r.action = $action""",
        ekey=element_key(page, selector), to=to_page, tsection=section(to_page), action=action)


def upsert_feature(name: str, summary: str = "") -> None:
    # Page linking rides the same write: name IS a section, so IN_FEATURE
    # needs no second query.
    run("""MERGE (f:Feature {name: $name})
           SET f.last_seen = datetime()
           FOREACH (_ IN CASE WHEN $summary <> '' THEN [1] ELSE [] END | SET f.summary = $summary)
           WITH f MATCH (p:Page {section: $name}) MERGE (p)-[:IN_FEATURE]->(f)""",
        name=name, summary=summary)


def upsert_feature_relation(frm: str, to: str, how: str, source: str) -> None:
    run("""MERGE (a:Feature {name: $frm})
           MERGE (b:Feature {name: $to})
           MERGE (a)-[r:RELATED_TO]->(b)
           SET r.how = $how, r.source = $source, r.last_seen = datetime()""",
        frm=frm, to=to, how=how, source=source)


def upsert_case(name: str, intent: str, status: str = "") -> None:
    run("""MERGE (c:Case {name: $name})
           SET c.intent = $intent, c.file = $file, c.last_run = datetime()
           FOREACH (_ IN CASE WHEN $status <> '' THEN [1] ELSE [] END | SET c.status = $status)""",
        name=name, intent=intent, file=f"cases/{name}.json", status=status)


def link_case(name: str, pages: list[str], elements: list[str]) -> None:
    run("""MATCH (c:Case {name: $name})
           FOREACH (k IN $pages | MERGE (p:Page {key: k}) MERGE (c)-[:COVERS]->(p))
           FOREACH (k IN $elements | MERGE (e:Element {key: k}) MERGE (c)-[:EXERCISES]->(e))""",
        name=name, pages=pages, elements=elements)
