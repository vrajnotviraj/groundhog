<p align="center">
  <img src="assets/groundhog.svg" width="160" alt="groundhog mascot">
</p>

<h1 align="center">groundhog</h1>

<p align="center"><b>Describe a test in English once. Replay it forever, for free.</b></p>

Groundhog is end-to-end testing for SaaS apps. You write what a user does in a sentence, and groundhog turns it into a test that runs on every deploy without calling an AI model.

## The problem

AI agents can click through a browser now. You've seen the demos.

But they forget everything between runs. The thousandth run of the same test looks exactly like the first: the agent reads the page, hunts for the same button, and pays for the same tokens. Your test bill grows with every deploy, and the test is only as steady as the model's mood that day.

Groundhog pays that cost once.

## How it works

**1. Describe it.** Type the test the way you'd explain it to a new teammate:

> Create an SMS template named {{name}} and verify it appears in the templates list.

**2. Groundhog drives your app, once.** It opens your real app, does the task, and saves every step it took as plain, readable selectors. The `{{name}}` becomes a variable, so the same test can run with fresh data every time.

**3. Every run after that is free.** Replays read the saved steps and check each one. That takes a few seconds per test and 0 model calls.

**4. When your UI changes, it heals.** If a button moves or gets renamed, 1 small AI call finds the element the step meant, checks that it worked, and updates the saved test. A heal is only kept when the whole run passes, so a bad guess never sticks.

Like the movie. It wakes up, lives the same day again, and gets a little better at it each time.

## What you can do

**Write tests in English.** One sentence per test. Groundhog does the clicking, picks durable selectors (test ids first, then labels and roles), and adds a check after each step so a click that did nothing counts as a failure.

**Run them with different data.** Every `{{variable}}` is filled at run time. Leave it empty and groundhog stamps a fresh value like `gh-1729`, so 2 runs never trip over each other's leftovers.

**Chain tests into flows.** A flow strings saved tests into a longer story: create a template, use it in a campaign, delete both. One browser, one login, shared variables. Describe the whole flow in English and groundhog reuses the tests you already have and writes the missing ones in the same pass.

**Clean up after yourself.** Cleanup steps in a flow run even when the flow fails, and a flow only passes when its cleanup passes too.

**Check things in plain English.** "The template appears in the list" works as an assertion. Groundhog judges it against the final page and shows how confident it is. Exact checks like "the URL contains /templates" skip the AI completely.

**See where your AI money goes.** Every run reports how many AI calls it made and why. A passing test with no English assertions makes 0, and the run page says so.

## The console

Everything lives in a web console your whole team can sign into. A run you start from the terminal shows up there too, live.

**Overview.** Opens with the day's verdict in big type: "All 10 runs passed" or "1 of 10 failed today". A strip of today's runs sits under it, one square per run in green or red, and the latest runs are listed below.

**Cases.** Every test with its steps, its last run and a yellow tag when it has healed. Search by name or intent, run any test in 1 click, or write a new one from a sentence.

**Flows.** Build a chain from your saved tests, set shared variables and cleanup, or describe a new flow in English.

**Run.** Watch a test as it happens. Each step lands as a tile coloured by how it ran (replayed, used a fallback, healed or failed), with a screenshot of the page after each step. Click a tile to jump to that step. When the run ends you see every assertion, its reasoning and what it cost.

**Runs.** The full history, filtered by kind, status or test name.

**Settings.** A health check for everything groundhog needs (the app, the login, the database, the AI service), plus users and roles.

### Meet the groundhog

The console has a mascot, and it tells you how things are going.

It pops out of its burrow in front of a sunrise. When every run passed, it squints happily. When something failed, it sinks lower and looks worried. While a run is live, it rocks back and forth digging. With nothing run yet, it's asleep in its hole. And while you type your password on the login screen, it squeezes its eyes shut.

You'll find it on the Overview, on every run, on empty pages, in the top bar while a run is live, and on the health screen.

## Safe with your credentials

Groundhog signs in through your app's own login API, so SSO-only login pages are fine. Your username and password stay in your own config. They never go to a model and never appear in a saved test, a screenshot or a page snapshot. Password fields are stripped before anything leaves the browser.

The console needs a signed-in session for everything except the login page. Passwords are hashed, and there are 2 roles: admins manage users and delete things, members do the rest.

## Try it

You need Node 20+, [uv](https://docs.astral.sh/uv/), MongoDB (or Docker), a TypeSafe API key from [console.typesafe.ai](https://console.typesafe.ai) and an app to test.

```sh
git clone <this repo> && cd groundhog
./start.sh
```

The script checks everything, tells you what's missing, and opens the console at http://localhost:8000. Fill in `.env` with your app's URL and a test login, run it again, and write your first test.

Prefer the terminal? The same engine has a CLI: `uv run groundhog --help`.
