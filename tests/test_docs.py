from types import SimpleNamespace

from groundhog.crawl import docs

DOCS_URL = "https://docs.example.com"

SITEMAP = f"""<urlset>
<url><loc> {DOCS_URL}/templates-getting-started </loc></url>
<url><loc>{DOCS_URL}/template-creation-voice</loc></url>
<url><loc>{DOCS_URL}/release-notes/june</loc></url>
<url><loc>{DOCS_URL}/api-reference/send</loc></url>
</urlset>"""


def _resp(text, status_code=200):
    return SimpleNamespace(text=text, status_code=status_code)


def test_sitemap_paths_drop_noise_and_rank_prefers_overviews(monkeypatch):
    monkeypatch.setattr(docs.config, "DOCS_URL", DOCS_URL)
    monkeypatch.setattr(docs.httpx, "get", lambda url, **kw: _resp(SITEMAP))
    paths = docs._sitemap_paths()
    assert not any("release-notes" in p or "api-reference" in p for p in paths)
    ranked = docs._rank(paths, ["templates", "routes"])
    assert ranked.index("/templates-getting-started") < ranked.index("/template-creation-voice")


def test_sitemap_fallback_harvests_same_site_landing_hrefs(monkeypatch):
    landing = ('<a href="/guides/templates">t</a>'
               f'<a href="{DOCS_URL}/guides/routes?page=2">r</a>'
               '<a href="https://elsewhere.example.org/external">x</a>'
               '<a href="/guides/templates">dupe</a>')
    monkeypatch.setattr(docs.config, "DOCS_URL", DOCS_URL)
    monkeypatch.setattr(docs.httpx, "get",
                        lambda url, **kw: _resp("gone", 404) if url.endswith("/sitemap.xml") else _resp(landing))
    assert docs._sitemap_paths() == ["/guides/templates", "/guides/routes"]


def test_learn_features_snaps_names_and_drops_invented_endpoints(monkeypatch):
    monkeypatch.setattr(docs.config, "DOCS_URL", DOCS_URL)
    monkeypatch.setattr(docs.store, "run", lambda q, **kw: [{"s": "templates"}, {"s": "routes"}])
    monkeypatch.setattr(docs, "_sitemap_paths", lambda: ["/templates-overview"])
    monkeypatch.setattr(docs, "read_docs_page", lambda url: "templates feed routes")
    parsed = docs.FeatureMap(
        features=[docs.FeatureSummary(name="Template", summary="reusable message"),
                  docs.FeatureSummary(name="workflows", summary="not a section")],
        relations=[docs.FeatureRelation(from_feature="templates", to_feature="Routes",
                                        how="a route sends a template", source="templates-overview"),
                   docs.FeatureRelation(from_feature="templates", to_feature="workflows",
                                        how="invented endpoint", source="templates-overview")])
    monkeypatch.setattr(docs.client, "parse", lambda **kw: parsed)
    feats, rels = [], []
    monkeypatch.setattr(docs.store, "upsert_feature", lambda name, summary="": feats.append(name))
    monkeypatch.setattr(docs.store, "upsert_feature_relation",
                        lambda frm, to, how, source: rels.append((frm, to)))
    assert docs.learn_features() == {"features": 1, "relations": 1}
    assert feats == ["templates"]  # "Template" snapped; "workflows" dropped
    assert rels == [("templates", "routes")]


def test_zero_harvested_pages_makes_no_llm_call(monkeypatch):
    monkeypatch.setattr(docs.config, "DOCS_URL", DOCS_URL)
    monkeypatch.setattr(docs.store, "run", lambda q, **kw: [{"s": "templates"}])
    monkeypatch.setattr(docs, "_sitemap_paths", lambda: ["/templates"])

    def boom(url):
        raise RuntimeError("docs site down")

    monkeypatch.setattr(docs, "read_docs_page", boom)
    monkeypatch.setattr(docs.client, "parse",
                        lambda **kw: (_ for _ in ()).throw(AssertionError("LLM was called")))
    assert docs.learn_features() == {"features": 0, "relations": 0}
