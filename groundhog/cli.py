"""groundhog — AI-authored, deterministically-replayed web tests."""

import json
import re
import secrets
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from groundhog import config, db, events
from groundhog.cases import store
from groundhog.checks import (
    REQUIRED,
    check_app,
    check_chromium,
    check_env,
    check_jev,
    check_login,
    check_mongo,
    placeholders,
)

app = typer.Typer(no_args_is_help=True, add_completion=False)
flow_app = typer.Typer(no_args_is_help=True, add_completion=False)
db_app = typer.Typer(no_args_is_help=True, add_completion=False)
app.add_typer(flow_app, name="flow", help="Chain saved cases: shared vars, always-run cleanup.")
app.add_typer(db_app, name="db", help="The Mongo database the console reads.")
console = Console()
RUN_ID = typer.Option(None, help="id of the run document to write events to; created when omitted")


def _parse_vars(pairs: list[str]) -> dict[str, str]:
    return dict(p.split("=", 1) for p in pairs)


def inventory() -> str:
    return f"cases: {db.cases().count_documents({})} · flows: {db.flows().count_documents({})}"


@contextmanager
def recorded(run_id: str | None, kind: str, target: str, vars: dict, intent: str | None = None):
    """Open a run document for the command, close it as error if the command raises, end on its id."""
    if not re.match(store.NAME, target):
        console.print(f"[red]{escape(target)} is not a valid name: use lowercase letters, digits and dashes[/]")
        raise typer.Exit(2)
    run_id = events.start(run_id, kind, target, vars, intent)
    try:
        yield
    except typer.Exit:
        raise
    except RuntimeError as e:
        events.finish("error", error=str(e))
        console.print(f"[red]{escape(str(e))}[/]")
        raise typer.Exit(2)
    except (Exception, KeyboardInterrupt) as e:
        events.finish("error", error=str(e) or type(e).__name__)
        raise
    finally:
        console.print(f"run {run_id}", highlight=False)


def saved(load, name: str):
    """Load a saved case or flow, or end the command with one red line when there is none."""
    try:
        return load(name)
    except KeyError as e:
        console.print(f"[red]{escape(e.args[0])}[/]")
        events.finish("error", error=e.args[0])
        raise typer.Exit(1)


def verdict(passed: bool) -> str:
    return "[green]PASSED[/]" if passed else "[red]FAILED[/]"


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
    mongo_ok, detail = check_mongo()
    line(mongo_ok, detail)

    login_ok = env_ok and chromium_ok and app_ok
    if login_ok:
        login_ok, detail = check_login()
        line(login_ok, detail)
    else:
        console.print("  [dim]·[/] login — skipped until the checks above pass")

    console.print(f"  [dim]·[/] {inventory()}")
    console.print("\nNext:\n"
                  "  ./start.sh   starts the console\n"
                  '  uv run groundhog new "create an SMS template named {{name}} and verify it appears '
                  'in the templates list" --name my-first-case --var name=gh-1\n'
                  "  uv run groundhog run my-first-case --var name=gh-2\n"
                  "  uv run groundhog flow run template-lifecycle", markup=False)
    raise typer.Exit(0 if env_ok and chromium_ok and app_ok and jev_ok and mongo_ok and login_ok else 1)


@app.command()
def run(name: str, var: list[str] = typer.Option([], help="template var, e.g. --var name=gh-test"),
        no_heal: bool = typer.Option(False, help="fail instead of trying to heal a drifted step"),
        headed: bool = typer.Option(False, help="show the browser"), run_id: str = RUN_ID):
    """Replay a saved case — static, zero AI until something drifts."""
    from groundhog.browser.session import Session
    from groundhog.runner.replay import run_case

    vars = _parse_vars(var)
    with recorded(run_id, "run", name, vars):
        case = saved(store.load, name)
        if missing := store.missing_vars(case, vars):
            # A bare run types literal {{braces}} into the app; a fresh per-run value is
            # what a create-style case wants. Delete-style cases need a real --var.
            stamp = datetime.now(timezone.utc).strftime("%H%M%S")
            vars |= {m: f"gh-{stamp}" for m in missing}
            events.record(vars=vars)
            console.print("[dim]using " + " ".join(f"--var {m}=gh-{stamp}" for m in missing) + "[/]")
        with Session(headless=not headed) as session:
            session.ensure_logged_in()
            result = run_case(case, session, vars=vars, heal=not no_heal)

        events.finish("passed" if result.passed else "failed", total_ms=result.total_ms,
                      healed=result.healed, modes=[s.mode for s in result.steps])
        console.print(f"\n{verdict(result.passed)} in {result.total_ms}ms · {result.healed} healed")
        raise typer.Exit(0 if result.passed else 1)


