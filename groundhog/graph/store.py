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

import atexit
import re
from urllib.parse import urlparse

from groundhog import config

WS_ID = re.compile(r"/FY[A-Z0-9]{6,}(?=/|$)")

# A few seconds, not library defaults (~30s) — a down/firewalled/hung Neo4j
# must fail fast, since every caller treats the graph as an accelerator and
# wraps it in try/except, never a wait.
CONNECT_TIMEOUT_S = 5
MAX_RETRY_TIME_S = 5

_driver = None
_unavailable: Exception | None = None


def driver():
    """Raises fast when Neo4j is unreachable — cli._need_graph() relies on
    that. Once a connection attempt fails, the failure is cached for the rest
    of the process so every later call (one per ingest, one per replay) fails
    immediately instead of re-paying the connection timeout."""
    global _driver, _unavailable
    if _driver is not None:
        return _driver
    if _unavailable is not None:
        raise _unavailable
    from neo4j import GraphDatabase

    try:
        d = GraphDatabase.driver(config.NEO4J_URI,
                                 auth=(config.NEO4J_USER, config.NEO4J_PASS),
                                 connection_timeout=CONNECT_TIMEOUT_S,
                                 max_transaction_retry_time=MAX_RETRY_TIME_S,
                                 # gaps in a fresh graph (no Feature nodes yet) are
                                 # normal — don't have the server generate
                                 # notifications for them
                                 notifications_min_severity="OFF")
        d.verify_connectivity()
    except Exception as e:
        _unavailable = e
        raise
    _driver = d
    return _driver


@atexit.register
def _close() -> None:
    if _driver is not None:
        _driver.close()


def run(query: str, **params):
    with driver().session() as s:
        return list(s.run(query, **params))


def page_key(url: str) -> str:
    """Normalized stateKey: /FYAP…/home → /:ws/home. Strips origin, query, hash."""
    path = WS_ID.sub("/:ws", urlparse(url).path)
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
