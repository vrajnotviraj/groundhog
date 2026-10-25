from types import SimpleNamespace

import pytest

from groundhog import config, crawl, db, events
from groundhog.browser.snapshot import Element, Snapshot


def element(role: str, label: str, href: str = "") -> Element:
    return Element(id="e1", role=role, label=label, value="", kind="click", attrs={"href": href} if href else {},
                   state={}, scope=None, frame=None, node=1)


SITE = {
    "/:ws/templates": [element("link", "Edit", "/FYTEST0001/templates/a"), element("button", "Create template"),
                       element("link", "Events", "/FYTEST0001/events"),
                       element("link", "Log out", "/FYTEST0001/templates/logout"),
                       element("link", "Elsewhere", "https://other.example.com/FYTEST0001/templates/x"),
                       element("link", "Other", "/FYTEST0001/templates/z")],
    "/:ws/templates/a": [element("link", "Deeper", "a/b"), element("button", "Delete"),
                         element("button", "Delete"), element("link", "Back", "/FYTEST0001/templates")],
    "/:ws/templates/z": [],
    "/:ws/templates/a/b": [element("link", "Deepest", "/FYTEST0001/templates/a/b/c")],
    "/:ws/templates/a/b/c": [],
}


@pytest.fixture
def site(monkeypatch):
    """A fake browser over SITE; returns the session and the page keys it opened, in order."""
    opened = []

    def goto(page, url):
        page.url = url
        opened.append(config.ws_path(url))

    def observe(page):
        key = config.ws_path(page.url)
        return Snapshot(url=page.url, title=key, text="", elements=SITE[key], omitted=0, fingerprint="")

    monkeypatch.setattr(crawl, "goto_app", goto)
    monkeypatch.setattr(crawl, "observe", observe)
    monkeypatch.setattr(config, "CRAWL_MAX_DEPTH", 2)
    return SimpleNamespace(page=SimpleNamespace(url=""), ws="FYTEST0001"), opened


def test_walk_stays_in_scope_and_depth_breadth_first(site):
    session, opened = site
    events.start("r1", "crawl", "/templates")

    counts = crawl.walk(session, "/:ws/templates", "/:ws/templates", 40, "r1")
    assert opened == ["/:ws/templates", "/:ws/templates/a", "/:ws/templates/z", "/:ws/templates/a/b"]
    assert counts == {"pages": 4, "controls": 10}
    page = db.pages().find_one({"_id": "/:ws/templates"})
    assert (page["section"], page["run_id"]) == ("templates", "r1")
    assert page["links"] == ["/:ws/templates/a", "/:ws/templates/z"]
    stored = [e["path"] for e in db.runs().find_one({"_id": "r1"})["events"] if e["kind"] == "page"]
    assert stored == opened


def test_walk_skips_a_page_that_does_not_load(site, monkeypatch):
    session, opened = site
    events.start("r2", "crawl", "/templates")
    working = crawl.goto_app

    def goto(page, url):
        if url.endswith("/templates/a"):
            raise RuntimeError("the app did not load within 45s")
        working(page, url)

    monkeypatch.setattr(crawl, "goto_app", goto)
    counts = crawl.walk(session, "/:ws/templates", "/:ws/templates", 40, "r2")
    assert counts["pages"] == 2 and "/:ws/templates/a" not in [e["path"] for e in _events("r2", "page")]
    assert [e["text"] for e in _events("r2", "note")] == ["skipped /:ws/templates/a: the app did not load within 45s"]


def _events(run_id: str, kind: str) -> list[dict]:
    return [e for e in db.runs().find_one({"_id": run_id})["events"] if e["kind"] == kind]


def test_walk_stops_at_max_pages(site):
    session, opened = site
    assert crawl.walk(session, "/:ws/templates", "/:ws/templates", 2, None)["pages"] == 2
    assert len(opened) == 2


@pytest.mark.parametrize("role, label, kind", [
    ("link", "Delete", "nav"), ("button", "Delete template", "destructive"), ("menuitem", "Remove", "destructive"),
    ("button", "Create new", "mutation"), ("tab", "Save", "mutation"), ("button", "Address book", "other"),
])
def test_control_kind_comes_from_the_label(role, label, kind):
    assert crawl.control_kind(role, label) == kind


@pytest.mark.parametrize("key, section", [
    ("/:ws/templates/x/edit", "templates"), ("/:ws", "home"), ("/:ws/home", "home"),
])
def test_section_is_the_first_segment_after_the_workspace(key, section):
    assert crawl.section(key) == section


def test_page_key_drops_the_workspace_and_the_query():
    assert crawl.links([element("link", "x", "/FYTEST0001/templates?tab=2")], "/:ws/", "") == ["/:ws/templates"]
