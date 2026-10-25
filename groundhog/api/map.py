"""The crawled pages grouped by section, the cases that cover each one, the gaps, and starting a crawl."""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, StringConstraints

from groundhog import config, db
from groundhog.api import jobs
from groundhog.api.auth import current_user
from groundhog.cases import store
from groundhog.cases.schema import Case

router = APIRouter(prefix="/map", dependencies=[Depends(current_user)])
GAP_KINDS = ("mutation", "destructive")


class Crawl(BaseModel):
    scope: Annotated[str, StringConstraints(pattern=r"^/\S{0,200}$")] = "/"
    max_pages: int = Field(config.CRAWL_MAX_PAGES, ge=1, le=200)
    headed: bool = False


@router.get("")
def get_map() -> dict:
    pages = list(db.pages().find().sort("_id"))
    cases = store.list_cases()
    visits = {c.name: run_paths(c.name) or case_paths(c) for c in cases}
    sections: dict[str, list[dict]] = {}
    for p in pages:
        sections.setdefault(p["section"], []).append(
            {"path": p["_id"], "title": p["title"], "controls": p["controls"], "links": p["links"],
             "cases": sorted(name for name, paths in visits.items() if p["_id"] in paths),
             "last_seen": p["last_seen"]})
    return {"crawled_at": max((p["last_seen"] for p in pages), default=None),
            "sections": [{"name": name, "covered": sum(bool(row["cases"]) for row in rows), "total": len(rows),
                          "pages": rows} for name, rows in sorted(sections.items())],
            "gaps": gaps([row for rows in sections.values() for row in rows], cases)}


def run_paths(name: str) -> set[str]:
    """The pages the case's newest finished replay visited; empty when no replay recorded them."""
    run = db.runs().find_one({"target": name, "kind": "run", "status": {"$in": ["passed", "failed", "error"]},
                              "paths": {"$exists": True}}, {"paths": 1}, sort=[("created_at", -1)])
    return set(run["paths"]) if run else set()


def case_paths(case: Case) -> set[str]:
    """The pages a saved case names: its start path, its goto steps and its url_contains expects."""
    paths = [case.start_path, *(s.value for s in case.steps if s.action == "goto" and s.value),
             *(s.expects.value for s in case.steps if s.expects and s.expects.kind == "url_contains")]
    keys = (config.ws_path(p) for p in paths)
    return {k if k.startswith("/:ws") else "/:ws" + k for k in keys}


def gaps(rows: list[dict], cases: list[Case]) -> list[dict]:
    """Create and delete controls whose label no step of a case covering their page mentions."""
    steps = {c.name: [s.description.lower() for s in c.steps] for c in cases}
    return [{"path": row["path"], "control": control, "why": "no case exercises it"}
            for row in rows for control in row["controls"]
            if control["kind"] in GAP_KINDS
            and not any(control["label"].lower() in d for name in row["cases"] for d in steps[name])]


@router.post("/crawl")
def start_crawl(body: Crawl, user: dict = Depends(current_user)) -> dict:
    args = ["crawl", "--scope", body.scope, "--max-pages", str(body.max_pages), *(["--headed"] if body.headed else [])]
    return {"run_id": jobs.start("crawl", body.scope, args, user)}
