"""Snapshot tests: headless Chromium against tests/fixture.html."""

from pathlib import Path

import pytest

from groundhog.browser.snapshot import SAME_NODE, observe, selectors_for

FIXTURE = (Path(__file__).parent / "fixture.html").as_uri()


@pytest.fixture(scope="module")
def browser():
    try:
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        b = pw.chromium.launch()
    except Exception as e:  # no browser binary, no display, no playwright
        pytest.skip(f"chromium unavailable: {e}")
    yield b
    b.close()
    pw.stop()


@pytest.fixture(scope="module")
def page(browser):
    p = browser.new_page()
    p.goto(FIXTURE)
    yield p
    p.close()


@pytest.fixture
def fresh(browser):
    p = browser.new_page()
    yield p
    p.close()


@pytest.fixture(scope="module")
def snap(page):
    return observe(page)


def by_label(snap, label):
    return [e for e in snap.elements if e.label == label]


def one(snap, label):
    hits = by_label(snap, label)
    assert len(hits) == 1, f"{label}: {[(e.role, e.label) for e in snap.elements]}"
    return hits[0]


def resolves(page, el, sel):
    root = page.frame_locator(el.frame) if el.frame else page
    loc = root.locator(sel)
    return loc.count() == 1 and loc.first.evaluate(SAME_NODE, el.node)


def test_password_and_consent_excluded(snap):
    assert not [e for e in snap.elements if e.attrs.get("type") == "password"]
    assert not [e for e in snap.elements if e.attrs.get("id") == "pw"]
    assert not by_label(snap, "Accept All")
    assert "your-password" not in snap.text


def test_hidden_checkbox_surfaces_as_its_label(page, snap):
    sms = one(snap, "SMS")
    assert (sms.role, sms.kind, sms.attrs["tag"]) == ("checkbox", "click", "label")
    assert sms.state["checked"] == "true"
    assert selectors_for(page, sms) == ['label:has(:text-is("SMS"))']


def test_sms_and_sms_fallback_are_different_nodes(page, snap):
    sms, fallback = one(snap, "SMS"), one(snap, "SMS Fallback")
    assert sms.node != fallback.node
    assert fallback.state["checked"] == "false"
    for el in (sms, fallback):
        assert resolves(page, el, selectors_for(page, el)[0])


def test_iframe_button_is_addressable_through_its_frame(page, snap):
    el = one(snap, "Inside Frame")
    assert el.frame == 'iframe[name="editor"]'
    assert el.id.startswith("f1e")
    sel = selectors_for(page, el)[0]
    assert page.frame_locator(el.frame).locator(sel).count() == 1


def test_testid_wins(page, snap):
    assert selectors_for(page, one(snap, "Create Template"))[0] == '[data-testid="create-tpl"]'


def test_stable_id_then_placeholder(page, snap):
    sels = selectors_for(page, one(snap, "Enter Name"))
    assert sels[0] == "#tpl-name"
    assert '[placeholder="Enter Name"]' in sels


def test_link_href_drops_the_workspace_segment(page, snap):
    card = next(e for e in snap.elements if e.role == "link" and e.label.startswith("gh-1"))
    sels = selectors_for(page, card)
    assert 'a[href*="/templates/gh-1/v1"]' in sels
    assert not [s for s in sels if "FYABCDEF" in s]


def test_hint_becomes_a_name_substring_selector(page, snap):
    card = next(e for e in snap.elements if e.role == "link" and e.label.startswith("gh-1"))
    assert selectors_for(page, card, hints=["gh-1"])[0] == 'role=link[name*="gh-1"]'


def test_scoped_selector_for_a_duplicated_delete(page, snap):
    inside = next(e for e in snap.elements if e.label == "Delete" and e.scope)
    assert inside.scope == {"kind": "dialog"}
    assert selectors_for(page, inside)[0] == 'role=dialog >> role=button[name="Delete"]'


def test_more_button_scoped_by_its_card(page, snap):
    more = [e for e in snap.elements if e.label == "more"]
    assert len(more) == 2
    sel = selectors_for(page, more[0])[0]
    assert sel == 'a[href*="/templates/gh-1/v1"] >> [aria-label="more"]'
    assert resolves(page, more[0], sel)


def test_nth_from_dom_order_as_last_resort(page, snap):
    dups = by_label(snap, "Dup")
    assert len(dups) == 2
    assert selectors_for(page, dups[0]) == ['role=button[name="Dup"] >> nth=0']
    assert selectors_for(page, dups[1]) == ['role=button[name="Dup"] >> nth=1']


def test_every_returned_selector_resolves_to_the_same_node(page, snap):
    for el in snap.elements:
        sels = selectors_for(page, el, hints=["gh-1"])
        assert sels, el
        for sel in sels:
            assert resolves(page, el, sel), (el.label, sel)


def test_toast_text_is_excluded(page):
    assert "Toast saved" not in observe(page).text


def test_below_the_fold_is_offered(snap):
    assert "Below the fold paragraph" in snap.text
    assert by_label(snap, "Far Below")


def test_fingerprint_ignores_digits_but_not_structure(fresh):
    fresh.set_content("<button>Item 1</button>")
    a = observe(fresh).fingerprint
    fresh.set_content("<button>Item 27</button>")
    assert observe(fresh).fingerprint == a
    fresh.set_content("<button>Item 1</button><button>Other</button>")
    assert observe(fresh).fingerprint != a


def test_fingerprint_changes_when_a_checkbox_is_checked(fresh):
    fresh.goto(FIXTURE)
    before = observe(fresh).fingerprint
    fresh.locator('label:has(:text-is("SMS"))').click()
    assert observe(fresh).fingerprint != before


def test_element_cap_reports_omitted(fresh):
    fresh.set_content("".join(f"<button>B{i}</button>" for i in range(300)))
    snap = observe(fresh)
    assert len(snap.elements) == 240
    assert snap.omitted == 60


def test_icon_only_button_falls_back_to_a_verified_positional_selector(fresh):
    # Its accessible name is empty, so no role=…[name=…] candidate can ever match;
    # the last resort must still resolve, never a bare unverified base.
    fresh.set_content('<button><svg width="12" height="12"></svg></button>')
    el = observe(fresh).elements[0]
    sels = selectors_for(fresh, el)
    assert sels and all(resolves(fresh, el, s) for s in sels)


def test_fingerprint_changes_when_only_text_changes(fresh):
    fresh.set_content("<button>Save</button><div>draft</div>")
    before = observe(fresh).fingerprint
    fresh.set_content("<button>Save</button><div>Saved</div>")
    assert observe(fresh).fingerprint != before
