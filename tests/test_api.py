import json
import re
import sys
import time

import pytest
from fastapi.testclient import TestClient

from groundhog import checks, config, db, events
from groundhog.api import auth, jobs, runs
from groundhog.api.app import app
from groundhog.cases import store
from groundhog.cases.schema import Case, Step
from groundhog.passwords import hash_password, verify_password

PASSWORD = "correct-horse"
EXIT_SOON = "import time; time.sleep(0.5)"
EXIT_WITH_ARGV = "import sys; sys.stderr.write(' '.join(sys.argv[1:])); sys.exit(1)"
SLEEP = "import time; time.sleep(30)"


@pytest.fixture(autouse=True)
def fresh_state():
    auth._failures.clear()
    db.ensure_indexes()
    store.save(Case(name="demo", intent="open {{page}}", steps=[Step(action="goto", value="/")]))


def add_user(email: str, role: str) -> None:
    db.users().insert_one({"_id": email, "email": email, "password_hash": hash_password(PASSWORD), "role": role,
                           "created_at": events.now()})


def signed_in(role: str = "admin") -> TestClient:
    email = f"{role}@example.com"
    add_user(email, role)
    client = TestClient(app)
    assert client.post("/api/auth/login", json={"email": email, "password": PASSWORD}).status_code == 204
    return client


def use_worker(monkeypatch, script: str) -> None:
    monkeypatch.setattr(jobs, "WORKER", [sys.executable, "-c", script])


def wait_until_closed(run_id: str) -> dict:
    deadline = time.monotonic() + 10
    while (run := db.runs().find_one({"_id": run_id}))["status"] in jobs.ACTIVE and time.monotonic() < deadline:
        time.sleep(0.05)
    return run


def test_every_api_route_except_login_and_health_needs_a_session():
    client = TestClient(app)
    public = {"/api/auth/login", "/api/health"}
    for path, methods in app.openapi()["paths"].items():
        if path in public:
            continue
        url = re.sub(r"\{[^}]+\}", "1", path)
        for method in methods:
            assert client.request(method.upper(), url).status_code == 401, f"{method} {path}"


def test_session_cookie_is_httponly_lax_and_logout_ends_it_server_side():
    client = signed_in()
    cookie = next(h for h in client.cookies.jar if h.name == auth.COOKIE)
    assert cookie.has_nonstandard_attr("HttpOnly")
    stolen = cookie.value

    assert client.post("/api/auth/logout").status_code == 204
    assert TestClient(app, cookies={auth.COOKIE: stolen}).get("/api/auth/me").status_code == 401


def test_login_sets_samesite_lax_and_me_returns_the_user():
    add_user("a@example.com", "admin")
    client = TestClient(app)
    response = client.post("/api/auth/login", json={"email": "a@example.com", "password": PASSWORD})
    assert "samesite=lax" in response.headers["set-cookie"].lower()
    assert client.get("/api/auth/me").json() == {"email": "a@example.com", "role": "admin"}


