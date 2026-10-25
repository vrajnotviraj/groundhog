"""Propose test intents a QA engineer could author, from product docs, the saved cases and the map's gaps.

One structured-output Anthropic call. The API saves what comes back.
"""

from pydantic import BaseModel, Field

from groundhog.llm import client

SUGGESTER = """\
You suggest browser tests for a web app. A QA engineer will hand each suggestion to an agent that authors the test \
against the live app, so each one has to work as written.

Each suggestion is one user-sized flow that ends in an outcome you can check on screen, written like "create an SMS \
template named {{name}} and verify it appears in the templates list". Rules:

- Self-sufficient: it starts from its own page and does not rely on another test having run first.
- Data that has to be unique per run goes in a {{var}} placeholder, and vars gives each one a plain default such as \
gh-suggested. Never put {{stamp}} in a default; the runner fills empty vars itself.
- Never a duplicate of a saved case. The saved cases are listed as `name: intent` lines.
- Grounded in the docs text and the coverage gaps you are given. Gaps come first: a create or delete control that no \
case exercises is the best place to start, and an unexercised delete on a page whose create is covered is the best \
suggestion of all.
- Never deletes or changes data the test did not create itself. A delete test creates its own entity first.
- name is short kebab-case, lowercase letters, digits and dashes.
- why is one sentence: the gap or the docs passage it covers."""


class Pair(BaseModel):
    var: str = Field(description="var name as it appears inside {{ }}")
    value: str = Field(description="plain default value, e.g. gh-suggested")


class Suggestion(BaseModel):
    name: str = Field(description="short kebab-case case name")
    intent: str = Field(description="plain-English test intent with {{var}} placeholders, ending in a check")
    why: str = Field(description="one sentence: the gap or docs passage this covers")
    # A list of pairs: strict structured output returns {} for dict fields.
    vars: list[Pair] = Field(default_factory=list, description="a default for every {{var}} in the intent")


class Suggestions(BaseModel):
    suggestions: list[Suggestion]


def suggest(docs_text: str, catalog: list[str], gaps: list[str], count: int) -> list[Suggestion]:
    """Ask for `count` new test intents grounded in the docs and the gaps."""
    user = (f"Suggest {count} tests.\n\nSaved cases:\n{lines(catalog)}\n\nCoverage gaps:\n{lines(gaps)}\n\n"
            f"Docs:\n{docs_text or '(none)'}")
    return client.parse(user=user, output_model=Suggestions, system=SUGGESTER).suggestions[:count]


def lines(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items) or "(none)"
