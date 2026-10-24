"""Runs are worker processes: the API inserts a queued run document and spawns the CLI to fill it.

A reaper thread per process waits for it to exit and marks the run as an error if the worker
never closed it, keeping the tail of its stderr as the reason.
"""

import signal
import subprocess
import sys
import threading
import uuid
from typing import Annotated

from pydantic import BaseModel, StringConstraints

from groundhog import config, db, events
from groundhog.cases.store import NAME

Name = Annotated[str, StringConstraints(pattern=NAME)]
Vars = dict[Annotated[str, StringConstraints(pattern=r"^\w{1,64}$")], Annotated[str, StringConstraints(max_length=500)]]
# An intent is a CLI argument, so it may not start with a dash and be read as an option.
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


def start(kind: str, target: str, args: list[str], user: dict) -> str:
    """Insert a queued run, spawn its worker and return the run id."""
    run_id = uuid.uuid4().hex[:12]
    db.runs().insert_one({"_id": run_id, "kind": kind, "target": target, "vars": {}, "status": "queued",
                          "created_at": events.now(), "started_by": user["email"], "events": []})
    worker = subprocess.Popen([*WORKER, *args, "--run-id", run_id], cwd=config.ROOT,
                              stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    _workers[run_id] = worker
    db.runs().update_one({"_id": run_id}, {"$set": {"pid": worker.pid}})
    threading.Thread(target=reap, args=(run_id, worker), daemon=True).start()
    return run_id


def reap(run_id: str, worker: subprocess.Popen) -> None:
    """Wait for the worker to exit; close its run as an error if the worker did not."""
    _, stderr = worker.communicate()
    _workers.pop(run_id, None)
    error = "cancelled" if worker.returncode == -signal.SIGTERM else stderr[-2000:] or f"exit {worker.returncode}"
    db.runs().update_one({"_id": run_id, "status": {"$in": ACTIVE}},
                         {"$set": {"status": "error", "error": error, "finished_at": events.now()}})


def cancel(run_id: str) -> bool:
    """Send SIGTERM to the run's worker; False when this server is not running it."""
    worker = _workers.get(run_id)
    if worker is None:
        return False
    worker.terminate()
    return True
