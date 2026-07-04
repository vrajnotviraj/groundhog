# groundhog

AI-authored, deterministically-replayed web tests.

An agent turns a natural-language test intent into a **JSON test case** once
(expensive, smart). Every later run is a **static Playwright replay** (fast,
zero tokens). The agent wakes up **only when a step fails**, heals it, and
persists the fix back into the case JSON. A Neo4j knowledge graph of the app —
built by crawling and enriched by every run — gives the agent minimal, targeted
context, so agent invocations stay crisp and cheap.

The system gets cheaper and more deterministic with use: every agent run
updates the graph; every healed step updates the case; every run after the
first costs nothing until the UI drifts.

## Setup (≈5 minutes)

```sh
git clone <this repo> && cd groundhog
uv sync && uv run playwright install chromium
docker compose up -d          # Neo4j (optional — everything degrades gracefully without it)
cp .env.example .env          # fill in BASE_URL, LOGIN_USER/PASS/WORKSPACE, ANTHROPIC_API_KEY
```

Login is two cached layers under `.auth/` (gitignored): `state.json` (session
cookies) and `login.json` (the login flow as replayable steps — `fill_secret`
steps store only the field *name*; credentials stay in `.env` and never reach
the LLM or disk). Seed `login.json` once by copying the shape below and
adjusting selectors to your login form:

```json
{"start_path": "/", "steps": [
  {"action": "goto", "selector": "/", "description": "Open the login page"},
  {"action": "fill_secret", "selector": "role=textbox[name=\"Email Address\"]", "field": "user", "description": "email"},
  {"action": "fill_secret", "selector": "role=textbox[name=\"Password\"]", "field": "pass", "description": "password"},
  {"action": "click", "selector": "role=button[name=\"Login\"]", "description": "submit"}
]}
```

## Demo (≈10 minutes)

```sh
uv run groundhog crawl --scope templates            # app → knowledge graph
uv run groundhog new "create an SMS template named {{name}} and verify it appears in the list" --var name=gh-seed
uv run groundhog run create-an-sms-template --var name=gh-1   # static replay, zero LLM on steps
uv run groundhog run create-an-sms-template --var name=gh-2   # again — still static
# break a selector in cases/*.json, run again → the step heals and the JSON is rewritten
uv run groundhog suggest                            # untested scenarios inferred from the graph
uv run groundhog list                               # saved cases, runs, heal counts
```

Every run writes a markdown + JSON report to `runs/` with per-step mode
(`static` / `fallback` / `healed` / `failed`), drift flags, and exact token
spend — a fully static run reports **"Zero LLM calls"**.

## How a run works

1. **Static replay.** Per step: drift gate (fingerprint of the pruned
   accessibility snapshot vs the one stored at authoring) → try `selector`,
   then `fallback_selectors` (zero LLM) → verify the step's `expects`
   post-condition → no-op detection (a "successful" click that changed nothing
   is a failure, not a silent pass).
2. **Heal on failure only.** One FAST call gets the step's intent + current
   snapshot; it returns a replacement selector or **refuses** (a Delete step
   must never heal to Cancel — better to fail than act on the wrong element).
   A heal is accepted only after it executes and passes `expects`, and is
   persisted only if the whole run passes — then the case JSON is rewritten
   (`meta.heals` history, `healed_count` as a flakiness signal) and the next
   run is fully static again.
3. **Assertions.** `deterministic` ones (`url_contains:…`, `text_visible:…`)
   are checked directly; plain-English ones are judged by FAST against the
   final snapshot with `{passed, confidence, reasoning}`.

## Model slots

| Slot | Default | Used for |
|---|---|---|
| `SMART_MODEL` | `claude-sonnet-5` | planner, optimizer, suggest |
| `FAST_MODEL` | `claude-haiku-4-5` | executor steps, healer, judge, crawl observe |

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
cases/                   saved test cases (JSON — edit freely)
runs/                    run reports
```

Safety: the crawler never executes `mutation`/`destructive` elements — those
edges enter the graph only from real test runs. Template vars (`{{name}}`)
substitute into values, assertions, and selectors at run time — a selector may
target an entity created earlier in the same test by its `{{var}}` name, but
never a hard-coded data literal.

Long flows (create a routing, a template, then an event that wires them
together) author in one pass: stale page snapshots are elided from the agent's
context as it works, and the action budget scales with the plan — so a
40-action flow stays as crisp as a 5-action one. Authoring types the concrete
`--var` values (validated name fields reject literal braces); the saved case is
re-parameterized mechanically before it is written.
