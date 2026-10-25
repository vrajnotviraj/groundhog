"""Run history, the live event stream of one run, its screenshots, cancel and delete."""

import json
import re
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from groundhog import db
from groundhog.api import jobs
from groundhog.api.auth import admin_only, current_user
from groundhog.cases.schema import Name

POLL_SECONDS = 0.5
KEEP_ALIVE_SECONDS = 15
OMIT_IN_LISTS = {"events": 0, "partial_trace": 0}  # large fields that run lists leave out

router = APIRouter(prefix="/runs", dependencies=[Depends(current_user)])


class BatchRun(BaseModel):
    cases: list[Name] = []
    flows: list[Name] = []
    retries: Literal[0, 1, 2] = 1
    heal: bool = True


def summary(run: dict) -> dict:
    """A run as lists show it: `id` instead of `_id`, without events or trace."""
    return {"id": run["_id"], **{k: v for k, v in run.items() if k not in ("_id", *OMIT_IN_LISTS)}}


def recent(target: str, kinds: list[str], limit: int) -> list[dict]:
    """The newest runs of one case or flow, newest first."""
    query = {"target": target, "kind": {"$in": kinds}}
    return [summary(r) for r in db.runs().find(query, OMIT_IN_LISTS).sort("created_at", -1).limit(limit)]


def find(run_id: str) -> dict:
    run = db.runs().find_one({"_id": run_id})
    if run is None:
        raise HTTPException(404, f"No run {run_id}.")
    return run


@router.get("")
def list_runs(limit: int = Query(50, ge=1, le=500), kind: str = "", status: str = "", target: str = "") -> list[dict]:
    query = {k: v for k, v in (("kind", kind), ("status", status)) if v}
    if target:
        query["target"] = {"$regex": re.escape(target), "$options": "i"}
    return [summary(r) for r in db.runs().find(query, OMIT_IN_LISTS).sort("created_at", -1).limit(limit)]


@router.post("/batch")
def batch_run(body: BatchRun, user: dict = Depends(current_user)) -> dict:
    """Queue one run per case and flow; nothing starts when a name is unknown. Flows never retry."""
    for collection, label, names in ((db.cases(), "case", body.cases), (db.flows(), "flow", body.flows)):
        if missing := next((n for n in names if not collection.find_one({"_id": n}, {"_id": 1})), None):
            raise HTTPException(404, f"No {label} named {missing}.")
    case_flags = jobs.run_flags(jobs.RunRequest(heal=body.heal, retries=body.retries))
    flow_flags = jobs.run_flags(jobs.RunRequest(heal=body.heal))
    return {"run_ids": [jobs.start("run", n, ["run", n, *case_flags], user) for n in body.cases]
            + [jobs.start("flow", n, ["flow", "run", n, *flow_flags], user) for n in body.flows]}


@router.get("/{run_id}")
def get_run(run_id: str) -> dict:
    run = find(run_id)
    return {"id": run.pop("_id"), **run}


@router.get("/{run_id}/events")
def stream_events(run_id: str, after: int = 0) -> StreamingResponse:
    find(run_id)
    return StreamingResponse(event_stream(run_id, after), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def event_stream(run_id: str, after: int):
    """Yield events after `after`, then new ones as they arrive, the status when it changes, and `done` at the end."""
    last_beat = time.monotonic()
    sent_status = None
    while run := db.runs().find_one({"_id": run_id}):
        for event in run["events"]:
            if event["seq"] > after:
                after = event["seq"]
                yield f"data: {json.dumps(event, default=str)}\n\n"
        if run["status"] not in jobs.ACTIVE:
            yield f"event: done\ndata: {json.dumps(summary(run), default=str)}\n\n"
            return
        if run["status"] != sent_status:
            sent_status = run["status"]
            yield f"event: status\ndata: {json.dumps({'status': sent_status})}\n\n"
        if time.monotonic() - last_beat >= KEEP_ALIVE_SECONDS:
            last_beat = time.monotonic()
            yield ": keep-alive\n\n"
        time.sleep(POLL_SECONDS)


@router.get("/{run_id}/shots/{seq}")
def get_shot(run_id: str, seq: int) -> Response:
    shot = db.shots().find_one({"run_id": run_id, "seq": seq})
    if shot is None:
        raise HTTPException(404, f"No screenshot {seq} on run {run_id}.")
    return Response(bytes(shot["jpeg"]), media_type="image/jpeg")


@router.post("/{run_id}/cancel", status_code=204)
def cancel_run(run_id: str) -> None:
    if find(run_id)["status"] not in jobs.ACTIVE:
        raise HTTPException(409, "This run has already finished.")
    if not jobs.cancel(run_id):
        raise HTTPException(409, "This run was not started from this console, so it cannot be cancelled here.")


@router.delete("/{run_id}", status_code=204, dependencies=[Depends(admin_only)])
def delete_run(run_id: str) -> None:
    if db.runs().delete_one({"_id": run_id}).deleted_count == 0:
        raise HTTPException(404, f"No run {run_id}.")
    db.shots().delete_many({"run_id": run_id})
