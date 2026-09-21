"""groundhog — AI-authored, deterministically-replayed web tests."""

import json
from datetime import datetime, timezone

import typer
from dotenv import dotenv_values
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from groundhog import config
from groundhog.cases import store

app = typer.Typer(no_args_is_help=True, add_completion=False)
flow_app = typer.Typer(no_args_is_help=True, add_completion=False)
app.add_typer(flow_app, name="flow", help="Chain saved cases: shared vars, always-run cleanup.")
console = Console()

REQUIRED = ["BASE_URL", "LOGIN_USER", "LOGIN_PASS", "LOGIN_WORKSPACE", "TYPESAFE_API_KEY"]


def _parse_vars(pairs: list[str]) -> dict[str, str]:
    return dict(p.split("=", 1) for p in pairs)


# --- init checks: each returns (ok, line to print after the mark) ---

def placeholders() -> dict[str, str]:
    """The values shipped in .env.example, so init can tell an unedited copy apart."""
    try:
        return dict(dotenv_values(config.ROOT / ".env.example"))
    except OSError:
        return {}


def check_env(name: str, value: str, placeholder: str | None) -> tuple[bool, str]:
    if not value:
        return False, f"{name} not set — edit .env"
    if placeholder and value == placeholder:
        return False, f"{name} still the placeholder — edit .env"
    return True, name


def check_chromium() -> tuple[bool, str]:
    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as p:
            p.chromium.launch().close()
    except Exception:
        return False, "Chromium — run: uv run playwright install chromium"
    return True, "Chromium launches"


def check_app() -> tuple[bool, str]:
    import httpx

    try:
        httpx.get(config.BASE_URL, follow_redirects=True, timeout=8)
    except Exception as e:
        return False, f"app unreachable ({config.BASE_URL}) — {e}"
    return True, f"app reachable ({config.BASE_URL})"


def check_jev() -> tuple[bool, str]:
    from groundhog import jev

    try:
        p = jev.ping()
    except Exception as e:
        return False, f"Jev — {e}"
    return True, f"Jev reachable ({p['model']}, {p['latency_ms']}ms)"


def check_login() -> tuple[bool, str]:
    from groundhog.browser.session import Session

    try:
        with Session() as s:
            s.ensure_logged_in()
            return True, (f"logged in as {config.LOGIN_USER} · workspace {s.ws} "
                          f"({config.LOGIN_WORKSPACE}) · session cached in .auth/")
    except Exception as e:
        return False, f"login — {e}"


def inventory() -> str:
    cases = len(list(config.CASES_DIR.glob("*.json"))) if config.CASES_DIR.exists() else 0
    flows = len(list(config.FLOWS_DIR.glob("*.json"))) if config.FLOWS_DIR.exists() else 0
    return f"cases/: {cases} saved · flows/: {flows} saved"


@app.command()
def init():
    """Check everything a first run needs and say exactly what is missing."""
    env = config.ROOT / ".env"
    if not env.exists():
        env.write_text((config.ROOT / ".env.example").read_text())
        console.print("created .env — fill in BASE_URL, LOGIN_USER, LOGIN_PASS, LOGIN_WORKSPACE, "
                      "TYPESAFE_API_KEY and run `groundhog init` again")
        raise typer.Exit(1)

    def line(ok: bool, detail: str) -> None:
        # A failure detail carries an exception message, which may contain [brackets]
        # that rich would read as markup and choke on.
        console.print(f"  [{'green' if ok else 'red'}]{'✓' if ok else '✗'}[/] {escape(detail)}", highlight=False)

    ph = placeholders()
    env_ok = True
    for name in REQUIRED:
        ok, detail = check_env(name, getattr(config, name, ""), ph.get(name))
        env_ok = env_ok and ok
        line(ok, detail)
    if config.ANTHROPIC_API_KEY:
        line(True, "ANTHROPIC_API_KEY")
    else:
        console.print("  [dim]·[/] ANTHROPIC_API_KEY — optional: unlocks `flow new` and lets the agent "
                      "write field values the intent doesn't spell out")

    chromium_ok, detail = check_chromium()
    line(chromium_ok, detail)
    app_ok, detail = check_app()
    line(app_ok, detail)
    jev_ok, detail = check_jev()
    line(jev_ok, detail)

    login_ok = env_ok and chromium_ok and app_ok
    if login_ok:
        login_ok, detail = check_login()
        line(login_ok, detail)
    else:
        console.print("  [dim]·[/] login — skipped until the checks above pass")

    console.print(f"  [dim]·[/] {inventory()}")
    console.print("\nNext:\n"
                  '  uv run groundhog new "create an SMS template named {{name}} and verify it appears '
                  'in the templates list" --name my-first-case --var name=gh-1\n'
                  "  uv run groundhog run my-first-case --var name=gh-2\n"
                  "  uv run groundhog flow run template-lifecycle", markup=False)
    raise typer.Exit(0 if env_ok and chromium_ok and app_ok and jev_ok and login_ok else 1)


