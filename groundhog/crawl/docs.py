"""Docs-informed feature layer: sitemap → ranked overview pages → one batched
SMART call → Feature nodes and RELATED_TO edges. Feature names are snapped to
the graph's existing Page.section vocabulary (sections already ARE the app's
features), so extraction stays verifiable and Page→Feature linking is a
one-property match. Opt-in via `groundhog crawl --docs`."""

import re
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field
from rich.console import Console

from groundhog import config
from groundhog.graph import store
from groundhog.llm import client

console = Console()

NOISE = ("release-notes", "api-reference")
OVERVIEW = ("introduction", "getting-started", "overview")


def read_docs_page(url: str) -> str:
    """Docs page → plain text. Only the configured docs site is readable."""
    if not url.startswith(config.DOCS_URL):
        return f"error: only {config.DOCS_URL} pages can be read"
    text = httpx.get(url, follow_redirects=True, timeout=15).text
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text)[:4000]


def _sitemap_paths() -> list[str]:
    """Candidate docs paths, noise sections dropped. Docs sites do not
    guarantee a sitemap.xml, so fall back to harvesting same-site hrefs off
    the landing page (one GET) when the sitemap is missing or empty."""
    prefix = urlparse(config.DOCS_URL).path
    resp = httpx.get(f"{config.DOCS_URL}/sitemap.xml", follow_redirects=True, timeout=15)
    urls = re.findall(r"<loc>\s*(.*?)\s*</loc>", resp.text) if resp.status_code == 200 else []
    if not urls:
        html = httpx.get(config.DOCS_URL, follow_redirects=True, timeout=15).text
        urls = [h for h in re.findall(r'href="([^"]+)"', html)
                if h.startswith("/") or h.startswith(config.DOCS_URL)]
    paths, seen = [], set()
    for u in urls:
        p = urlparse(u).path.rstrip("/")
        if p and p.startswith(prefix) and not any(n in p for n in NOISE) and p not in seen:
            seen.add(p)
            paths.append(p)
    return paths


def _stem(word: str) -> str:
    return word[:-1] if word.endswith("s") else word


def _rank(paths: list[str], sections: list[str], limit: int = 10) -> list[str]:
    """Feature-overview pages first: slugs naming graph sections (plural-
    insensitive) and intro/overview slugs beat deep reference pages."""
    stems = {_stem(s.lower()) for s in sections}

    def score(path: str) -> int:
        hits = sum(1 for w in re.findall(r"[a-z0-9]+", path.lower()) if _stem(w) in stems)
        boost = 2 if any(o in path.lower() for o in OVERVIEW) else 0
        return 3 * hits + boost - path.count("/")

    return sorted(paths, key=score, reverse=True)[:limit]


class FeatureSummary(BaseModel):
    name: str
    summary: str = ""


class FeatureRelation(BaseModel):
    from_feature: str
    to_feature: str
    how: str
    source: str  # docs slug the claim came from


class FeatureMap(BaseModel):
    features: list[FeatureSummary] = Field(default_factory=list)
    relations: list[FeatureRelation] = Field(default_factory=list)


def _snap(name: str, sections: list[str]) -> str | None:
    """Exact or plural-insensitive match into the section vocabulary — like
    the is_weak gate, the model never invents graph vocabulary."""
    n = name.strip().lower()
    return next((s for s in sections if _stem(n) == _stem(s)), None)


def learn_features() -> dict:
    """One batched SMART pass over the ranked docs pages → Feature nodes and
    RELATED_TO edges, written only through the store upserts."""
    sections = [r["s"] for r in store.run("MATCH (p:Page) RETURN DISTINCT p.section AS s") if r["s"]]
    if not sections:
        console.print("[yellow]graph has no sections yet — crawl before running --docs[/]")
        return {"features": 0, "relations": 0}
    pages = []
    for path in _rank(_sitemap_paths(), sections):
        try:
            pages.append(f"## {path}\n{read_docs_page(config.DOCS_URL + path)}")
        except Exception:
            continue  # one unreachable page never kills the pass
    if not pages:
        return {"features": 0, "relations": 0}
    result = client.parse(
        user="\n\n".join(pages),
        output_model=FeatureMap,
        system=client.prompt("features", sections=", ".join(sorted(sections))),
        model=client.SMART,
        max_tokens=4096,
    )
    counts = {"features": 0, "relations": 0}
    for f in result.features:
        name = _snap(f.name, sections)
        if name:
            store.upsert_feature(name, f.summary)
            counts["features"] += 1
    for rel in result.relations:
        frm, to = _snap(rel.from_feature, sections), _snap(rel.to_feature, sections)
        if frm and to:
            store.upsert_feature_relation(frm, to, rel.how, rel.source)
            counts["relations"] += 1
    return counts
