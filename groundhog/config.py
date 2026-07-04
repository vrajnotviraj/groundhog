"""Env-backed configuration: model slots, budgets, credentials.

Only credential VALUES live in env — login flows are recorded as steps that
reference a field name ("user"/"pass"), so secrets never reach the LLM or disk.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.environ.get("BASE_URL", "https://app.example.com")

LOGIN_USER = os.environ.get("LOGIN_USER", "")
LOGIN_PASS = os.environ.get("LOGIN_PASS", "")
LOGIN_WORKSPACE = os.environ.get("LOGIN_WORKSPACE", "")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
# SMART plans and optimizes (few calls, hard thinking); FAST drives per-step
# decisions, healing, judging, crawl observation (many calls, cheap).
SMART_MODEL = os.environ.get("SMART_MODEL", "claude-sonnet-5")
FAST_MODEL = os.environ.get("FAST_MODEL", "claude-haiku-4-5")

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASS = os.environ.get("NEO4J_PASS", "groundhog")

HEADLESS = os.environ.get("HEADLESS", "1") == "1"
# Bounded settle: networkidle may never fire on an app with websockets/polling.
SETTLE_TIMEOUT_MS = int(os.environ.get("SETTLE_TIMEOUT_MS", "1500"))
STEP_TIMEOUT_MS = int(os.environ.get("STEP_TIMEOUT_MS", "8000"))
EXECUTOR_MAX_ACTIONS = int(os.environ.get("EXECUTOR_MAX_ACTIONS", "25"))

CRAWL_MAX_PAGES = int(os.environ.get("CRAWL_MAX_PAGES", "40"))
CRAWL_MAX_DEPTH = int(os.environ.get("CRAWL_MAX_DEPTH", "4"))

DOCS_URL = os.environ.get("DOCS_URL", "https://docs.example.com")

ROOT = Path.cwd()
CASES_DIR = ROOT / "cases"
RUNS_DIR = ROOT / "runs"
AUTH_DIR = ROOT / ".auth"
