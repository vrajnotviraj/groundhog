"""Feature-scoped, budgeted BFS: app → Neo4j.

Per page: pruned snapshot → deterministic link harvest (zero LLM) → one FAST
observe call → execute only safe nav-kind clicks to discover JS transitions.
Mutation/destructive elements enter the graph but are NEVER executed here —
those edges are learned only from real test runs.
"""

from rich.console import Console

from groundhog import config
from groundhog.browser.actions import goto_app, settle
from groundhog.browser.session import Session
from groundhog.graph import store
from groundhog.graph.ingest import ingest_crawl

console = Console()

SKIP_LINKS = ("logout", "signout", "sign-out", "mailto:", "tel:", "http")
NAV_CLICKS_PER_PAGE = 4


def _harvest_links(page) -> list[dict]:
    """Same-origin <a href> → nav edges, zero LLM."""
    anchors = page.eval_on_selector_all(
        "a[href]", "els => els.map(e => ({href: e.getAttribute('href'), text: (e.textContent||'').trim()}))")
    out = []
    for a in anchors:
        href = (a["href"] or "").strip()
        # "//x" is protocol-relative (an external host, not an app path) — it
        # slips past the "/" check and pollutes the graph with bogus page keys.
        if not href.startswith("/") or href.startswith("//") \
                or any(s in href.lower() for s in SKIP_LINKS):
            continue
        out.append({"key": store.page_key(href), "text": a["text"][:60]})
    return out


def crawl(scope: str = "/", max_pages: int | None = None, headless: bool = True) -> dict:
    max_pages = max_pages or config.CRAWL_MAX_PAGES
    scope = "/" + scope.strip("/") if scope.strip("/") else "/"
    stats = {"pages": 0, "elements": 0, "transitions": 0}

    with Session(headless=headless) as session:
        session.ensure_logged_in()
        page = session.page
        root = f"/:ws{scope}" if scope != "/" else "/:ws/home"
        in_scope = (lambda key: key.startswith(f"/:ws{scope}")) if scope != "/" else (lambda key: key.startswith("/:ws"))

        queue: list[tuple[str, int]] = [(root, 0)]
        seen = {root}
        try:
            _bfs(page, session, queue, seen, in_scope, max_pages, stats)
        except KeyboardInterrupt:
            # Ctrl-C on a long crawl: every finished page is already ingested,
            # so stop cleanly and keep the graph instead of dying mid-BFS.
            console.print(f"[yellow]interrupted — keeping {stats['pages']} crawled page(s)[/]")
    return stats


def _bfs(page, session, queue, seen, in_scope, max_pages: int, stats: dict) -> None:
    while queue and stats["pages"] < max_pages:
        key, depth = queue.pop(0)
        url = f"{config.BASE_URL}{key.replace('/:ws', '/' + session.ws)}"
        try:
            goto_app(page, url)
        except Exception as e:
            console.print(f"  [red]✗[/] {key} — {str(e).splitlines()[0]}")
            continue
        landed = store.page_key(page.url)
        console.print(f"[cyan]crawl[/] {landed} (depth {depth})")
        stats["pages"] += 1

        links = _harvest_links(page)
        from groundhog.crawl.observe import observe

        elements = observe(page)
        transitions = [(f'role=link[name="{l["text"]}"]', "click",
                        f"{config.BASE_URL}{l['key']}") for l in links if l["text"]]

        # Execute only safe nav clicks to surface JS-driven transitions.
        clicked = 0
        for el in elements:
            if el.kind != "nav" or clicked >= NAV_CLICKS_PER_PAGE:
                continue
            before = page.url
            try:
                page.locator(el.selector).first.click(timeout=3000)
                settle(page)
            except Exception:
                continue
            clicked += 1
            if store.page_key(page.url) != store.page_key(before):
                transitions.append((el.selector, "click", page.url))
                _enqueue(store.page_key(page.url), depth + 1, queue, seen, in_scope)
                goto_app(page, before)

        ingest_crawl(page.url if landed == key else url, page.title(), elements, transitions)
        stats["elements"] += len(elements)
        stats["transitions"] += len(transitions)

        if depth < config.CRAWL_MAX_DEPTH:
            for l in links:
                _enqueue(l["key"], depth + 1, queue, seen, in_scope)


def _enqueue(key: str, depth: int, queue: list, seen: set, in_scope) -> None:
    if key not in seen and in_scope(key):
        seen.add(key)
        queue.append((key, depth))
