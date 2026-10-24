"""Cases and flows live in Mongo, one document per name, plus {{var}} rendering."""

import re
from datetime import datetime, timezone

from groundhog import db
from groundhog.cases.schema import Case, Flow

VAR = re.compile(r"\{\{\s*(\w+)\s*\}\}")
NAME = r"^[a-z0-9][a-z0-9-]{0,63}$"  # case and flow names: lowercase kebab-case


def render(text: str, vars: dict[str, str] | None = None) -> str:
    """Substitute {{name}} template vars. Applied to values, assertions, and
    selectors at run time, so one case serves many data values — including a
    step that targets an entity created earlier in the same run by its
    per-run name."""
    return VAR.sub(lambda m: (vars or {}).get(m.group(1), m.group(0)), text)


def missing_vars(case: Case, vars: dict[str, str] | None) -> list[str]:
    """{{var}}s the intent declares that the caller did not supply; running with them
    unrendered types the literal braces into the app. Only the intent counts: step
    values may carry the app's own {{placeholders}}, which are content, not vars."""
    used = dict.fromkeys(VAR.findall(case.intent))
    return [k for k in used if not (vars or {}).get(k)]  # unset or empty both type braces


def _put(collection, model) -> None:
    doc = {"_id": model.name, **model.model_dump(), "updated_at": datetime.now(timezone.utc).isoformat()}
    collection.replace_one({"_id": model.name}, doc, upsert=True)


def _fields(doc: dict) -> dict:
    return {k: v for k, v in doc.items() if k not in ("_id", "updated_at")}


def _get(collection, cls, name: str):
    doc = collection.find_one({"_id": name})
    if doc is None:
        raise KeyError(f"no saved {cls.__name__.lower()} named {name}")
    return cls.model_validate(_fields(doc))


def _all(collection, cls) -> list:
    return [cls.model_validate(_fields(d)) for d in collection.find().sort("_id")]


def load(name: str) -> Case:
    return _get(db.cases(), Case, name)


def save(case: Case) -> None:
    _put(db.cases(), case)


def delete(name: str) -> bool:
    return db.cases().delete_one({"_id": name}).deleted_count == 1


def list_cases() -> list[Case]:
    return _all(db.cases(), Case)


def load_flow(name: str) -> Flow:
    return _get(db.flows(), Flow, name)


def save_flow(flow: Flow) -> None:
    _put(db.flows(), flow)


def delete_flow(name: str) -> bool:
    return db.flows().delete_one({"_id": name}).deleted_count == 1


def list_flows() -> list[Flow]:
    return _all(db.flows(), Flow)
