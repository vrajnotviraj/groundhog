"""init's env/.env checks, its summary line and db seed, without a browser or network."""

import re

import pytest
import typer
from typer.testing import CliRunner

from groundhog import cli, config, crawl, db, setup_checks
from groundhog.api.passwords import verify_password
from groundhog.browser import session as browser_session
from groundhog.cases import store
from groundhog.cases.schema import Case, Flow
from groundhog.runner import replay
from groundhog.runner.replay import RunResult

EXAMPLE = (
    "BASE_URL=https://app.example.com\n"
    "LOGIN_USER=you@example.com\n"
    "LOGIN_PASS=your-password\n"
    "LOGIN_WORKSPACE=Your Workspace\n"
    "TYPESAFE_API_KEY=\n"
    "\n"
    "# ANTHROPIC_API_KEY=\n"
)


@pytest.fixture
def home(tmp_path, monkeypatch):
    (tmp_path / ".env.example").write_text(EXAMPLE)
    monkeypatch.setattr(config, "ROOT", tmp_path)
    return tmp_path


def test_placeholders_skips_comments_and_blanks(home):
    assert setup_checks.placeholders() == {
        "BASE_URL": "https://app.example.com",
        "LOGIN_USER": "you@example.com",
        "LOGIN_PASS": "your-password",
        "LOGIN_WORKSPACE": "Your Workspace",
        "TYPESAFE_API_KEY": "",
    }


def test_check_env_placeholder_missing_and_filled():
    assert setup_checks.check_env("BASE_URL", "", "https://app.example.com") == (False, "BASE_URL not set — edit .env")
    ok, detail = setup_checks.check_env("BASE_URL", "https://app.example.com", "https://app.example.com")
    assert (ok, detail) == (False, "BASE_URL still the placeholder — edit .env")
    filled = setup_checks.check_env("BASE_URL", "https://real.example.net", "https://app.example.com")
    assert filled == (True, "BASE_URL")


def test_empty_placeholder_does_not_shadow_a_real_key():
    # TYPESAFE_API_KEY's placeholder is "", so only emptiness may fail it.
    assert setup_checks.check_env("TYPESAFE_API_KEY", "sk-abc", "") == (True, "TYPESAFE_API_KEY")


def test_inventory_counts_mongo_documents():
    for n in ("a", "b", "c"):
        store.save(Case(name=n, intent="i", steps=[]))
    store.save_flow(Flow(name="f", chain=["a"]))
    assert cli.inventory() == "cases: 3 · flows: 1"


def test_init_creates_env_and_stops(home, capsys):
    with pytest.raises(typer.Exit) as e:
        cli.init()
    assert e.value.exit_code == 1
    assert (home / ".env").read_text() == EXAMPLE
    assert "created .env" in capsys.readouterr().out


def test_init_reports_placeholders_and_exits_1(home, monkeypatch, capsys):
    (home / ".env").write_text(EXAMPLE)
    for name, value in [("BASE_URL", "https://app.example.com"), ("LOGIN_USER", "me@real.example.net"),
                        ("LOGIN_PASS", "x"), ("LOGIN_WORKSPACE", "Mine"), ("TYPESAFE_API_KEY", ""),
                        ("ANTHROPIC_API_KEY", "")]:
        monkeypatch.setattr(config, name, value)
    monkeypatch.setattr(setup_checks, "check_chromium", lambda: (True, "Chromium launches"))
    monkeypatch.setattr(setup_checks, "check_app", lambda: (True, "app reachable"))
    monkeypatch.setattr(setup_checks, "check_jev", lambda: (True, "Jev reachable (jev-latest, 12ms)"))
    monkeypatch.setattr(setup_checks, "check_login", lambda: pytest.fail("login must not run with a bad env"))

    with pytest.raises(typer.Exit) as e:
        cli.init()
    assert e.value.exit_code == 1
    out = capsys.readouterr().out
    assert "BASE_URL still the placeholder" in out
    assert "TYPESAFE_API_KEY not set" in out
    assert "✓ LOGIN_USER" in out
    assert "login — skipped" in out
    assert "cases: 0 · flows: 0" in out
    assert "Next:" in out


