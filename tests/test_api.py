import json
import re
import sys
import time
from contextlib import nullcontext

import httpx
import pytest
from fastapi.testclient import TestClient

from groundhog import config, db, events, setup_checks
from groundhog.agent import suggester
from groundhog.api import auth, jobs, runs, suggestions
from groundhog.api.app import app
from groundhog.api.passwords import hash_password, verify_password
from groundhog.cases import store
from groundhog.cases.schema import Case, Expect, Flow, Step

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


def test_health_is_public_and_says_only_mongo_and_version():
    body = TestClient(app).get("/api/health").json()
    assert set(body) == {"mongo", "version"}


def test_settings_health_says_how_many_runs_go_at_once(monkeypatch):
    monkeypatch.setattr(config, "MAX_WORKERS", 3)
    monkeypatch.setattr(setup_checks, "all_checks", lambda: [])
    assert signed_in().get("/api/settings/health").json()["workers"] == 3


def test_settings_health_never_returns_an_env_value(monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "https://app.example.com")
    monkeypatch.setattr(config, "LOGIN_PASS", "hunter2-secret")
    monkeypatch.setattr(config, "TYPESAFE_API_KEY", "tk-secret-value")
    monkeypatch.setattr(setup_checks, "check_chromium", lambda: (True, "Chromium launches"))
    monkeypatch.setattr(setup_checks, "check_app", lambda: (False, f"app unreachable ({config.BASE_URL})"))
    monkeypatch.setattr(setup_checks, "check_jev", lambda: (False, f"Jev — bad key {config.TYPESAFE_API_KEY}"))
    monkeypatch.setattr(setup_checks, "check_login", lambda: (False, f"login — {config.LOGIN_PASS} rejected"))
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
    ("/api/cases/demo/run", {"retries": 3}),
    ("/api/flows/demo/run", {"retries": 1}),
])
def test_bad_names_and_vars_are_422_and_never_spawn_a_worker(monkeypatch, url, body):
    store.save_flow(Flow(name="demo", chain=["demo"]))
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


def test_case_and_flow_with_one_name_show_only_their_own_runs():
    store.save_flow(Flow(name="demo", chain=["demo"]))
    db.runs().insert_many([{"_id": "case-run", "kind": "run", "target": "demo", "created_at": "1", "events": []},
                           {"_id": "flow-run", "kind": "flow", "target": "demo", "created_at": "2", "events": []}])
    client = signed_in()
    assert [r["id"] for r in client.get("/api/cases/demo").json()["runs"]] == ["case-run"]
    assert [r["id"] for r in client.get("/api/flows/demo").json()["runs"]] == ["flow-run"]


def test_server_start_closes_runs_a_previous_server_spawned():
    db.runs().insert_many([{"_id": "spawned", "status": "running", "pid": 1, "events": []},
                           {"_id": "terminal", "status": "running", "events": []},
                           {"_id": "queued", "status": "queued", "pid": None, "events": []}])
    with TestClient(app):
        pass
    assert db.runs().find_one({"_id": "spawned"})["status"] == "error"
    assert db.runs().find_one({"_id": "queued"})["status"] == "error"
    assert db.runs().find_one({"_id": "terminal"})["status"] == "running"


def test_queue_starts_at_most_max_workers_and_the_next_when_one_exits(monkeypatch):
    monkeypatch.setattr(config, "MAX_WORKERS", 1)
    use_worker(monkeypatch, EXIT_SOON)
    client = signed_in()
    first, second = (client.post("/api/cases/demo/run", json={}).json()["run_id"] for _ in range(2))

    assert db.runs().find_one({"_id": first})["pid"]
    assert db.runs().find_one({"_id": second})["pid"] is None
    assert wait_until_closed(second)["pid"]


