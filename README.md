<p align="center">
  <img src="assets/groundhog.svg" width="160" alt="groundhog mascot">
</p>

<h1 align="center">groundhog</h1>

<p align="center"><b>Describe a test in English once. Replay it forever, for free.</b></p>

Groundhog is end-to-end testing for SaaS apps. That's it.

## Why this exists

An AI agent can drive a browser today. Every demo proves that. What none of
them fix is memory. An agent opening your app for the thousandth time still
behaves like it's the first: the same blind clicking around the DOM, the same
tokens spent finding the same button, every single run.

So groundhog pays that cost once. You describe a test in English, it drives
your real app one time, and it saves what it did as a JSON case of ordinary
Playwright selectors. Every run after that replays the JSON with zero AI
calls. When a selector breaks, 1 small AI call heals it and the JSON is
rewritten.

Like the movie: it wakes up, sees the same day, and gets a little better at
it.

## Quick start

You need [uv](https://docs.astral.sh/uv/), Node 20 or later, MongoDB (or
Docker to run one), a TypeSafe API key from
[console.typesafe.ai](https://console.typesafe.ai), and an app to test.

```sh
git clone <this repo> && cd groundhog
./start.sh                     # creates .env, then tells you what to fill
# fill in .env
./start.sh                     # again, until every line is green
```

`start.sh` checks uv, Node and npm, `.env`, Mongo at `MONGO_URL`, Chromium
and the web dependencies, installing what it can. When Mongo is not reachable
and Docker is, it offers to start a `mongo:7` container. Then it seeds the
database, builds the console and serves it at http://localhost:8000. The
first seed creates the admin from `ADMIN_EMAIL` and, when `ADMIN_PASSWORD` is
empty, prints a generated password once. Keep it.

`./start.sh --dev` also runs the Vite dev server on port 5173, with hot reload.
`./start.sh --check` runs every check and stops before starting anything.
`--yes` answers the Docker prompt, `--port` moves the console off 8000.

The CLI is the second way in, and the same engine. Every command below works
without the console running:

```sh
uv run groundhog init          # checks env vars, Chromium, the app, Jev, Mongo and the login
uv run groundhog db seed       # creates the indexes and the first admin
uv run groundhog new "create an SMS template named {{name}} and verify it appears in the templates list" \
  --name my-first-case --var name=gh-1 --start /:ws/templates
uv run groundhog run my-first-case --var name=gh-2   # static, zero AI
uv run groundhog serve --port 8000                   # the console and its API
```

groundhog logs in through the app's own login API, called from inside the
browser session, so no login page is driven and it works even when the login
page only offers SSO buttons. Your credentials live in `.env` and never reach a
model, a snapshot or a case file. The session is cached under `.auth/`, so the
login replays only when it expires.

## Console

The console is the same data as the CLI, on 5 screens:

- **Overview** answers whether the latest runs passed: today's counts and the last 6 runs.
- **Cases** lists every case with its steps, runs and heals; authors a new one from English.
- **Flows** lists the chains and builds or composes a new one.
- **Runs** is every run, filtered by kind, status and target.
- **Settings** shows the `init` checks, the users and the version.

A run streams live. Each step lands as it happens, coloured by mode, with a
screenshot per step. A run started from the terminal is a run document like
any other, so it shows up in the console too, live.

Cases and flows are stored in Mongo. Download on a case page exports a case
as JSON, and Edit JSON on the same page takes it back.

Every API route needs a signed-in session, except login and health. The
session is an HttpOnly cookie, passwords are hashed with scrypt, and there are
2 roles: admin and member. Only an admin deletes things or manages users.

## How it decides

Authoring runs a loop. Each turn, groundhog reads the live page into an
element table: every visible, enabled, interactive element, numbered, with
its role, label, current value and state. Password fields are excluded before
anything leaves the browser.

That table goes to [Jev](https://docs.typesafe.ai), a System One model that
answers typed questions with probabilities instead of prose. One request asks
which operation comes next and which numbered element it acts on. Jev picks
an index. It never writes a selector.

Code owns the selector. Groundhog takes the DOM node Jev picked and derives
candidates from it in order of durability: `data-testid`, a stable `id`,
`aria-label`, the accessible name, a placeholder, a scoped variant like
`role=dialog >> role=button[name="Delete"]`. Each candidate is run against
the live page and kept only if it resolves to exactly that node. The top 3
survivors become the step's selector and its fallbacks.

Replay is then free. The saved JSON is a list of selectors, values and
post-conditions, checked directly.

Two things still call AI after authoring: a step whose selector matches
nothing asks Jev to pick the element it meant, and a plain-English assertion
like "the template appears in the list" is judged by Jev against the final
page. A green run of a case with no English assertions makes zero calls, and
the run page says so.

## Variables

Every case has its own local vars. `{{name}}` in an intent becomes `--var
name=gh-1` at run time, substituted into values, assertions and selectors.
Same case, different data, every run.

The agent types real values while authoring, because validated form fields
reject braces, and the saved case is re-parameterized back into `{{var}}`
form automatically.

## Chain cases into flows

One case tests one thing. A flow chains saved cases into a longer story:
create a template, create an event that uses it, delete both. One browser
session, one login, one shared set of `{{var}}` values.

```sh
uv run groundhog flow new "create an SMS template, verify it shows up in search, then delete it"
uv run groundhog flow run template-lifecycle
uv run groundhog flow list
```

`flow new` splits the description into case-sized steps, replays the ones a
saved case already covers, and authors the missing ones on the spot, in chain
order against real app state. That's what lets the case that creates an event
pick the template the chain just created. After that one pass, the flow and
every case in it are saved, and `flow run` is static. It needs
`ANTHROPIC_API_KEY`.

When step 1 creates a template and step 3 searches for it, both need the same
name. That's what a flow's `vars` block is: one shared namespace, set once,
visible to every case in the chain. A case can override a shared var just for
itself:

```json
{"case": "search-templates", "vars": {"query": "{{name}}"}}
```

Cleanup is part of the contract. Cases under `cleanup` run even when the
chain fails, and a flow only passes if cleanup passes too. Shared vars
default to per-run values like `gh-{{stamp}}`, so 2 runs never collide over
leftover data.

A flow document is small:

```json
{"name": "template-lifecycle",
 "vars": {"name": "gh-{{stamp}}"},
 "chain": ["create-sms-template", {"case": "search-templates", "vars": {"query": "{{name}}"}}],
 "cleanup": ["delete-sms-template"]}
```

## How a run works

1. **Static replay.** Each step checks for page drift, tries its selector,
   then its fallbacks, all without AI. A step's `expects` post-condition
   verifies it actually worked, so a "successful" click that changed nothing
   counts as a failure.
2. **Heal on failure only.** Jev picks the element the step meant. The heal
   is refused when the probability is low, when the frame doesn't match, or
   when a Delete step would become a Cancel. It's persisted only if the whole
   run passes, and the heal history stays in the case as a flakiness signal.
3. **Assertions.** Deterministic ones (`url_contains:…`, `text_visible:…`)
   are checked directly. English ones are judged by Jev with a probability.

Every run is a document in Mongo with per-step mode (`static` / `fallback` /
`healed` / `failed`) and which AI calls ran, shown on the console's run page.
`groundhog run` ends by printing `run <id>`.

## Configuration

`.env` holds 5 required values, 3 for the console and 1 optional key.

| Env var | Used for |
|---|---|
| `BASE_URL` | the app under test, e.g. `https://app.example.com` |
| `LOGIN_USER` | login email |
| `LOGIN_PASS` | login password |
| `LOGIN_WORKSPACE` | workspace to select after login |
| `TYPESAFE_API_KEY` | Jev, needed by `new`, heal and English assertions |
| `MONGO_URL` | the console's database, default `mongodb://localhost:27017/groundhog` |
| `ADMIN_EMAIL` | the first admin, created by `groundhog db seed` when there are no users |
| `ADMIN_PASSWORD` | that admin's password; empty generates one and prints it once |
| `ANTHROPIC_API_KEY` | optional: `flow new`, and field values the intent doesn't spell out |

Timeouts, action budgets, probability thresholds and model names are plain
constants in `groundhog/config.py`, each overridable by an env var of the
same name.

## Layout

```
groundhog/               Python package: engine, worker CLI, API
  cli.py                 init · new · run · list · show · flow new|run|list · db seed · serve
  config.py              env, budgets, paths, MONGO_URL
  db.py                  Mongo client, collections, indexes
  events.py              every run event: a console line and the run document
  checks.py              readiness checks shared by init and the Settings screen
  passwords.py           scrypt hash and verify
  jev.py                 TypeSafe client, the questions, usage counter
  browser/               session+login · DOM snapshot+selectors · step execution
  agent/                 authoring loop · flow composer · optional text helper
  llm/client.py          Anthropic wrapper, used only for text
  cases/ runner/         case schema+store · replay orchestration
  api/                   FastAPI: auth, jobs, one router per resource
web/                     the console: Vite, React, TypeScript
start.sh                 checks every dependency, then starts the console
```