def test_init_all_green_exits_0(home, monkeypatch, capsys):
    (home / ".env").write_text(EXAMPLE)
    for name, value in [("BASE_URL", "https://real.example.net"), ("LOGIN_USER", "me@real.example.net"),
                        ("LOGIN_PASS", "x"), ("LOGIN_WORKSPACE", "Mine"), ("TYPESAFE_API_KEY", "sk-1"),
                        ("ANTHROPIC_API_KEY", "sk-2")]:
        monkeypatch.setattr(config, name, value)
    monkeypatch.setattr(setup_checks, "check_chromium", lambda: (True, "Chromium launches"))
    monkeypatch.setattr(setup_checks, "check_app", lambda: (True, "app reachable"))
    monkeypatch.setattr(setup_checks, "check_jev", lambda: (True, "Jev reachable (jev-latest, 12ms)"))
    monkeypatch.setattr(setup_checks, "check_login", lambda: (True, "logged in as me@real.example.net"))

    with pytest.raises(typer.Exit) as e:
        cli.init()
    assert e.value.exit_code == 0
    assert "✗" not in capsys.readouterr().out


def test_init_failed_check_still_exits_1(home, monkeypatch):
    (home / ".env").write_text(EXAMPLE)
    for name, value in [("BASE_URL", "https://real.example.net"), ("LOGIN_USER", "me@real.example.net"),
                        ("LOGIN_PASS", "x"), ("LOGIN_WORKSPACE", "Mine"), ("TYPESAFE_API_KEY", "sk-1"),
                        ("ANTHROPIC_API_KEY", "")]:
        monkeypatch.setattr(config, name, value)
    monkeypatch.setattr(setup_checks, "check_chromium", lambda: (True, "Chromium launches"))
    monkeypatch.setattr(setup_checks, "check_app", lambda: (True, "app reachable"))
    monkeypatch.setattr(setup_checks, "check_jev", lambda: (False, "Jev — TYPESAFE_API_KEY was rejected"))
    monkeypatch.setattr(setup_checks, "check_login", lambda: (True, "logged in"))

    with pytest.raises(typer.Exit) as e:
        cli.init()
    assert e.value.exit_code == 1


def test_init_survives_brackets_in_a_check_message(home, monkeypatch, capsys):
    # Jev's HTTP errors quote the response body, which is JSON full of brackets.
    (home / ".env").write_text(EXAMPLE)
    for name, value in [("BASE_URL", "https://real.example.net"), ("LOGIN_USER", "me@real.example.net"),
                        ("LOGIN_PASS", "x"), ("LOGIN_WORKSPACE", "Mine"), ("TYPESAFE_API_KEY", "sk-1")]:
        monkeypatch.setattr(config, name, value)
    monkeypatch.setattr(setup_checks, "check_chromium", lambda: (True, "Chromium launches"))
    monkeypatch.setattr(setup_checks, "check_app", lambda: (True, "app reachable"))
    monkeypatch.setattr(setup_checks, "check_jev", lambda: (False, 'Jev returned HTTP 400: [{"detail": "bad"}]'))
    monkeypatch.setattr(setup_checks, "check_login", lambda: (True, "logged in"))

    with pytest.raises(typer.Exit) as e:
        cli.init()
    assert e.value.exit_code == 1
    assert '[{"detail": "bad"}]' in capsys.readouterr().out


