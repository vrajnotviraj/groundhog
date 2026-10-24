"""Saved flows: list, read, save, delete, and start a flow run or a compose run."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel

from groundhog import db
from groundhog.api import jobs
from groundhog.api.auth import admin_only, current_user
from groundhog.api.runs import recent
from groundhog.cases import store
from groundhog.cases.schema import Flow

router = APIRouter(prefix="/flows", dependencies=[Depends(current_user)])
FlowName = Annotated[str, Path(pattern=jobs.NAME)]


class ComposeFlow(BaseModel):
    intent: jobs.Intent
    name: jobs.Name | None = None
    headed: bool = False


@router.get("")
def list_flows() -> list[dict]:
    return [{**f, "last_run": next(iter(recent(f["name"], 1)), None)}
            for f in db.flows().find({}, {"_id": 0}).sort("name")]


@router.get("/{name}")
def get_flow(name: FlowName) -> dict:
    flow = db.flows().find_one({"_id": name}, {"_id": 0})
    if flow is None:
        raise HTTPException(404, f"No flow named {name}.")
    return {**flow, "runs": recent(name, 10)}


@router.put("/{name}")
def put_flow(name: FlowName, flow: Flow) -> dict:
    if flow.name != name:
        raise HTTPException(422, f"The flow is named {flow.name}, but it is being saved as {name}.")
    store.save_flow(flow)
    return flow.model_dump()


@router.delete("/{name}", status_code=204, dependencies=[Depends(admin_only)])
def delete_flow(name: FlowName) -> None:
    if not store.delete_flow(name):
        raise HTTPException(404, f"No flow named {name}.")


@router.post("/compose")
def compose_flow(body: ComposeFlow, user: dict = Depends(current_user)) -> dict:
    args = ["flow", "new", body.intent]
    args += ["--name", body.name] if body.name else []
    args += ["--headed"] if body.headed else []
    return {"run_id": jobs.start("compose", body.name or "", args, user)}


@router.post("/{name}/run")
def run_flow(name: FlowName, body: jobs.RunRequest, user: dict = Depends(current_user)) -> dict:
    try:
        store.load_flow(name)
    except KeyError:
        raise HTTPException(404, f"No flow named {name}.")
    args = ["flow", "run", name, *jobs.var_args(body.vars)]
    args += ["--headed"] if body.headed else []
    args += [] if body.heal else ["--no-heal"]
    return {"run_id": jobs.start("flow", name, args, user)}
