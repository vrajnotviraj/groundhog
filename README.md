<p align="center">
  <img src="assets/groundhog.svg" width="160" alt="groundhog mascot">
</p>

<h1 align="center">groundhog</h1>

<p align="center"><b>Describe a test in English once. Replay it forever, for free.</b></p>

Groundhog is end-to-end testing for SaaS apps. That's it.

Today you have two bad options for testing a web app. Write Playwright scripts
by hand: slow to write, and they break every time the UI changes. Or let an AI
agent drive the browser on every run: resilient, but slow, and you pay tokens
for every single test, every time.

Groundhog does the smart part once. An AI agent turns your plain-English intent
into a JSON test case. Every run after that is a static Playwright replay: fast,
deterministic, zero AI calls. When the UI drifts and a step breaks, the agent
wakes up, fixes that one step, verifies the fix, and writes it back into the
JSON. The next run is fully static again.

Like the movie: it wakes up, sees the same day, and gets a little better at it.

## What you get

- **Write tests in English.** `groundhog new "create an SMS template named {{name}} and verify it appears in the list"`: the agent drives your real app, then saves a replayable case.
- **Runs cost nothing.** A green run makes zero AI calls. The report says so explicitly: "Zero LLM calls".
- **Tests fix themselves.** A broken selector triggers one small AI call that heals it, and refuses when healing would be dangerous (a Delete step never heals to Cancel).
- **Your app gets mapped.** A crawler builds a knowledge graph of your app in Neo4j. Every run enriches it. `groundhog suggest` tells you what you haven't tested yet.
- **Long flows work.** "Create a route, then a template, then an event that wires them together" authors in one pass and replays statically.

## Quick start (~5 minutes)

You need [uv](https://docs.astral.sh/uv/), Docker (optional), and an Anthropic API key.

```sh
git clone <this repo> && cd groundhog
uv sync && uv run playwright install chromium
docker compose up -d          # Neo4j (optional): degrades gracefully without it
cp .env.example .env          # fill in BASE_URL, LOGIN_USER/PASS/WORKSPACE, ANTHROPIC_API_KEY
```

Then teach it your login form once. Copy this into `.auth/login.json` and adjust
the selectors:

```json
{"start_path": "/", "steps": [
  {"action": "goto", "selector": "/", "description": "Open the login page"},
  {"action": "fill_secret", "selector": "role=textbox[name=\"Email Address\"]", "field": "user", "description": "email"},
  {"action": "fill_secret", "selector": "role=textbox[name=\"Password\"]", "field": "pass", "description": "password"},
  {"action": "click", "selector": "role=button[name=\"Login\"]", "description": "submit"}
]}
```

Credentials stay in `.env`. They never reach the LLM or disk: `fill_secret`
steps store only the field name. Session cookies are cached under `.auth/`
(gitignored) so login replays only when the session expires.

## Use it

```sh
uv run groundhog doctor                       # check API key, app URL, Neo4j, login flow
uv run groundhog crawl --scope templates      # map your app into the knowledge graph
uv run groundhog new "create an SMS template named {{name}} and verify it appears in the list" --var name=gh-seed
uv run groundhog run create-an-sms-template --var name=gh-1   # static replay, zero AI
uv run groundhog run create-an-sms-template --var name=gh-2   # again, still static
uv run groundhog suggest                      # untested scenarios, inferred from the graph
uv run groundhog list                         # saved cases, runs, heal counts
```

Break a selector in `cases/*.json` and run again: the step heals and the JSON
is rewritten. Every run writes a markdown + JSON report to `runs/` with
per-step mode (`static` / `fallback` / `healed` / `failed`), drift flags, and
exact token spend. Long runs fail safe: Ctrl-C during a crawl keeps every page
already ingested, and a failed authoring run dumps its partial trace to `runs/`
so the agent's work isn't lost.

## How a run works

1. **Static replay.** Each step checks for page drift (a fingerprint of the
   pruned accessibility snapshot), tries its selector, then its fallback
   selectors, all without AI. A step's `expects` post-condition verifies it
   actually worked; a "successful" click that changed nothing counts as a
   failure, not a silent pass.
2. **Heal on failure only.** One small AI call sees the step's intent and the
   current page, and returns a replacement selector, or refuses. A heal is
   accepted only after it executes and passes `expects`, and persisted only if
   the whole run passes. Heal history stays in the case as a flakiness signal.
3. **Assertions.** Deterministic ones (`url_contains:…`, `text_visible:…`) are
   checked directly. Plain-English ones are judged by a fast model against the
   final page, with a confidence score.

## How authoring works

A planner reads the knowledge graph and drafts sub-goals. An executor agent
performs them one at a time against your live app, verifying as it goes. An
optimizer then distills the executed trace into the minimal replayable case.
It keeps only selectors that actually ran, never invented ones.

Test data is parameterized: `{{name}}` in your intent becomes a `--var` at run
time, substituted into values, assertions, and selectors, so a test can open
the entity it just created, but never keys on hard-coded data. The agent types
real values while authoring (validated form fields reject braces); the saved
case is re-parameterized automatically.

## Configuration

| Env var | Default | Used for |
|---|---|---|
| `SMART_MODEL` | `claude-sonnet-5` | planner, optimizer, suggest |
| `FAST_MODEL` | `claude-haiku-4-5` | executor steps, healer, judge, crawl |

## Layout

```
groundhog/
  cli.py                 crawl · new · run · list · show · suggest
  config.py              env, model slots, budgets
  browser/               session+login · snapshot pruning+fingerprints · step execution · selector rules
  llm/                   Anthropic wrapper (structured output, caching, usage counter) · prompts/*.md
  agent/                 planner · executor · optimizer · healer · judge
  graph/                 Neo4j store (single write path) · queries · ingest
  crawl/                 budgeted BFS crawler · LLM page observation
  cases/ runner/         case schema+store · replay orchestration · reports
cases/                   saved test cases (JSON, edit freely)
runs/                    run reports
```

Safety: the crawler never clicks anything that mutates or destroys data.
Those edges enter the graph only from real test runs.
