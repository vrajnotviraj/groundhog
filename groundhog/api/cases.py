"""Saved cases: list, read, save, delete, and start a replay or an authoring run."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, StringConstraints

from groundhog import db
from groundhog.api import jobs
from groundhog.api.auth import admin_only, current_user
from groundhog.api.runs import recent
from groundhog.cases import store
from groundhog.cases.schema import Case

router = APIRouter(prefix="/cases", dependencies=[Depends(current_user)])
CaseName = Annotated[str, Path(pattern=jobs.NAME)]


class AuthorCase(BaseModel):
    intent: jobs.Intent
    name: jobs.Name | None = None
    vars: jobs.Vars = {}
    start: Annotated[str, StringConstraints(pattern=r"^/\S{0,500}$")] = "/:ws/home"
    headed: bool = False


@router.get("")
def list_cases() -> list[dict]:
    return [{"name": c["_id"], "intent": c["intent"], "steps": len(c["steps"]), "runs": c["meta"]["runs"],
             "heals": len(c["meta"]["heals"]), "start_path": c["start_path"], "updated_at": c.get("updated_at"),
             "last_run": next(iter(recent(c["_id"], 1)), None)}
            for c in db.cases().find().sort("_id")]


@router.get("/{name}")
def get_case(name: CaseName) -> dict:
    case = db.cases().find_one({"_id": name}, {"_id": 0})
    if case is None:
        raise HTTPException(404, f"No case named {name}.")
    return {**case, "runs": recent(name, 10)}


@router.put("/{name}")
def put_case(name: CaseName, case: Case) -> dict:
    if case.name != name:
        raise HTTPException(422, f"The case is named {case.name}, but it is being saved as {name}.")
    store.save(case)
    return case.model_dump()


@router.delete("/{name}", status_code=204, dependencies=[Depends(admin_only)])
def delete_case(name: CaseName) -> None:
    if not store.delete(name):
        raise HTTPException(404, f"No case named {name}.")


@router.post("/author")
def author_case(body: AuthorCase, user: dict = Depends(current_user)) -> dict:
    args = ["new", body.intent, *jobs.var_args(body.vars), "--start", body.start]
    args += ["--name", body.name] if body.name else []
    args += ["--headed"] if body.headed else []
    return {"run_id": jobs.start("author", body.name or "", args, user)}


@router.post("/{name}/run")
def run_case(name: CaseName, body: jobs.RunRequest, user: dict = Depends(current_user)) -> dict:
    try:
        store.load(name)
    except KeyError:
        raise HTTPException(404, f"No case named {name}.")
    args = ["run", name, *jobs.var_args(body.vars)]
    args += ["--headed"] if body.headed else []
    args += [] if body.heal else ["--no-heal"]
    return {"run_id": jobs.start("run", name, args, user)}
