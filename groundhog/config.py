"""Env-backed configuration: credentials, model slots, budgets, paths.

Credential values live in .env and never reach a model, a snapshot or a case file.
"""

import os
import re
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.environ.get("BASE_URL", "https://app.example.com")

LOGIN_USER = os.environ.get("LOGIN_USER", "")
LOGIN_PASS = os.environ.get("LOGIN_PASS", "")
LOGIN_WORKSPACE = os.environ.get("LOGIN_WORKSPACE", "")
# Workspace id to open directly after login; when empty the picker is used via LOGIN_WORKSPACE.
WORKSPACE_ID = os.environ.get("WORKSPACE_ID", "")

# Jev makes every browser decision; required for new/heal/judge.
TYPESAFE_API_KEY = os.environ.get("TYPESAFE_API_KEY", "")
TYPESAFE_MODEL = os.environ.get("TYPESAFE_MODEL", "jev-latest")

# Optional: only writes field values the intent doesn't spell out, and composes flows.
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")

HEADLESS = os.environ.get("HEADLESS", "1") == "1"
# Bounded settle: networkidle may never fire on an app with websockets/polling.
SETTLE_TIMEOUT_MS = int(os.environ.get("SETTLE_TIMEOUT_MS", "1000"))
STEP_TIMEOUT_MS = int(os.environ.get("STEP_TIMEOUT_MS", "10000"))
# First page load of a session; a slow dev environment needs more than a step.
PAGE_LOAD_MS = int(os.environ.get("PAGE_LOAD_MS", "45000"))
# Once an element's existence is established, actions and confirmations should be
# quick — a short per-attempt budget keeps the fallback walk from multiplying the
# full timeout, and fails a selector that matches nothing fast instead of at 8s.
ACTION_PROBE_MS = int(os.environ.get("ACTION_PROBE_MS", "2000"))
# Poll interval for the cheap existence waits (readiness + fail-fast probe).
READINESS_POLL_MS = int(os.environ.get("READINESS_POLL_MS", "250"))
EXECUTOR_MAX_ACTIONS = int(os.environ.get("EXECUTOR_MAX_ACTIONS", "40"))

# Noul probability a "jev" assertion needs to pass; also the DONE gate.
JUDGE_THRESHOLD = float(os.environ.get("JUDGE_THRESHOLD", "0.6"))
# Target probability a heal needs before its selector is accepted.
HEAL_THRESHOLD = float(os.environ.get("HEAL_THRESHOLD", "0.6"))

ROOT = Path.cwd()
# Cases, flows, runs, users and sessions all live in this database.
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017/groundhog")
# The first console admin, created by `groundhog db seed` when there are no users.
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
AUTH_DIR = ROOT / ".auth"

# Workspace ids are per-install, so they must never land in a saved case.
WS_ID = re.compile(r"/FY[A-Z0-9]{6,}(?=/|$)")


def ws_path(url: str) -> str:
    """Path of a URL or path, workspace segment replaced by /:ws."""
    return WS_ID.sub("/:ws", urlsplit(url).path or "/")