@app.command()
def run(name: str, var: list[str] = typer.Option([], help="template var, e.g. --var name=gh-test"),
        no_heal: bool = typer.Option(False, help="fail instead of trying to heal a drifted step"),
        headed: bool = typer.Option(False, help="show the browser")):
    """Replay a saved case — static, zero AI until something drifts."""
    from groundhog.browser.session import Session
    from groundhog.runner.replay import run_case
    from groundhog.runner.report import write_report

    case = store.load(name)
    vars = _parse_vars(var)
    if missing := store.missing_vars(case, vars):
        # A bare run types literal {{braces}} into the app; a fresh per-run value is
        # what a create-style case wants. Delete-style cases need a real --var.
        stamp = datetime.now(timezone.utc).strftime("%H%M%S")
        vars |= {m: f"gh-{stamp}" for m in missing}
        console.print("[dim]using " + " ".join(f"--var {m}=gh-{stamp}" for m in missing) + "[/]")
    with Session(headless=not headed) as session:
        session.ensure_logged_in()
        result = run_case(case, session, vars=vars, heal=not no_heal)

    report = write_report(result)
    console.print(f"\n[{'green' if result.passed else 'red'}]{'PASSED' if result.passed else 'FAILED'}[/] "
                  f"in {result.total_ms}ms · {result.healed} healed · report: {report}")
    raise typer.Exit(0 if result.passed else 1)


@app.command()
def new(intent: str, name: str = typer.Option(None, help="case name (kebab-case); derived from intent if omitted"),
        var: list[str] = typer.Option([], help="concrete value for a {{var}} in the intent, e.g. --var name=gh-1; "
                                               "the saved case is re-parameterized automatically"),
        start: str = typer.Option("/:ws/home", help="path to open before the agent starts"),
        verify: bool = typer.Option(False, help="after saving, replay the case once to prove it works"),
        headed: bool = typer.Option(False, help="show the browser")):
    """Author a new case from a natural-language intent (agentic, one-time cost)."""
    from groundhog.agent.author import author_case

    parsed = _parse_vars(var)
    try:
        case = author_case(intent, name=name, headless=not headed, vars=parsed, start=start)
    except RuntimeError as e:
        console.print(f"[red]{escape(str(e))}[/]")
        raise typer.Exit(2)

    if verify:
        from groundhog.agent.author import verify_case

        result = verify_case(case, vars=parsed, headless=not headed)
        if not result.passed:
            broken = "; ".join(s.description for s in result.steps if s.mode == "failed") or "see steps above"
            console.print(f"[red]verification failed[/] — {case.name} is saved but did not replay cleanly: {broken}. "
                          "Run `groundhog run` to let it heal, or edit the case JSON.")
            raise typer.Exit(1)
        console.print(f"[green]verified[/] {case.name} replays cleanly against fresh data")


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
             no_heal: bool = typer.Option(False, help="fail instead of trying to heal a drifted step"),
             headed: bool = typer.Option(False, help="show the browser")):
    """Replay a flow: chain cases in one session, then cleanup — always."""
    from groundhog.browser.session import Session
    from groundhog.runner.flow import run_flow
    from groundhog.runner.report import write_flow_report

    flow = store.load_flow(name)
    with Session(headless=not headed) as session:
        session.ensure_logged_in()
        result = run_flow(flow, session, vars=_parse_vars(var), heal=not no_heal)

    report = write_flow_report(result)
    console.print(f"\n[{'green' if result.passed else 'red'}]{'PASSED' if result.passed else 'FAILED'}[/] "
                  f"in {result.total_ms}ms · {len(result.runs)} case(s) · report: {report}")
    raise typer.Exit(0 if result.passed else 1)


@flow_app.command("new")
def flow_new(intent: str, name: str = typer.Option(None, help="flow name (kebab-case); derived from intent if omitted"),
             headed: bool = typer.Option(False, help="show the browser")):
    """Compose a flow from English: reuse saved cases, author the missing ones
    live in one pass, then save the flow — later runs are static."""
    from groundhog.agent.composer import compose_flow

    try:
        flow = compose_flow(intent, name=name, headless=not headed)
    except RuntimeError as e:
        console.print(f"[red]{escape(str(e))}[/]")
        raise typer.Exit(2)
    chain = " → ".join(fc.case for fc in flow.chain)
    cleanup = ", ".join(fc.case for fc in flow.cleanup) or "none"
    console.print(f"\n[green]saved[/] flows/{flow.name}.json — chain: {chain} · cleanup: {cleanup} · vars: {flow.vars}")


@flow_app.command("list")
def flow_list():
    """List saved flows."""
    table = Table("name", "chain", "cleanup", "vars", "intent")
    for f in store.list_flows():
        table.add_row(f.name, " → ".join(fc.case for fc in f.chain),
                      ", ".join(fc.case for fc in f.cleanup), json.dumps(f.vars), f.intent)
    console.print(table)


if __name__ == "__main__":
    app()
