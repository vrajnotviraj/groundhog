from groundhog.graph.store import element_key, page_key, section


def test_page_key_normalizes_workspace_and_noise():
    assert page_key("https://app.example.com/FYAP2A5C3ECACIN/home") == "/:ws/home"
    assert page_key("/FYAP958935141IN/templates?group=All#sms") == "/:ws/templates"
    assert page_key("https://app.example.com/") == "/"
    assert page_key("/workspaces") == "/workspaces"


def test_page_key_is_idempotent():
    assert page_key("/:ws/templates") == "/:ws/templates"


def test_section():
    assert section("/:ws/templates/new") == "templates"
    assert section("/:ws") == "home"


def test_element_key_is_page_scoped():
    assert element_key("/:ws/templates", "#save") == "/:ws/templates|#save"
