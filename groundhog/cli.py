"""groundhog — AI-authored, deterministically-replayed web tests."""

import json

import typer
from rich.console import Console
from rich.table import Table

from groundhog.cases import store

app = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console()

MODE_STYLE = {"static": "dim", "fallback": "yellow", "healed": "magenta", "failed": "red", "skipped": "dim"}


def _parse_vars(pairs: list[str]) -> dict[str, str]:
    return dict(p.split("=", 1) for p in pairs)


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

    for i, s in enumerate(result.steps, 1):
        style = MODE_STYLE.get(s.mode, "")
        console.print(f"  [{style}]{s.mode:>8}[/] {i}. {s.description}" + (f" [red]— {s.error}[/]" if s.error else ""))
    for a in result.assertions:
        console.print(f"  [{'green' if a.passed else 'red'}]{'✓' if a.passed else '✗'}[/] {a.assertion} — {a.reasoning}")

    report = write_report(result, tokens=client.usage_snapshot())
    console.print(f"\n[{'green' if result.passed else 'red'}]{'PASSED' if result.passed else 'FAILED'}[/] "
                  f"in {result.total_ms}ms · {result.healed} healed · report: {report}")
    raise typer.Exit(0 if result.passed else 1)


@app.command()
def new(intent: str, name: str = typer.Option(None, help="case name (kebab-case); derived from intent if omitted"),
        headed: bool = typer.Option(False, help="show the browser")):
    """Author a new case from a natural-language intent (agentic, one-time cost)."""
    from groundhog.agent.author import author_case

    case = author_case(intent, name=name, headless=not headed)
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


@app.command()
def crawl(scope: str = typer.Option("/", help="restrict to one feature, e.g. /templates"),
          max_pages: int = typer.Option(None), headed: bool = typer.Option(False)):
    """Crawl the app into the Neo4j knowledge graph (feature-scoped, budgeted)."""
    from groundhog.crawl.crawler import crawl as do_crawl

    stats = do_crawl(scope=scope, max_pages=max_pages, headless=not headed)
    console.print(f"[green]crawled[/] {stats['pages']} pages, {stats['elements']} elements, {stats['transitions']} transitions")


@app.command()
def suggest():
    """Infer untested scenarios from the graph (coverage gaps + asymmetries)."""
    from groundhog.graph.queries import suggestions

    for s in suggestions():
        console.print(f"[cyan]•[/] {s}")


if __name__ == "__main__":
    app()
