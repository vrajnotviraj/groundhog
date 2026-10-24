"""Run history, the live event stream of one run, its screenshots, cancel and delete."""

import json
import re
import time

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse

from groundhog import db
from groundhog.api import jobs
from groundhog.api.auth import admin_only, current_user

POLL_SECONDS = 0.5
KEEP_ALIVE_SECONDS = 15
OMIT_IN_LISTS = {"events": 0, "partial_trace": 0}  # projection and filter: list views leave the big fields out

router = APIRouter(prefix="/runs", dependencies=[Depends(current_user)])


def summary(run: dict) -> dict:
    """A run document as the lists show it: id instead of _id, without events or trace."""
    return {"id": run["_id"], **{k: v for k, v in run.items() if k not in ("_id", *OMIT_IN_LISTS)}}


def recent(target: str, limit: int) -> list[dict]:
    return [summary(r) for r in db.runs().find({"target": target}, OMIT_IN_LISTS).sort("created_at", -1).limit(limit)]


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
    """Every event past `after`, the status whenever it changes, new events as the worker appends them, then `done`."""
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
