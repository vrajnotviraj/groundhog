"""The health screen's readiness checks, and console user management."""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, StringConstraints
from pymongo.errors import DuplicateKeyError

from groundhog import config, db, events, setup_checks
from groundhog.api.auth import admin_only, current_user
from groundhog.api.passwords import hash_password

router = APIRouter(dependencies=[Depends(current_user)])
SECRETS = [*setup_checks.REQUIRED, "ANTHROPIC_API_KEY"]


class NewUser(BaseModel):
    email: Annotated[str, StringConstraints(pattern=r"^[^@\s]+@[^@\s]+$", max_length=254)]
    password: Annotated[str, StringConstraints(min_length=8, max_length=200)]
    role: Literal["admin", "member"] = "member"


def without_env_values(detail: str) -> str:
    """Replace any .env value in a check's detail with the variable's name."""
    for name in SECRETS:
        if value := getattr(config, name, ""):
            detail = detail.replace(value, name)
    return detail


def as_row(name: str, ok: bool, detail: str) -> dict:
    return {"name": name, "ok": ok, "detail": without_env_values(detail)}


def user_row(user: dict) -> dict:
    return {"id": user["_id"], "email": user["email"], "role": user["role"], "created_at": user["created_at"]}


@router.get("/settings/health")
def health() -> dict:
    return {
        "checks": [as_row(*check) for check in setup_checks.all_checks()],
        "optional": [{"name": "ANTHROPIC_API_KEY", "set": bool(config.ANTHROPIC_API_KEY),
                      "note": "Unlocks composing flows from English and writing field values the intent leaves out."}],
    }


@router.post("/settings/check-login")
def check_login() -> dict:
    return as_row("Login", *setup_checks.check_login())


@router.get("/users", dependencies=[Depends(admin_only)])
def list_users() -> list[dict]:
    return [user_row(u) for u in db.users().find().sort("email")]


@router.post("/users", status_code=201, dependencies=[Depends(admin_only)])
def add_user(body: NewUser) -> dict:
    user = {"_id": uuid.uuid4().hex, "email": body.email, "password_hash": hash_password(body.password),
            "role": body.role, "created_at": events.now()}
    try:
        db.users().insert_one(user)
    except DuplicateKeyError:
        raise HTTPException(409, f"{body.email} already has an account.")
    return user_row(user)


@router.delete("/users/{user_id}", status_code=204)
def remove_user(user_id: str, admin: dict = Depends(admin_only)) -> None:
    if user_id == admin["_id"]:
        raise HTTPException(400, "You cannot remove your own account.")
    if db.users().delete_one({"_id": user_id}).deleted_count == 0:
        raise HTTPException(404, "No such user.")
    db.sessions().delete_many({"user_id": user_id})
