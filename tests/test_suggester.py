from groundhog.agent import suggester


def test_suggest_sends_count_catalog_and_gaps_and_keeps_at_most_count(monkeypatch):
    asked = {}
    many = [suggester.Suggestion(name=f"s{i}", intent="open home and verify it loads", why="docs") for i in range(4)]

    def parse(**kw):
        asked.update(kw)
        return suggester.Suggestions(suggestions=many)
    monkeypatch.setattr(suggester.client, "parse", parse)

    out = suggester.suggest("Templates hold copy.", ["demo: open {{page}}"], ["/:ws/templates: Delete"], 2)
    assert [s.name for s in out] == ["s0", "s1"]
    assert "Suggest 2 tests" in asked["user"]
    assert "- demo: open {{page}}" in asked["user"] and "- /:ws/templates: Delete" in asked["user"]
    assert asked["output_model"] is suggester.Suggestions


def test_suggest_says_none_for_an_empty_catalog_and_no_gaps(monkeypatch):
    asked = {}
    monkeypatch.setattr(suggester.client, "parse",
                        lambda **kw: asked.update(kw) or suggester.Suggestions(suggestions=[]))
    assert suggester.suggest("", [], [], 3) == []
    assert asked["user"].count("(none)") == 3
