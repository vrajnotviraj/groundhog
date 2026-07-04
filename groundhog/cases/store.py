"""Load/save cases as pretty JSON in cases/, plus {{var}} template rendering."""

import json
import re

from groundhog.config import CASES_DIR
from groundhog.cases.schema import Case

VAR = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def render(text: str, vars: dict[str, str] | None = None) -> str:
    """Substitute {{name}} template vars. Applied to values and assertions at
    run time — never to selectors, so one case serves many data values."""
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