def test_db_seed_creates_the_admin_once(monkeypatch, capsys):
    monkeypatch.setattr(config, "ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "groundhog-dev")
    cli.db_seed()
    cli.db_seed()
    out = capsys.readouterr().out
    assert out.count("created admin admin@example.com") == 1 and "generated password" not in out
    user = db.users().find_one()
    assert user["role"] == "admin" and verify_password("groundhog-dev", user["password_hash"])


def test_db_seed_needs_an_admin_email(monkeypatch):
    monkeypatch.setattr(config, "ADMIN_EMAIL", "")
    with pytest.raises(typer.Exit):
        cli.db_seed()
    assert db.users().count_documents({}) == 0


def test_db_seed_prints_a_generated_password_once(monkeypatch, capsys):
    monkeypatch.setattr(config, "ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "")
    cli.db_seed()
    password = capsys.readouterr().out.split("generated password (shown once): ")[1].split()[0]
    assert verify_password(password, db.users().find_one()["password_hash"])
    cli.db_seed()
    assert "generated password" not in capsys.readouterr().out


def test_an_unknown_case_is_one_line_not_a_traceback(capsys):
    with pytest.raises(typer.Exit) as e:
        cli.show("no-such-case")
    assert e.value.exit_code == 1
    assert capsys.readouterr().out.strip() == "no saved case named no-such-case"


def test_recorded_rejects_a_bad_name_before_opening_a_run():
    with pytest.raises(typer.Exit) as e, cli.recorded(None, "run", "Bad Name", {}):
        pass
    assert e.value.exit_code == 2
    assert db.runs().count_documents({}) == 0


def test_recorded_closes_a_runtime_error_as_one_red_line_and_ends_on_the_run_id(capsys):
    with pytest.raises(typer.Exit) as e, cli.recorded("abc123abc123", "author", "new-case", {}):
        raise RuntimeError("authoring stopped (budget)")
    assert e.value.exit_code == 2
    run = db.runs().find_one()
    assert (run["status"], run["error"]) == ("error", "authoring stopped (budget)")
    assert capsys.readouterr().out.strip().splitlines()[-1] == "run abc123abc123"


@pytest.mark.parametrize("raised, error", [(ValueError("boom"), "boom"), (KeyboardInterrupt(), "KeyboardInterrupt")])
def test_recorded_closes_any_other_exception_as_error_and_reraises(raised, error):
    with pytest.raises(type(raised)), cli.recorded(None, "run", "a-case", {}):
        raise raised
    run = db.runs().find_one()
    assert (run["status"], run["error"]) == ("error", error)


class FakeSession:
    def __init__(self, headless=None):
        self.ws = ""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def ensure_logged_in(self):
        self.ws = "FYTEST0001"


def stub_replays(monkeypatch, outcomes: list[bool]) -> list:
    """Replace the browser and the replay; return the (case, session, vars) of every replay."""
    calls, results = [], iter(outcomes)

    def fake_run_case(case, session, vars=None, heal=True):
        calls.append((case.name, session, dict(vars)))
        return RunResult(passed=next(results), total_ms=5)

    monkeypatch.setattr(browser_session, "Session", FakeSession)
    monkeypatch.setattr(replay, "run_case", fake_run_case)
    return calls


def test_run_with_two_names_shares_one_session_and_writes_a_run_per_case(monkeypatch):
    for name in ("a", "b"):
        store.save(Case(name=name, intent="open {{page}}", steps=[]))
    calls = stub_replays(monkeypatch, [True, False])

    result = CliRunner().invoke(cli.app, ["run", "a", "b", "--var", "page=home"])
    assert result.exit_code == 1
    assert len({id(session) for _, session, _ in calls}) == 1
    assert sorted((r["target"], r["status"]) for r in db.runs().find()) == [("a", "passed"), ("b", "failed")]
    assert len(re.findall(r"^run \w{12}$", result.output, re.M)) == 2


def test_retry_emits_the_attempt_and_restamps_empty_vars(monkeypatch):
    store.save(Case(name="a", intent="create {{name}}", steps=[]))
    calls = stub_replays(monkeypatch, [False, True])
    stamps = iter(["gh-1", "gh-2"])
    monkeypatch.setattr(cli, "stamp", lambda run_id: next(stamps))

    assert CliRunner().invoke(cli.app, ["run", "a", "--retries", "1"]).exit_code == 0
    assert [v["name"] for _, _, v in calls] == ["gh-1", "gh-2"]
    run = db.runs().find_one()
    assert [e["n"] for e in run["events"] if e["kind"] == "attempt"] == [2]
    assert (run["attempts"], run["flaky"], run["retries"], run["vars"]) == (2, True, 1, {"name": "gh-2"})


def test_stamp_differs_between_runs_started_in_the_same_second():
    first, second = cli.stamp("abcd12345678"), cli.stamp("ef0198765432")
    assert re.fullmatch(r"gh-\d{6}-abcd", first) and first != second


def test_crawl_records_a_crawl_run_and_refuses_a_bad_scope(monkeypatch):
    monkeypatch.setattr(crawl, "crawl", lambda *a, **kw: {"pages": 2, "controls": 5})

    assert CliRunner().invoke(cli.app, ["crawl", "--scope", "templates"]).exit_code == 2
    assert db.runs().count_documents({}) == 0
    assert CliRunner().invoke(cli.app, ["crawl", "--scope", "/templates"]).exit_code == 0
    run = db.runs().find_one()
    assert (run["kind"], run["target"], run["status"], run["pages"]) == ("crawl", "/templates", "passed", 2)


def test_run_of_an_unknown_case_stops_before_the_browser(monkeypatch):
    monkeypatch.setattr(browser_session, "Session", lambda **kw: pytest.fail("no browser for an unknown case"))
    result = CliRunner().invoke(cli.app, ["run", "nope"])
    assert result.exit_code == 1 and "no saved case named nope" in result.output


def test_run_needs_a_name_or_all(monkeypatch):
    stub_replays(monkeypatch, [])
    assert CliRunner().invoke(cli.app, ["run"]).exit_code == 2
