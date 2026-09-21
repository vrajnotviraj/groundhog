"""init's env/.env checks and its summary line, without a browser or network."""

import pytest
import typer

from groundhog import cli, config

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
    monkeypatch.setattr(config, "CASES_DIR", tmp_path / "cases")
    monkeypatch.setattr(config, "FLOWS_DIR", tmp_path / "flows")
    return tmp_path


def test_placeholders_skips_comments_and_blanks(home):
    assert cli.placeholders() == {
        "BASE_URL": "https://app.example.com",
        "LOGIN_USER": "you@example.com",
        "LOGIN_PASS": "your-password",
        "LOGIN_WORKSPACE": "Your Workspace",
        "TYPESAFE_API_KEY": "",
    }


def test_check_env_placeholder_missing_and_filled():
    assert cli.check_env("BASE_URL", "", "https://app.example.com") == (False, "BASE_URL not set — edit .env")
    ok, detail = cli.check_env("BASE_URL", "https://app.example.com", "https://app.example.com")
    assert (ok, detail) == (False, "BASE_URL still the placeholder — edit .env")
    assert cli.check_env("BASE_URL", "https://real.example.net", "https://app.example.com") == (True, "BASE_URL")


def test_empty_placeholder_does_not_shadow_a_real_key():
    # TYPESAFE_API_KEY's placeholder is "", so only emptiness may fail it.
    assert cli.check_env("TYPESAFE_API_KEY", "sk-abc", "") == (True, "TYPESAFE_API_KEY")


def test_inventory_counts_saved_files(home):
    (home / "cases").mkdir()
    (home / "flows").mkdir()
    for n in ("a", "b", "c"):
        (home / "cases" / f"{n}.json").write_text("{}")
    (home / "flows" / "f.json").write_text("{}")
    assert cli.inventory() == "cases/: 3 saved · flows/: 1 saved"


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
    monkeypatch.setattr(cli, "check_chromium", lambda: (True, "Chromium launches"))
    monkeypatch.setattr(cli, "check_app", lambda: (True, "app reachable"))
    monkeypatch.setattr(cli, "check_jev", lambda: (True, "Jev reachable (jev-latest, 12ms)"))
    monkeypatch.setattr(cli, "check_login", lambda: pytest.fail("login must not run with a bad env"))

    with pytest.raises(typer.Exit) as e:
        cli.init()
    assert e.value.exit_code == 1
    out = capsys.readouterr().out
    assert "BASE_URL still the placeholder" in out
    assert "TYPESAFE_API_KEY not set" in out
    assert "✓ LOGIN_USER" in out
    assert "login — skipped" in out
    assert "cases/: 0 saved · flows/: 0 saved" in out
    assert "Next:" in out


def test_init_all_green_exits_0(home, monkeypatch, capsys):
    (home / ".env").write_text(EXAMPLE)
    for name, value in [("BASE_URL", "https://real.example.net"), ("LOGIN_USER", "me@real.example.net"),
                        ("LOGIN_PASS", "x"), ("LOGIN_WORKSPACE", "Mine"), ("TYPESAFE_API_KEY", "sk-1"),
                        ("ANTHROPIC_API_KEY", "sk-2")]:
        monkeypatch.setattr(config, name, value)
    monkeypatch.setattr(cli, "check_chromium", lambda: (True, "Chromium launches"))
    monkeypatch.setattr(cli, "check_app", lambda: (True, "app reachable"))
    monkeypatch.setattr(cli, "check_jev", lambda: (True, "Jev reachable (jev-latest, 12ms)"))
    monkeypatch.setattr(cli, "check_login", lambda: (True, "logged in as me@real.example.net"))

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
    monkeypatch.setattr(cli, "check_chromium", lambda: (True, "Chromium launches"))
    monkeypatch.setattr(cli, "check_app", lambda: (True, "app reachable"))
    monkeypatch.setattr(cli, "check_jev", lambda: (False, "Jev — TYPESAFE_API_KEY was rejected"))
    monkeypatch.setattr(cli, "check_login", lambda: (True, "logged in"))

    with pytest.raises(typer.Exit) as e:
        cli.init()
    assert e.value.exit_code == 1


def test_init_survives_brackets_in_a_check_message(home, monkeypatch, capsys):
    # Jev's HTTP errors quote the response body, which is JSON full of brackets.
    (home / ".env").write_text(EXAMPLE)
    for name, value in [("BASE_URL", "https://real.example.net"), ("LOGIN_USER", "me@real.example.net"),
                        ("LOGIN_PASS", "x"), ("LOGIN_WORKSPACE", "Mine"), ("TYPESAFE_API_KEY", "sk-1")]:
        monkeypatch.setattr(config, name, value)
    monkeypatch.setattr(cli, "check_chromium", lambda: (True, "Chromium launches"))
    monkeypatch.setattr(cli, "check_app", lambda: (True, "app reachable"))
    monkeypatch.setattr(cli, "check_jev", lambda: (False, 'Jev returned HTTP 400: [{"detail": "bad"}]'))
    monkeypatch.setattr(cli, "check_login", lambda: (True, "logged in"))

    with pytest.raises(typer.Exit) as e:
        cli.init()
    assert e.value.exit_code == 1
    assert '[{"detail": "bad"}]' in capsys.readouterr().out
