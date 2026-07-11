from groundhog.browser.selectors import dedupe_ranked, embeds_value, is_weak, rank


def test_weak_selectors_rejected():
    assert is_weak("div")
    assert is_weak("button")
    assert is_weak("")
    assert is_weak(None)
    assert not is_weak('role=button[name="Create"]')
    assert not is_weak("#save")
    # Structural CSS with no anchor, and aria-role names used as CSS tags.
    assert is_weak("dialog combobox:first-of-type")
    assert is_weak('combobox[name*="Template"]')
    assert is_weak('textbox[placeholder="Enter Name"]')
    assert not is_weak('role=combobox[name="Type"]')
    assert not is_weak('input[type="checkbox"]')


def test_snapshot_syntax_leak_rejected():
    # aria-snapshot shape (bare tag + quoted string) is invalid CSS, not a
    # selector — Playwright throws a parse error, so the weak gate must catch it.
    assert is_weak('button "Start"')
    assert is_weak('link "Home"')
    assert is_weak("option 'SMS'")
    # real selectors that legitimately contain quotes still pass
    assert not is_weak('role=button[name="Start"]')
    assert not is_weak('button:has-text("Start")')
    assert not is_weak('text="Start"')


def test_reactflow_selectors_pass_existing_gate():
    # Anchored ReactFlow shapes are durable; bare canvas classes are not.
    assert not is_weak('.react-flow__node:has-text("SMS")')
    assert not is_weak('.react-flow__node[data-id="n1"] .react-flow__handle.source')
    assert is_weak(".react-flow__handle")
    assert is_weak(".react-flow__node")


def test_rank_prefers_durable_shapes():
    ordered = ['[data-testid="x"]', "#save", '[aria-label="Close"]',
               'role=button[name="Save"]', '[placeholder="Name"]', 'text="Save"']
    assert [rank(s) for s in ordered] == sorted(rank(s) for s in ordered)
    assert rank('button:has-text("Save")') == 6  # unranked shapes sort last


def test_embeds_value_guards_overfitting():
    assert embeds_value('text="gh-test"', "gh-test")
    assert not embeds_value('role=button[name="Save"]', "gh-test")
    assert not embeds_value('text="ab"', "ab")  # too short to be meaningful
    # {{var}} placeholders render per run — not overfitting.
    assert not embeds_value('text="{{name}}"', "{{name}}")


def test_dedupe_ranked_orders_and_filters():
    out = dedupe_ranked(['text="Save"', "div", '[data-testid="save"]', 'text="Save"'])
    assert out == ['[data-testid="save"]', 'text="Save"']
