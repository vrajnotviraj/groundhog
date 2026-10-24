"""Readiness checks as data for the health screen, and console user management."""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, StringConstraints
from pymongo.errors import DuplicateKeyError

from groundhog import checks, config, db, events
from groundhog.api.auth import admin_only, current_user
from groundhog.passwords import hash_password

router = APIRouter(dependencies=[Depends(current_user)])
SECRETS = [*checks.REQUIRED, "ANTHROPIC_API_KEY"]


class NewUser(BaseModel):
    email: Annotated[str, StringConstraints(pattern=r"^[^@\s]+@[^@\s]+$", max_length=254)]
    password: Annotated[str, StringConstraints(min_length=8, max_length=200)]
    role: Literal["admin", "member"] = "member"


def without_env_values(detail: str) -> str:
    """Replace any .env value a check echoed with the variable's name."""
    for name in SECRETS:
        if value := getattr(config, name, ""):
            detail = detail.replace(value, name)
    return detail


def as_row(name: str, result: tuple[bool, str]) -> dict:
    return {"name": name, "ok": result[0], "detail": without_env_values(result[1])}


@router.get("/settings/health")
def health() -> dict:
    placeholders = checks.placeholders()
    env = [as_row(n, checks.check_env(n, getattr(config, n, ""), placeholders.get(n))) for n in checks.REQUIRED]
    return {
        "checks": [*env, as_row("Chromium", checks.check_chromium()), as_row("App", checks.check_app()),
                   as_row("Jev", checks.check_jev()), as_row("Mongo", checks.check_mongo())],
        "optional": [{"name": "ANTHROPIC_API_KEY", "set": bool(config.ANTHROPIC_API_KEY),
                      "note": "Unlocks composing flows from English and writing field values the intent leaves out."}],
    }


@router.post("/settings/check-login")
def check_login() -> dict:
    row = as_row("Login", checks.check_login())
    return {"ok": row["ok"], "detail": row["detail"]}


@router.get("/users", dependencies=[Depends(admin_only)])
def list_users() -> list[dict]:
    return [{"id": str(u["_id"]), "email": u["email"], "role": u["role"], "created_at": u["created_at"]}
            for u in db.users().find().sort("email")]


@router.post("/users", status_code=201, dependencies=[Depends(admin_only)])
def add_user(body: NewUser) -> dict:
    user = {"_id": uuid.uuid4().hex, "email": body.email, "password_hash": hash_password(body.password),
            "role": body.role, "created_at": events.now()}
    try:
        db.users().insert_one(user)
    except DuplicateKeyError:
        raise HTTPException(409, f"{body.email} already has an account.")
    return {"id": user["_id"], "email": user["email"], "role": user["role"], "created_at": user["created_at"]}


@router.delete("/users/{user_id}", status_code=204)
def remove_user(user_id: str, admin: dict = Depends(admin_only)) -> None:
    if user_id == str(admin["_id"]):
        raise HTTPException(400, "You cannot remove your own account.")
    if db.users().delete_one({"_id": user_id}).deleted_count == 0:
        raise HTTPException(404, "No such user.")
    db.sessions().delete_many({"user_id": user_id})
