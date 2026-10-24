"""Console sign-in: users in Mongo, a session cookie per login, and the guards every route uses.

The cookie holds a random token; Mongo keeps only its sha256, so a database read never yields a
usable session.
"""

import hashlib
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, StringConstraints

from groundhog import db
from groundhog.passwords import hash_password, verify_password

COOKIE = "gh_session"
SESSION_DAYS = 7
MAX_FAILURES = 5
# Checked when the email is unknown, so a wrong email costs as long as a wrong password.
DECOY_HASH = hash_password(secrets.token_hex(8))

_failures: dict[str, list[float]] = {}

router = APIRouter(prefix="/auth")


class Login(BaseModel):
    email: str
    password: Annotated[str, StringConstraints(max_length=200)]


def token_id(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def current_user(request: Request) -> dict:
    """The signed-in user, or 401."""
    token = request.cookies.get(COOKIE)
    now = datetime.now(timezone.utc)
    session = token and db.sessions().find_one({"_id": token_id(token), "expires_at": {"$gt": now}})
    user = session and db.users().find_one({"_id": session["user_id"]})
    if not user:
        raise HTTPException(401, "Sign in first.")
    return user


def admin_only(user: dict = Depends(current_user)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(403, "Only an admin can do that.")
    return user


async def reject_foreign_origin(request: Request, call_next):
    """Refuse a state-changing request sent from another site's page."""
    origin = request.headers.get("origin")
    foreign = origin and urlsplit(origin).netloc != request.headers.get("host")
    if request.method not in ("GET", "HEAD", "OPTIONS") and foreign:
        return JSONResponse({"detail": "Cross-site request refused."}, status_code=403)
    return await call_next(request)


@router.post("/login", status_code=204)
def login(body: Login, request: Request, response: Response) -> None:
    ip = request.client.host if request.client else ""
    recent = [t for t in _failures.get(ip, []) if t > time.monotonic() - 60]
    if len(recent) >= MAX_FAILURES:
        raise HTTPException(429, "Too many failed sign-ins. Wait a minute and try again.")
    user = db.users().find_one({"email": body.email})
    ok = verify_password(body.password, user["password_hash"] if user else DECOY_HASH)
    if not (user and ok):
        _failures[ip] = [*recent, time.monotonic()]
        raise HTTPException(401, "Wrong email or password.")
    _failures.pop(ip, None)
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    db.sessions().insert_one({"_id": token_id(token), "user_id": user["_id"], "created_at": now,
                              "expires_at": now + timedelta(days=SESSION_DAYS)})
    response.set_cookie(COOKIE, token, max_age=SESSION_DAYS * 86400, httponly=True, samesite="lax")


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, user: dict = Depends(current_user)) -> None:
    db.sessions().delete_one({"_id": token_id(request.cookies[COOKIE])})
    response.delete_cookie(COOKIE)


@router.get("/me")
def me(user: dict = Depends(current_user)) -> dict:
    return {"email": user["email"], "role": user["role"]}
