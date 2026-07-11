"""Load/save cases (cases/) and flows (flows/) as pretty JSON, plus {{var}} rendering."""

import re

from groundhog.config import CASES_DIR, FLOWS_DIR
from groundhog.cases.schema import Case, Flow

VAR = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def render(text: str, vars: dict[str, str] | None = None) -> str:
    """Substitute {{name}} template vars. Applied to values, assertions, and
    selectors at run time, so one case serves many data values — including a
    step that targets an entity created earlier in the same run by its
    per-run name."""
    return VAR.sub(lambda m: (vars or {}).get(m.group(1), m.group(0)), text)


def case_path(name: str):
    return CASES_DIR / f"{name}.json"


def load(name: str) -> Case:
    return Case.model_validate_json(case_path(name).read_text())


def save(case: Case) -> None:
    CASES_DIR.mkdir(exist_ok=True)
    case_path(case.name).write_text(case.model_dump_json(indent=2) + "\n")


def list_cases() -> list[Case]:
    return [Case.model_validate_json(p.read_text()) for p in sorted(CASES_DIR.glob("*.json"))]


def load_flow(name: str) -> Flow:
    return Flow.model_validate_json((FLOWS_DIR / f"{name}.json").read_text())


def save_flow(flow: Flow) -> None:
    FLOWS_DIR.mkdir(exist_ok=True)
    (FLOWS_DIR / f"{flow.name}.json").write_text(flow.model_dump_json(indent=2) + "\n")


def list_flows() -> list[Flow]:
    return [Flow.model_validate_json(p.read_text()) for p in sorted(FLOWS_DIR.glob("*.json"))]