@app.command()
def new(intent: str, name: str = typer.Option(None, help="case name (kebab-case); derived from intent if omitted"),
        var: list[str] = typer.Option([], help="concrete value for a {{var}} in the intent, e.g. --var name=gh-1; "
                                               "the saved case is re-parameterized automatically"),
        start: str = typer.Option("/:ws/home", help="path to open before the agent starts"),
        verify: bool = typer.Option(False, help="after saving, replay the case once to prove it works"),
        headed: bool = typer.Option(False, help="show the browser"), run_id: str = RUN_ID):
    """Author a new case from a natural-language intent (agentic, one-time cost)."""
    from groundhog.agent.author import _derive_name, author_case, verify_case

    parsed = _parse_vars(var)
    name = name or _derive_name(intent)
    clock = time.monotonic()
    with recorded(run_id, "author", name, parsed, intent):
        case = author_case(intent, name=name, headless=not headed, vars=parsed, start=start)

        modes, passed = [], True
        if verify:
            result = verify_case(case, vars=parsed, headless=not headed)
            modes, passed = [s.mode for s in result.steps], result.passed
        events.finish("passed" if passed else "failed", total_ms=int((time.monotonic() - clock) * 1000),
                      healed=0, modes=modes)
        if not passed:
            broken = "; ".join(s.description for s in result.steps if s.mode == "failed") or "see steps above"
            console.print(f"[red]verification failed[/] — {case.name} is saved but did not replay cleanly: {broken}. "
                          "Run `groundhog run` to let it heal, or edit the case JSON.")
            raise typer.Exit(1)
        if verify:
            console.print(f"[green]verified[/] {case.name} replays cleanly against fresh data")
        console.print(f"\n{verdict(True)} {case.name} saved")


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
    console.print_json(json.dumps(saved(store.load, name).model_dump()))


@flow_app.command("run")
def flow_run(name: str, var: list[str] = typer.Option([], help="shared template var, e.g. --var name=gh-test"),
             no_heal: bool = typer.Option(False, help="fail instead of trying to heal a drifted step"),
             headed: bool = typer.Option(False, help="show the browser"), run_id: str = RUN_ID):
    """Replay a flow: chain cases in one session, then cleanup — always."""
    from groundhog.browser.session import Session
    from groundhog.runner.flow import run_flow

    vars = _parse_vars(var)
    with recorded(run_id, "flow", name, vars):
        flow = saved(store.load_flow, name)
        with Session(headless=not headed) as session:
            session.ensure_logged_in()
            result = run_flow(flow, session, vars=vars, heal=not no_heal)

        ran = [cr.result for cr in result.runs if cr.result]
        events.finish("passed" if result.passed else "failed", total_ms=result.total_ms,
                      healed=sum(r.healed for r in ran), modes=[s.mode for r in ran for s in r.steps])
        console.print(f"\n{verdict(result.passed)} in {result.total_ms}ms · {len(result.runs)} case(s)")
        raise typer.Exit(0 if result.passed else 1)


@flow_app.command("new")
def flow_new(intent: str, name: str = typer.Option(None, help="flow name (kebab-case); derived from intent if omitted"),
             headed: bool = typer.Option(False, help="show the browser"), run_id: str = RUN_ID):
    """Compose a flow from English: reuse saved cases, author the missing ones
    live in one pass, then save the flow — later runs are static."""
    from groundhog.agent.author import _derive_name
    from groundhog.agent.composer import compose_flow

    clock = time.monotonic()
    with recorded(run_id, "compose", name or _derive_name(intent), {}, intent):
        flow = compose_flow(intent, name=name, headless=not headed)
        events.record(target=flow.name)
        events.finish("passed", total_ms=int((time.monotonic() - clock) * 1000), healed=0, modes=[])
        chain = " → ".join(fc.case for fc in flow.chain)
        cleanup = ", ".join(fc.case for fc in flow.cleanup) or "none"
        console.print(f"\n{verdict(True)} saved {flow.name} — chain: {chain} · cleanup: {cleanup} · vars: {flow.vars}")


@flow_app.command("list")
def flow_list():
    """List saved flows."""
    table = Table("name", "chain", "cleanup", "vars", "intent")
    for f in store.list_flows():
        table.add_row(f.name, " → ".join(fc.case for fc in f.chain),
                      ", ".join(fc.case for fc in f.cleanup), json.dumps(f.vars), f.intent)
    console.print(table)


@db_app.command("seed")
def db_seed():
    """Create the indexes and the first admin."""
    from groundhog.passwords import hash_password

    db.ensure_indexes()
    console.print(inventory(), highlight=False)

    if db.users().count_documents({}):
        return
    if not config.ADMIN_EMAIL:
        console.print("[red]ADMIN_EMAIL not set — add it to .env to create the first admin[/]")
        raise typer.Exit(1)
    password = config.ADMIN_PASSWORD or secrets.token_urlsafe(12)
    db.users().insert_one({"_id": uuid.uuid4().hex, "email": config.ADMIN_EMAIL, "role": "admin",
                           "password_hash": hash_password(password), "created_at": events.now()})
    console.print(f"created admin {config.ADMIN_EMAIL}", highlight=False)
    if not config.ADMIN_PASSWORD:
        console.print(f"generated password (shown once): {password}", markup=False, highlight=False)


@app.command()
def serve(port: int = typer.Option(8000, help="port to listen on")):
    """Serve the console and its API."""
    import uvicorn

    uvicorn.run("groundhog.api.app:app", port=port)


if __name__ == "__main__":
    app()
