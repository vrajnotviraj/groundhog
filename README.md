<p align="center">
  <img src="assets/groundhog.svg" width="160" alt="groundhog mascot">
</p>

<h1 align="center">groundhog</h1>

<p align="center"><b>Describe a test in English once. Replay it forever, for free.</b></p>

Groundhog is end-to-end testing for SaaS apps. That's it.

## Why this exists

An AI agent can drive a browser today. Every demo proves that. What none of
them fix is memory. An agent opening your app for the thousandth time still
behaves like it's the first: same blind clicking around the DOM, same tokens
spent finding the same button, every single run.

The real question behind groundhog: how do you give an AI enough context
about your app that it stops re-learning it every run?

The answer is to crawl the app once. A crawler walks it like a careful user:
it clicks links, reads pages, and refuses to touch anything that mutates or
deletes data. What it sees goes into a knowledge graph in Neo4j. That graph
is the context. It's what lets you write `create an SMS template` instead of
walking the agent to the exact button, form, and field by hand.

Once the agent has that map, you write tests in plain English. `groundhog new
"create an SMS template named {{name}} and verify it appears in the list"`
drives your real app once, then saves what it did as a JSON case. Every run
after that replays the JSON. No AI, no map, no guessing, just a deterministic
script.

A single case proves one thing works. Real objectives rarely live on one
page. Wiring a route to a template to an event, then confirming the event
actually fires, is three or four cases deep. Flows chain saved cases into
that longer story, in order, sharing one login and one set of data. That's
the objective a lone case can't reach on its own.

Like the movie: it wakes up, sees the same day, and gets a little better at
it.

## What you get

- **Write tests in English.** `groundhog new "create an SMS template named {{name}} and verify it appears in the list"`: the agent drives your real app, then saves a replayable case.
- **Runs cost nothing.** A green run makes zero AI calls. The report says so explicitly: "Zero LLM calls".
- **Tests fix themselves.** A broken selector triggers one small AI call that heals it, and refuses when healing would be dangerous (a Delete step never heals to Cancel).
- **Your app gets mapped.** A crawler builds a knowledge graph of your app in Neo4j. Every run enriches it. `groundhog suggest` tells you what you haven't tested yet.
- **Long flows work.** "Create a route, then a template, then an event that wires them together" authors in one pass and replays statically.
- **Cases chain into flows.** `groundhog flow new "create a template, then an event on it, then clean up"` reuses saved cases, authors the missing ones live, and pairs every create with a delete that runs even when the chain fails.

## Variables

Every case has its own local vars. `{{name}}` in an intent becomes `--var
name=gh-1` at run time, substituted into values, assertions, and selectors.
Same case, different data, every run.

A flow needs more than that. When step one creates a template and step three
searches for it, both steps need the same name. That's what a flow's `vars`
block is: one shared namespace, set once at the flow level, visible to every
case in the chain.

A case inside the chain can still override a shared var just for itself:

```json
{"case": "search-templates", "vars": {"query": "{{name}}"}}
```

That override wins locally without touching what the rest of the chain sees.
And `{{stamp}}` (a per-run timestamp) gets baked into shared defaults like
`gh-{{stamp}}`, so two runs of the same flow never collide over leftover
data.

Local vars make one case reusable. Shared vars make a chain of cases behave
like one continuous story instead of four cases that happen to run back to
back.

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

`uv run` re-syncs dependencies on every call, which is why the commands below
use it. For a real `groundhog` command on your `PATH` instead, install it as
a uv tool once: `uv tool install --editable .` (editable means it keeps
running your local code, not a frozen copy). A plain shell alias to `uv run
groundhog` is a lighter option, but it's just a shorthand, not a real
install: it still re-syncs on every call.

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

## Chain cases into flows

One case tests one thing. A flow chains saved cases into a longer story: create a
template, create an event that uses it, delete both. One browser session, one
login, one shared set of `{{var}}` values.

```sh
uv run groundhog flow new "create an SMS template, verify it shows up in search, then delete it"
uv run groundhog flow run template-lifecycle     # static replay, zero AI
uv run groundhog flow list
```

`flow new` is an orchestrator. It splits the description into case-sized steps,
replays the ones a saved case already covers, and authors the missing ones on
the spot, in chain order against real app state. That's what lets the case that
creates an event pick the template the chain just created. After that one pass,
the flow and every case in it are saved, and `flow run` is static.

Cleanup is part of the contract. Cases under `cleanup` run even when the chain
fails, the composer pairs every create with a delete, and a flow only passes if
cleanup passes too. Shared vars default to per-run values like `gh-{{stamp}}`,
so runs never collide with leftover data.

A flow file is small enough to write by hand:

```json
{"name": "template-lifecycle",
 "vars": {"name": "gh-{{stamp}}"},
 "chain": ["create-sms-template", {"case": "search-templates", "vars": {"query": "{{name}}"}}],
 "cleanup": ["delete-sms-template"]}
```

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

The agent types real values while authoring (validated form fields reject
braces); the saved case is re-parameterized back into `{{var}}` form
automatically, ready for the next run.

## Configuration

| Env var | Default | Used for |
|---|---|---|
| `SMART_MODEL` | `claude-sonnet-5` | planner, optimizer, suggest |
| `FAST_MODEL` | `claude-haiku-4-5` | executor steps, healer, judge, crawl |

## Layout

```
groundhog/
  cli.py                 crawl · new · run · list · show · suggest · doctor
  config.py              env, model slots, budgets
  browser/               session+login · snapshot pruning+fingerprints · step execution · selector rules
  llm/                   Anthropic wrapper (structured output, caching, usage counter) · prompts/*.md
  agent/                 planner · executor · optimizer · healer · judge · composer
  graph/                 Neo4j store (single write path) · queries · ingest
  crawl/                 budgeted BFS crawler · LLM page observation
  cases/ runner/         case schema+store · replay orchestration · reports
cases/                   saved test cases (JSON, edit freely)
flows/                   saved flows: chains of cases (JSON, edit freely)
runs/                    run reports
```

Safety: the crawler never clicks anything that mutates or destroys data.
Those edges enter the graph only from real test runs.
