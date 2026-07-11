from groundhog.browser.snapshot import fingerprint, format_canvas, format_frames, prune_tree


def _tree(n):
    return "\n".join(f'- listitem:\n  - link "row {i}"' for i in range(n))


def test_prune_collapses_repeated_siblings():
    pruned = prune_tree(_tree(20), max_repeat=6)
    assert "(14 more listitem)" in pruned
    assert pruned.count("listitem") == 6 + 1  # kept blocks + the marker


def test_prune_keeps_small_lists():
    assert prune_tree(_tree(3)) == _tree(3)


def test_prune_caps_total_lines():
    # alternate roles so no sibling run is long enough to collapse
    text = "\n".join(f'- {"alpha" if i % 2 else "beta"} "x{i}"' for i in range(300))
    pruned = prune_tree(text, max_lines=250)
    assert len(pruned.split("\n")) == 251
    assert "more lines truncated" in pruned


def test_format_canvas_renders_nodes_handles_edges():
    data = {"nodes": [{"id": "n1", "label": "SMS", "handles": ["source", "target"]},
                      {"id": "n2", "label": "Trigger", "handles": []}],
            "edges": ["Edge from n1 to n2"]}
    block = format_canvas(data)
    assert block.startswith("Canvas (ReactFlow):")
    assert '- node data-id="n1" "SMS" handles: source, target' in block
    assert '- node data-id="n2" "Trigger"' in block
    assert '- edge "Edge from n1 to n2"' in block


def test_format_canvas_empty_or_malformed_renders_nothing():
    assert format_canvas({"nodes": [], "edges": []}) == ""
    assert format_canvas(None) == ""
    assert format_canvas({"nodes": "garbage"}) == ""


def test_format_frames_renders_labeled_blocks_and_survives_bad_input():
    frames = [
        {"selector": 'iframe[title="Editor"]', "tree": '- button "Save"\n- textbox "Body"'},
        {"selector": "iframe >> nth=1", "tree": "   "},  # blank frame dropped
    ]
    block = format_frames(frames)
    assert 'Frame iframe[title="Editor"]:\n- button "Save"' in block
    assert "iframe >> nth=1" not in block
    assert format_frames([]) == "" and format_frames(None) == ""  # never throws


def test_fingerprint_ignores_live_numbers():
    a = '- text "Notifications Sent: 1,234"\n- text "Last 7 Days"'
    b = '- text "Notifications Sent: 9,876"\n- text "Last 7 Days"'
    c = '- text "Notifications Sent: 9,876"\n- text "Last Week"'
    assert fingerprint(a) == fingerprint(b)  # counts pruned out
    assert fingerprint(b) != fingerprint(c)  # structural text change is drift