def test_wrong_password_and_unknown_email_get_the_same_answer():
    add_user("a@example.com", "admin")
    client = TestClient(app)
    wrong = client.post("/api/auth/login", json={"email": "a@example.com", "password": "nope"})
    unknown = client.post("/api/auth/login", json={"email": "b@example.com", "password": "nope"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_sixth_attempt_after_five_failures_is_refused():
    add_user("a@example.com", "admin")
    client = TestClient(app)
    for _ in range(5):
        assert client.post("/api/auth/login", json={"email": "a@example.com", "password": "x"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "a@example.com", "password": PASSWORD}).status_code == 429


def test_mutating_request_from_a_foreign_origin_is_refused():
    client = signed_in()
    foreign = client.put("/api/cases/demo", json=store.load("demo").model_dump(),
                         headers={"Origin": "https://evil.example.com"})
    own = client.put("/api/cases/demo", json=store.load("demo").model_dump(), headers={"Origin": "http://testserver"})
    assert foreign.status_code == 403
    assert own.status_code == 200


def test_health_is_public_and_says_only_booleans_and_version():
    body = TestClient(app).get("/api/health").json()
    assert set(body) == {"ok", "mongo", "version"}


def test_settings_health_never_returns_an_env_value(monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "https://app.example.com")
    monkeypatch.setattr(config, "LOGIN_PASS", "hunter2-secret")
    monkeypatch.setattr(config, "TYPESAFE_API_KEY", "tk-secret-value")
    monkeypatch.setattr(checks, "check_chromium", lambda: (True, "Chromium launches"))
    monkeypatch.setattr(checks, "check_app", lambda: (False, f"app unreachable ({config.BASE_URL})"))
    monkeypatch.setattr(checks, "check_jev", lambda: (False, f"Jev — bad key {config.TYPESAFE_API_KEY}"))
    monkeypatch.setattr(checks, "check_login", lambda: (False, f"login — {config.LOGIN_PASS} rejected"))
    client = signed_in()

    text = client.get("/api/settings/health").text + client.post("/api/settings/check-login").text
    for value in ("https://app.example.com", "hunter2-secret", "tk-secret-value"):
        assert value not in text
    assert "TYPESAFE_API_KEY" in text


def test_admin_only_routes_refuse_a_member():
    client = signed_in("member")
    db.runs().insert_one({"_id": "r1", "status": "passed", "events": []})
    assert client.delete("/api/cases/demo").status_code == 403
    assert client.delete("/api/flows/demo").status_code == 403
    assert client.delete("/api/runs/r1").status_code == 403
    assert client.get("/api/users").status_code == 403
    assert client.post("/api/users", json={"email": "c@example.com", "password": "long-enough"}).status_code == 403
    assert client.delete("/api/users/admin@example.com").status_code == 403


@pytest.mark.parametrize("url, body", [
    ("/api/cases/Bad_Name/run", {}),
    ("/api/cases/demo/run", {"vars": {"bad key": "x"}}),
    ("/api/cases/demo/run", {"vars": {"page": "x" * 501}}),
    ("/api/cases/author", {"intent": "--verify everything"}),
    ("/api/cases/author", {"intent": "open home", "name": "../etc"}),
    ("/api/flows/compose", {"intent": "chain things", "name": "UPPER"}),
])
def test_bad_names_and_vars_are_422_and_never_spawn_a_worker(monkeypatch, url, body):
    monkeypatch.setattr(jobs.subprocess, "Popen", lambda *a, **k: pytest.fail("worker spawned"))
    assert signed_in().post(url, json=body).status_code == 422


def test_passwords_are_salted_scrypt():
    stored = hash_password("pw")
    assert re.fullmatch(r"scrypt\$[0-9a-f]{32}\$[0-9a-f]{128}", stored)
    assert stored != hash_password("pw")
    assert verify_password("pw", stored) and not verify_password("other", stored)


def test_case_detail_has_its_saved_time_and_runs():
    detail = signed_in().get("/api/cases/demo").json()
    assert detail["name"] == "demo" and detail["updated_at"] and detail["runs"] == []
    assert "_id" not in detail


def test_case_save_rejects_a_body_named_differently():
    body = {**store.load("demo").model_dump(), "name": "other"}
    assert signed_in().put("/api/cases/demo", json=body).status_code == 422


def test_admin_adds_a_user_but_cannot_remove_themselves():
    client = signed_in()
    added = client.post("/api/users", json={"email": "m@example.com", "password": "long-enough", "role": "member"})
    assert added.status_code == 201
    assert client.post("/api/users", json={"email": "m@example.com", "password": "long-enough"}).status_code == 409
    assert client.delete("/api/users/admin@example.com").status_code == 400
    assert client.delete(f"/api/users/{added.json()['id']}").status_code == 204


def test_worker_gets_the_run_arguments_and_a_crash_keeps_its_stderr(monkeypatch):
    use_worker(monkeypatch, EXIT_WITH_ARGV)
    run_id = signed_in().post("/api/cases/demo/run", json={"vars": {"page": "home"}, "heal": False}).json()["run_id"]

    run = wait_until_closed(run_id)
    assert run["status"] == "error"
    assert run["error"] == f"run demo --var page=home --no-heal --run-id {run_id}"


def test_a_run_the_worker_closed_is_left_alone(monkeypatch):
    use_worker(monkeypatch, EXIT_SOON)  # outlives the status write below
    client = signed_in()
    run_id = client.post("/api/cases/demo/run", json={}).json()["run_id"]
    db.runs().update_one({"_id": run_id}, {"$set": {"status": "passed"}})

    jobs_done = time.monotonic() + 10
    while run_id in jobs._workers and time.monotonic() < jobs_done:
        time.sleep(0.05)
    assert db.runs().find_one({"_id": run_id})["status"] == "passed"


def test_events_stream_ends_with_done_once_the_run_closes():
    client = signed_in()
    events.start("r2", "run", "demo")
    events.emit("note", level="info", text="one")
    events.emit("note", level="info", text="two")
    events.finish("passed", total_ms=10)

    with client.stream("GET", "/api/runs/r2/events?after=1") as response:
        lines = [line for line in response.iter_lines() if line]
    assert json.loads(lines[0].removeprefix("data: "))["text"] == "two"
    assert lines[1] == "event: done"
    assert json.loads(lines[2].removeprefix("data: "))["status"] == "passed"


def test_events_stream_sends_the_status_when_it_changes(monkeypatch):
    monkeypatch.setattr(runs, "POLL_SECONDS", 0.05)
    client = signed_in()
    db.runs().insert_one({"_id": "r3", "kind": "run", "target": "demo", "status": "queued", "events": []})

    statuses = []
    with client.stream("GET", "/api/runs/r3/events") as response:
        for line in response.iter_lines():
            if line.startswith("data: ") and len(statuses) < 2:
                statuses.append(json.loads(line.removeprefix("data: "))["status"])
                db.runs().update_one({"_id": "r3"}, {"$set": {"status": ["running", "passed"][len(statuses) - 1]}})
    assert statuses == ["queued", "running"]


def test_round_trip_login_list_run_watch_cancel(monkeypatch):
    use_worker(monkeypatch, SLEEP)
    monkeypatch.setattr(runs, "KEEP_ALIVE_SECONDS", 0.5)  # a closed stream is noticed on its next write
    client = signed_in()
    assert [c["name"] for c in client.get("/api/cases").json()] == ["demo"]

    run_id = client.post("/api/cases/demo/run", json={"vars": {"page": "home"}}).json()["run_id"]
    events.start(run_id, "run", "demo", {"page": "home"})
    events.emit("step", i=1, id="s1", description="open home", mode="static", selector=None, ms=5, drift=False,
                error=None)
    events.emit("note", level="info", text="still going")

    with client.stream("GET", f"/api/runs/{run_id}/events") as response:
        data = []
        for line in response.iter_lines():
            if line.startswith("data: "):
                data.append(json.loads(line.removeprefix("data: ")))
            if len(data) == 2:
                break
    assert [e["kind"] for e in data] == ["step", "note"]

    assert client.post(f"/api/runs/{run_id}/cancel").status_code == 204
    run = wait_until_closed(run_id)
    assert (run["status"], run["error"]) == ("error", "cancelled")
    assert client.get("/api/runs").json()[0]["id"] == run_id
    assert "events" not in client.get("/api/runs").json()[0]
