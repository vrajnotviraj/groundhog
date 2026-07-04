"""SMART planner: intent + graph slice → ordered draft plan.

The graph is an accelerator, never a prerequisite — an empty slice just means
the planner is told to expect live exploration.
"""

from pydantic import BaseModel, Field

from groundhog.llm import client


class Plan(BaseModel):
    start_path: str = Field(description="path the test starts at, /:ws/ for the workspace segment")
    steps: list[str] = Field(description="ordered plain-English sub-goals")
    notes: str = Field(default="", description="anything the executor should know")


def graph_slice(intent: str) -> str:
    """Route + elements context from Neo4j (≤ ~1.5k tokens); empty when the
    graph is down or knows nothing relevant."""
    try:
        from groundhog.graph.queries import slice_for_intent

        return slice_for_intent(intent)
    except Exception:
        return ""


def plan(intent: str) -> tuple[Plan, bool]:
    """Returns the draft plan and whether a graph slice informed it."""
    sliced = graph_slice(intent)
    context = (f"Intent: {intent}\n\n"
               + (f"Known app graph (verified — reuse it):\n{sliced}"
                  if sliced else
                  "(The app graph has nothing for this area yet — the executor will explore live, "
                  "and everything it finds is remembered for next time.)"))
    result = client.parse(
        user="Produce the draft plan.",
        output_model=Plan,
        system=client.prompt("planner", context=context),
        model=client.SMART,
    )
    return result, bool(sliced)
