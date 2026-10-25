"""Start worker processes for runs, close runs whose worker crashed, and cancel them."""

import signal
import subprocess
import sys
import threading
import uuid
from typing import Annotated, Literal

from fastapi import Path
from pydantic import BaseModel, StringConstraints

from groundhog import config, db, events
from groundhog.cases.schema import NAME

PathName = Annotated[str, Path(pattern=NAME)]
Vars = dict[Annotated[str, StringConstraints(pattern=r"^\w{1,64}$")], Annotated[str, StringConstraints(max_length=500)]]
# An intent is passed as a CLI argument, so it must not start with a dash.
Intent = Annotated[str, StringConstraints(pattern=r"^[^-\s]", max_length=2000)]


class RunRequest(BaseModel):
    vars: Vars = {}
    headed: bool = False
    heal: bool = True
    retries: Literal[0, 1, 2] = 0


WORKER = [sys.executable, "-m", "groundhog.cli"]
ACTIVE = ["queued", "running"]

_workers: dict[str, subprocess.Popen] = {}
_waiting: dict[str, list[str]] = {}  # queued run id -> worker arguments, oldest first
_lock = threading.Lock()


def var_args(vars: dict[str, str]) -> list[str]:
    return [arg for k, v in vars.items() for arg in ("--var", f"{k}={v}")]


def run_flags(body: RunRequest) -> list[str]:
    """The CLI options for a replay request: vars, headed, no-heal and retries."""
    return [*var_args(body.vars), *(["--headed"] if body.headed else []), *([] if body.heal else ["--no-heal"]),
            *(["--retries", str(body.retries)] if body.retries else [])]


def start(kind: str, target: str, args: list[str], user: dict) -> str:
    """Insert a queued run, start it if a worker is free, and return the run id."""
    run_id = uuid.uuid4().hex[:12]
    db.runs().insert_one({"_id": run_id, "kind": kind, "target": target, "vars": {}, "status": "queued", "pid": None,
                          "created_at": events.now(), "started_by": user["email"], "events": []})
    with _lock:
        _waiting[run_id] = [*args, "--run-id", run_id]
    dispatch()
    return run_id


def dispatch() -> None:
    """Start workers for the oldest queued runs while fewer than MAX_WORKERS are alive."""
    with _lock:
        while _waiting and len(_workers) < config.MAX_WORKERS:
            run_id = next(iter(_waiting))
            worker = subprocess.Popen([*WORKER, *_waiting.pop(run_id)], cwd=config.ROOT,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            _workers[run_id] = worker
            db.runs().update_one({"_id": run_id}, {"$set": {"pid": worker.pid}})
            threading.Thread(target=wait_for_exit, args=(run_id, worker), daemon=True).start()


def wait_for_exit(run_id: str, worker: subprocess.Popen) -> None:
    """Wait for the worker to exit, close its run as an error if the worker did not, then start the next run."""
    _, stderr = worker.communicate()
    _workers.pop(run_id, None)
    error = "cancelled" if worker.returncode == -signal.SIGTERM else stderr[-2000:] or f"exit {worker.returncode}"
    db.runs().update_one({"_id": run_id, "status": {"$in": ACTIVE}},
                         {"$set": {"status": "error", "error": error, "finished_at": events.now()}})
    dispatch()


def close_orphaned_runs() -> None:
    """Close as an error every open run a previous server queued or spawned; it died with that server."""
    db.runs().update_many({"status": {"$in": ACTIVE}, "pid": {"$exists": True}},
                          {"$set": {"status": "error", "error": "server stopped", "finished_at": events.now()}})


def cancel(run_id: str) -> bool:
    """Stop the run's worker, or drop it from the queue; False when this server is not running it."""
    with _lock:
        if _waiting.pop(run_id, None) is not None:
            db.runs().update_one({"_id": run_id}, {"$set": {"status": "error", "error": "cancelled",
                                                             "finished_at": events.now()}})
            return True
    worker = _workers.get(run_id)
    if worker is None:
        return False
    worker.terminate()
    return True
