"""groundhog — AI-authored, deterministically-replayed web tests."""

import json

import typer
from rich.console import Console
from rich.table import Table

from groundhog.cases import store

app = typer.Typer(no_args_is_help=True, add_completion=False)
flow_app = typer.Typer(no_args_is_help=True, add_completion=False)
app.add_typer(flow_app, name="flow", help="Chain saved cases: shared vars, always-run cleanup.")
console = Console()


def _parse_vars(pairs: list[str]) -> dict[str, str]:
    return dict(p.split("=", 1) for p in pairs)


def _need_llm() -> None:
    """Fail fast with a hint instead of a deep SDK auth traceback mid-run."""
    from groundhog import config

    if not config.ANTHROPIC_API_KEY:
        console.print("[red]ANTHROPIC_API_KEY is not set — add it to .env[/]")
        raise typer.Exit(2)


def _need_graph() -> None:
    """Fail fast when Neo4j is required (crawl/suggest) rather than optional."""
    from groundhog import config
    from groundhog.graph import store

    try:
        store.driver()
    except Exception:
        console.print(f"[red]Neo4j is not reachable at {config.NEO4J_URI} — docker compose up -d[/]")
        raise typer.Exit(2)


@app.command()
def run(name: str, var: list[str] = typer.Option([], help="template var, e.g. --var name=gh-test"),
        no_heal: bool = typer.Option(False, help="fail instead of waking the healer"),
        headed: bool = typer.Option(False, help="show the browser")):
    """Replay a saved case — static, zero LLM until something drifts."""
    from groundhog.browser.session import Session
    from groundhog.runner.replay import run_case
    from groundhog.runner.report import write_report
    from groundhog.llm import client

    case = store.load(name)
    with Session(headless=not headed) as session:
        session.ensure_logged_in()
        result = run_case(case, session, vars=_parse_vars(var), heal=not no_heal)

    report = write_report(result, tokens=client.usage_snapshot())
    console.print(f"\n[{'green' if result.passed else 'red'}]{'PASSED' if result.passed else 'FAILED'}[/] "
                  f"in {result.total_ms}ms · {result.healed} healed · report: {report}")
    raise typer.Exit(0 if result.passed else 1)


@app.command()
def new(intent: str, name: str = typer.Option(None, help="case name (kebab-case); derived from intent if omitted"),
        var: list[str] = typer.Option([], help="concrete value for a {{var}} in the intent, e.g. --var name=gh-1; "
                                               "the saved case is re-parameterized automatically"),
        headed: bool = typer.Option(False, help="show the browser")):
    """Author a new case from a natural-language intent (agentic, one-time cost)."""
    _need_llm()
    from groundhog.agent.executor import author_case

    case = author_case(intent, name=name, headless=not headed, vars=_parse_vars(var))
    console.print(f"[green]saved[/] cases/{case.name}.json — {len(case.steps)} steps, {len(case.assertions)} assertions")


@app.command("list")
def list_():
    """List saved cases."""
    table = Table("name", "steps", "runs", "heals", "intent")
    for c in store.list_cases():
        table.add_row(c.name, str(len(c.steps)), str(c.meta.runs), str(len(c.meta.heals)), c.intent)
    console.print(table)


@app.command()
def show(name: str):
    """Print a case JSON."""
    console.print_json(json.dumps(store.load(name).model_dump()))


@flow_app.command("run")
def flow_run(name: str, var: list[str] = typer.Option([], help="shared template var, e.g. --var name=gh-test"),
             no_heal: bool = typer.Option(False, help="fail instead of waking the healer"),
             headed: bool = typer.Option(False, help="show the browser")):
    """Replay a flow: chain cases in one session, then cleanup — always."""
    from groundhog.browser.session import Session
    from groundhog.llm import client
    from groundhog.runner.flow import run_flow
    from groundhog.runner.report import write_flow_report

    flow = store.load_flow(name)
    with Session(headless=not headed) as session:
        session.ensure_logged_in()
        result = run_flow(flow, session, vars=_parse_vars(var), heal=not no_heal)

    report = write_flow_report(result, tokens=client.usage_snapshot())
    console.print(f"\n[{'green' if result.passed else 'red'}]{'PASSED' if result.passed else 'FAILED'}[/] "
                  f"in {result.total_ms}ms · {len(result.runs)} case(s) · report: {report}")
    raise typer.Exit(0 if result.passed else 1)


