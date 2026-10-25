"""Saved cases: list, read, save, delete, and start a replay or an authoring run."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, StringConstraints

from groundhog import db
from groundhog.api import jobs
from groundhog.api.auth import admin_only, current_user
from groundhog.api.runs import recent
from groundhog.cases import store
from groundhog.cases.schema import Case, Name

router = APIRouter(prefix="/cases", dependencies=[Depends(current_user)])
RUN_KINDS = ["run", "author"]


class AuthorCase(BaseModel):
    intent: jobs.Intent
    name: Name | None = None
    vars: jobs.Vars = {}
    start: Annotated[str, StringConstraints(pattern=r"^/\S{0,500}$")] = "/:ws/home"
    headed: bool = False


def health(name: str, case: dict) -> dict:
    """Outcomes and average duration of the case's last 10 finished replays, oldest first, and its heals."""
    query = {"target": name, "kind": "run", "status": {"$in": ["passed", "failed", "error"]}}
    runs = list(db.runs().find(query, {"status": 1, "flaky": 1, "total_ms": 1}).sort("created_at", -1).limit(10))[::-1]
    durations = [r["total_ms"] for r in runs if r.get("total_ms") is not None]
    return {"runs": len(runs), "passed": sum(r["status"] == "passed" for r in runs),
            "flaky": sum(bool(r.get("flaky")) for r in runs),
            "avg_ms": sum(durations) // len(durations) if durations else None, "heals": len(case["meta"]["heals"]),
            "history": [{"id": r["_id"], "status": r["status"], "flaky": bool(r.get("flaky"))} for r in runs]}


@router.get("")
def list_cases() -> list[dict]:
    return [{"name": c["_id"], "intent": c["intent"], "steps": len(c["steps"]), "runs": c["meta"]["runs"],
             "heals": len(c["meta"]["heals"]), "start_path": c["start_path"], "updated_at": c.get("updated_at"),
             "last_run": next(iter(recent(c["_id"], RUN_KINDS, 1)), None), "health": health(c["_id"], c)}
            for c in db.cases().find().sort("_id")]


@router.get("/{name}")
def get_case(name: jobs.PathName) -> dict:
    case = db.cases().find_one({"_id": name}, {"_id": 0})
    if case is None:
        raise HTTPException(404, f"No case named {name}.")
    return {**case, "runs": recent(name, RUN_KINDS, 10), "health": health(name, case)}


@router.put("/{name}")
def put_case(name: jobs.PathName, case: Case) -> dict:
    if case.name != name:
        raise HTTPException(422, f"The case is named {case.name}, but it is being saved as {name}.")
    store.save(case)
    return case.model_dump()


@router.delete("/{name}", status_code=204, dependencies=[Depends(admin_only)])
def delete_case(name: jobs.PathName) -> None:
    if not store.delete(name):
        raise HTTPException(404, f"No case named {name}.")


@router.post("/author")
def author_case(body: AuthorCase, user: dict = Depends(current_user)) -> dict:
    args = ["new", body.intent, *jobs.var_args(body.vars), "--start", body.start]
    args += ["--name", body.name] if body.name else []
    args += ["--headed"] if body.headed else []
    return {"run_id": jobs.start("author", body.name or "", args, user)}


@router.post("/{name}/run")
def run_case(name: jobs.PathName, body: jobs.RunRequest, user: dict = Depends(current_user)) -> dict:
    try:
        store.load(name)
    except KeyError:
        raise HTTPException(404, f"No case named {name}.")
    return {"run_id": jobs.start("run", name, ["run", name, *jobs.run_flags(body)], user)}
