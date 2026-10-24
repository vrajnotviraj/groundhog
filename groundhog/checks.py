"""The readiness checks behind `groundhog init` and the console's health screen.

Each check returns (ok, line): the line names what passed, or says what to do about what failed.
"""

from dotenv import dotenv_values

from groundhog import config

REQUIRED = ["BASE_URL", "LOGIN_USER", "LOGIN_PASS", "LOGIN_WORKSPACE", "TYPESAFE_API_KEY"]


def placeholders() -> dict[str, str]:
    """The values shipped in .env.example, so an unedited copy can be told apart."""
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


def check_mongo() -> tuple[bool, str]:
    from groundhog import db

    host = config.MONGO_URL.split("@")[-1]  # never echo credentials embedded in the URL
    if not db.ping():
        return False, f"Mongo unreachable ({host}) — start it, or set MONGO_URL in .env"
    return True, f"Mongo reachable ({host})"


def check_login() -> tuple[bool, str]:
    from groundhog.browser.session import Session

    try:
        with Session() as s:
            s.ensure_logged_in()
            return True, (f"logged in as {config.LOGIN_USER} · workspace {s.ws} "
                          f"({config.LOGIN_WORKSPACE}) · session cached in .auth/")
    except Exception as e:
        return False, f"login — {e}"