@flow_app.command("new")
def flow_new(intent: str, name: str = typer.Option(None, help="flow name (kebab-case); derived from intent if omitted")):
    """Compose a flow from English — picks from saved cases, never invents them."""
    _need_llm()
    from groundhog.agent.composer import compose_flow

    try:
        flow = compose_flow(intent, name=name)
    except ValueError as e:
        console.print(f"[red]{e}[/]")
        raise typer.Exit(2)
    chain = " → ".join(fc.case for fc in flow.chain)
    cleanup = ", ".join(fc.case for fc in flow.cleanup) or "none"
    console.print(f"[green]saved[/] flows/{flow.name}.json — chain: {chain} · cleanup: {cleanup} · vars: {flow.vars}")


@flow_app.command("list")
def flow_list():
    """List saved flows."""
    table = Table("name", "chain", "cleanup", "vars", "intent")
    for f in store.list_flows():
        table.add_row(f.name, " → ".join(fc.case for fc in f.chain),
                      ", ".join(fc.case for fc in f.cleanup), json.dumps(f.vars), f.intent)
    console.print(table)


@app.command()
def crawl(scope: str = typer.Option("/", help="restrict to one feature, e.g. /templates"),
          max_pages: int = typer.Option(None), headed: bool = typer.Option(False),
          docs: bool = typer.Option(False, help="also read the product docs into a Feature relationship layer")):
    """Crawl the app into the Neo4j knowledge graph (feature-scoped, budgeted)."""
    _need_llm()
    _need_graph()  # both the crawl and the --docs pass write through the graph
    from groundhog.crawl.crawler import crawl as do_crawl

    stats = do_crawl(scope=scope, max_pages=max_pages, headless=not headed)
    console.print(f"[green]crawled[/] {stats['pages']} pages, {stats['elements']} elements, {stats['transitions']} transitions")
    if docs:
        from groundhog.crawl.docs import learn_features

        try:
            d = learn_features()
            console.print(f"[green]features[/] {d['features']} features, {d['relations']} relations")
        except Exception as e:  # a failed docs pass never fails the crawl
            console.print(f"[yellow]docs pass skipped — {e}[/]")


@app.command()
def suggest():
    """Infer untested scenarios from the graph (coverage gaps + asymmetries)."""
    _need_llm()
    _need_graph()
    from groundhog.graph.queries import suggestions

    for s in suggestions():
        console.print(f"[cyan]•[/] {s}")


@app.command()
def doctor():
    """Check the environment: API key, app reachability, Neo4j, login flow."""
    import httpx

    from groundhog import config

    failed = []

    def check(label: str, passed: bool, hint: str) -> None:
        if not passed:
            failed.append(label)
        console.print(f"  [{'green' if passed else 'red'}]{'✓' if passed else '✗'}[/] {label}"
                      + ("" if passed else f" — {hint}"))

    check("ANTHROPIC_API_KEY set", bool(config.ANTHROPIC_API_KEY), "add it to .env")
    try:
        httpx.get(config.BASE_URL, follow_redirects=True, timeout=5)
        reachable = True
    except Exception:
        reachable = False
    check(f"app reachable ({config.BASE_URL})", reachable, "check BASE_URL in .env")
    try:
        from groundhog.graph import store

        store.driver()
        graph = True
    except Exception:
        graph = False
    check(f"Neo4j reachable ({config.NEO4J_URI})", graph,
          "docker compose up -d (crawl/suggest need it; run/new degrade gracefully)")
    check("login flow present (.auth/login.json)", (config.AUTH_DIR / "login.json").exists(),
          "seed one (see README)")
    raise typer.Exit(1 if failed else 0)


if __name__ == "__main__":
    app()