def test_cancelling_a_queued_run_closes_it_without_starting_it(monkeypatch):
    monkeypatch.setattr(config, "MAX_WORKERS", 1)
    use_worker(monkeypatch, SLEEP)
    client = signed_in()
    running, queued = (client.post("/api/cases/demo/run", json={}).json()["run_id"] for _ in range(2))

    assert client.post(f"/api/runs/{queued}/cancel").status_code == 204
    run = db.runs().find_one({"_id": queued})
    assert (run["status"], run["error"], run["pid"]) == ("error", "cancelled", None)
    assert client.post(f"/api/runs/{running}/cancel").status_code == 204
    wait_until_closed(running)


def test_batch_queues_one_run_per_name_and_404s_an_unknown_one(monkeypatch):
    use_worker(monkeypatch, EXIT_WITH_ARGV)
    store.save_flow(Flow(name="lifecycle", chain=["demo"]))
    client = signed_in()
    assert client.post("/api/runs/batch", json={"cases": ["demo", "nope"]}).status_code == 404
    assert db.runs().count_documents({}) == 0

    ids = client.post("/api/runs/batch", json={"cases": ["demo"], "flows": ["lifecycle"]}).json()["run_ids"]
    assert [wait_until_closed(i)["error"] for i in ids] == [f"run demo --retries 1 --run-id {ids[0]}",
                                                            f"flow run lifecycle --run-id {ids[1]}"]


def test_cases_carry_health_over_finished_replays_oldest_first():
    db.runs().insert_many([
        {"_id": "r1", "kind": "run", "target": "demo", "status": "failed", "total_ms": 100, "created_at": "1"},
        {"_id": "r2", "kind": "run", "target": "demo", "status": "passed", "flaky": True, "total_ms": 300,
         "created_at": "2"},
        {"_id": "r3", "kind": "run", "target": "demo", "status": "running", "created_at": "3"},
        {"_id": "a1", "kind": "author", "target": "demo", "status": "passed", "created_at": "4"}])
    client = signed_in()
    health = client.get("/api/cases").json()[0]["health"]
    assert health == {"runs": 2, "passed": 1, "flaky": 1, "avg_ms": 200, "heals": 0,
                      "history": [{"id": "r1", "status": "failed", "flaky": False},
                                  {"id": "r2", "status": "passed", "flaky": True}]}
    assert client.get("/api/cases/demo").json()["health"] == health


def test_map_groups_by_section_covers_from_runs_or_steps_and_lists_gaps():
    store.save(Case(name="create-template", intent="create", start_path="/:ws/templates",
                    steps=[Step(action="click", description="click Create template",
                                expects=Expect(kind="url_contains", value="/templates/new"))]))
    store.save(Case(name="events", intent="events", start_path="/:ws/home", steps=[]))
    db.runs().insert_one({"_id": "r1", "kind": "run", "target": "events", "status": "passed",
                          "paths": ["/:ws/events"], "created_at": "1"})
    db.pages().insert_many([
        {"_id": "/:ws/templates", "title": "Templates", "section": "templates", "links": [], "last_seen": "2",
         "controls": [{"role": "button", "label": "Create template", "kind": "mutation"},
                      {"role": "button", "label": "Delete", "kind": "destructive"}]},
        {"_id": "/:ws/templates/new", "title": "New", "section": "templates", "links": [], "last_seen": "1",
         "controls": []},
        {"_id": "/:ws/events", "title": "Events", "section": "events", "links": [], "last_seen": "1",
         "controls": [{"role": "button", "label": "Add event", "kind": "mutation"}]}])

    body = signed_in().get("/api/map").json()
    assert body["crawled_at"] == "2"
    assert [(s["name"], s["covered"], s["total"]) for s in body["sections"]] == [("events", 1, 1), ("templates", 2, 2)]
    assert [p["cases"] for p in body["sections"][1]["pages"]] == [["create-template"], ["create-template"]]
    assert [(g["path"], g["control"]["label"]) for g in body["gaps"]] == [("/:ws/events", "Add event"),
                                                                         ("/:ws/templates", "Delete")]


def test_crawl_starts_a_crawl_run_and_refuses_a_bad_scope(monkeypatch):
    use_worker(monkeypatch, EXIT_WITH_ARGV)
    client = signed_in()
    assert client.post("/api/map/crawl", json={"scope": "templates"}).status_code == 422

    run_id = client.post("/api/map/crawl", json={"scope": "/templates", "max_pages": 5}).json()["run_id"]
    run = wait_until_closed(run_id)
    assert (run["kind"], run["target"]) == ("crawl", "/templates")
    assert run["error"] == f"crawl --scope /templates --max-pages 5 --run-id {run_id}"


