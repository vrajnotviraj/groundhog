"""Start worker processes for runs, close runs whose worker crashed, and cancel them."""

import signal
import subprocess
import sys
import threading
import uuid
from typing import Annotated

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


WORKER = [sys.executable, "-m", "groundhog.cli"]
ACTIVE = ["queued", "running"]

_workers: dict[str, subprocess.Popen] = {}


def var_args(vars: dict[str, str]) -> list[str]:
    return [arg for k, v in vars.items() for arg in ("--var", f"{k}={v}")]


def run_flags(body: RunRequest) -> list[str]:
    """The CLI options for a replay request: vars, headed and no-heal."""
    return [*var_args(body.vars), *(["--headed"] if body.headed else []), *([] if body.heal else ["--no-heal"])]


def start(kind: str, target: str, args: list[str], user: dict) -> str:
    """Insert a queued run, spawn its worker and return the run id."""
    run_id = uuid.uuid4().hex[:12]
    db.runs().insert_one({"_id": run_id, "kind": kind, "target": target, "vars": {}, "status": "queued",
                          "created_at": events.now(), "started_by": user["email"], "events": []})
    worker = subprocess.Popen([*WORKER, *args, "--run-id", run_id], cwd=config.ROOT,
                              stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    _workers[run_id] = worker
    db.runs().update_one({"_id": run_id}, {"$set": {"pid": worker.pid}})
    threading.Thread(target=wait_for_exit, args=(run_id, worker), daemon=True).start()
    return run_id


def wait_for_exit(run_id: str, worker: subprocess.Popen) -> None:
    """Wait for the worker to exit; close its run as an error if the worker did not."""
    _, stderr = worker.communicate()
    _workers.pop(run_id, None)
    error = "cancelled" if worker.returncode == -signal.SIGTERM else stderr[-2000:] or f"exit {worker.returncode}"
    db.runs().update_one({"_id": run_id, "status": {"$in": ACTIVE}},
                         {"$set": {"status": "error", "error": error, "finished_at": events.now()}})


def close_orphaned_runs() -> None:
    """Close as an error every open run a previous server spawned; its worker died with that server."""
    db.runs().update_many({"status": {"$in": ACTIVE}, "pid": {"$exists": True}},
                          {"$set": {"status": "error", "error": "server stopped", "finished_at": events.now()}})


def cancel(run_id: str) -> bool:
    """Send SIGTERM to the run's worker; False when this server is not running it."""
    worker = _workers.get(run_id)
    if worker is None:
        return False
    worker.terminate()
    return True