def resolve_to(monkeypatch, address):
    monkeypatch.setattr(suggestions.socket, "getaddrinfo", lambda host, port: [(2, 1, 6, "", (address, 0))])


def test_suggest_refuses_docs_on_an_internal_address(monkeypatch):
    resolve_to(monkeypatch, "127.0.0.1")
    monkeypatch.setattr(suggestions.httpx, "stream", lambda *a, **kw: pytest.fail("fetched an internal address"))
    response = signed_in().post("/api/suggestions", json={"docs_urls": ["http://internal.example.com/admin"]})
    assert (response.status_code, response.json()["detail"]) == (400, "Only public docs sites can be read.")


def test_page_text_reads_docs_on_a_public_address(monkeypatch):
    resolve_to(monkeypatch, "93.184.215.14")
    monkeypatch.setattr(suggestions.httpx, "stream", lambda method, url, **kw: nullcontext(
        httpx.Response(200, text="<p>public docs</p>", request=httpx.Request(method, url))))
    assert suggestions.page_text("https://docs.example.com/templates") == "public docs"


def test_suggest_reads_the_docs_and_saves_open_suggestions(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "sk-test")
    resolve_to(monkeypatch, "93.184.215.14")
    html = "<html><script>track()</script><p>Templates   hold\n copy</p></html>"
    monkeypatch.setattr(suggestions.httpx, "stream", lambda method, url, **kw: nullcontext(
        httpx.Response(200, text=html, request=httpx.Request(method, url))))
    asked = {}

    def parse(**kw):
        asked.update(kw)
        return suggester.Suggestions(suggestions=[suggester.Suggestion(
            name="Delete Template", intent="delete template {{name}} and verify it is gone", why="gap",
            vars=[suggester.Pair(var="name", value="gh-suggested")])])
    monkeypatch.setattr(suggester.client, "parse", parse)

    client = signed_in()
    rows = client.post("/api/suggestions", json={"docs_urls": ["https://docs.example.com/templates"]}).json()
    assert "Templates hold copy" in asked["user"] and "track()" not in asked["user"]
    assert [(r["name"], r["vars"], r["source"], r["status"]) for r in rows] == [
        ("delete-template-name-and-verify", {"name": "gh-suggested"}, "docs", "open")]
    assert client.get("/api/suggestions").json() == rows


def test_suggest_without_the_anthropic_key_is_409(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "")
    monkeypatch.setattr(suggester.client, "_client", None)
    response = signed_in().post("/api/suggestions", json={"text": "templates hold copy"})
    assert response.status_code == 409 and "ANTHROPIC_API_KEY is not set" in response.json()["detail"]


def test_authoring_a_suggestion_marks_it_and_dismiss_toggles(monkeypatch):
    use_worker(monkeypatch, EXIT_WITH_ARGV)
    db.suggestions().insert_one({"_id": "abcdef012345", "name": "delete-template", "intent": "delete {{name}}",
                                 "why": "gap", "vars": {"name": "gh-suggested"}, "source": "map", "status": "open",
                                 "created_at": "1", "created_by": "admin@example.com"})
    client = signed_in()
    run_id = client.post("/api/suggestions/abcdef012345/author").json()["run_id"]
    assert wait_until_closed(run_id)["error"] == (f"new delete {{{{name}}}} --var name=gh-suggested --start /:ws/home "
                                                  f"--name delete-template --run-id {run_id}")
    row = client.get("/api/suggestions").json()[0]
    assert (row["status"], row["case"], row["run_id"], row["run_status"]) == ("authored", "delete-template",
                                                                              run_id, "error")

    for status in ("dismissed", "open"):
        assert client.post("/api/suggestions/abcdef012345/dismiss").status_code == 204
        assert db.suggestions().find_one()["status"] == status
