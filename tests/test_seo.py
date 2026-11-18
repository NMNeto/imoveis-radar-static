from __future__ import annotations

import json
import re
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"

sys.path.insert(0, str(ROOT / "scripts"))

from imoveis_radar import sitemap  # noqa: E402
from verificar_seo import check_page  # noqa: E402


def _html(path: Path = PUBLIC / "index.html") -> str:
    return path.read_text(encoding="utf-8")


def _head() -> str:
    return _html().split("</head>", 1)[0]


def test_title_and_description_are_search_oriented():
    head = _head()
    title = re.search(r"<title>(.*?)</title>", head, re.S).group(1).strip()
    description = re.search(
        r'<meta name="description" content="(.*?)"', head, re.S
    ).group(1).strip()
    assert "Imóveis de leilão" in title
    assert "Imovanta" in title
    assert len(title) <= 65
    assert 70 <= len(description) <= 160
    assert "Caixa" in description and "Santander" in description


def test_canonical_and_social_metadata():
    head = _head()
    assert '<link rel="canonical" href="https://imovanta.com.br/">' in head
    assert '<meta property="og:image" content="https://imovanta.com.br/static/og-image.png">' in head
    assert '<meta property="og:image:width" content="1200">' in head
    assert '<meta property="og:image:height" content="630">' in head
    assert '<meta name="twitter:card" content="summary_large_image">' in head
    assert '<meta property="og:locale" content="pt_BR">' in head
    assert '<meta name="robots" content="index, follow' in head
    assert "noindex" not in head.lower()


def test_h1_has_keyword_text_but_keeps_logo():
    html = _html()
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
    assert h1, "H1 ausente"
    inner = h1.group(1)
    assert "logo-imovanta.png" in inner
    assert 'class="sr-only"' in inner
    assert "imóveis de leilão e retomados" in inner.lower()


def test_structured_data_graph():
    blocks = re.findall(
        r'<script type="application/ld\+json">(.*?)</script>', _html(), re.S
    )
    assert blocks, "nenhum JSON-LD encontrado"
    payloads = [json.loads(block) for block in blocks]
    types: set[str] = set()
    for payload in payloads:
        for node in payload.get("@graph", []):
            types.add(node["@type"])
    assert {"WebSite", "Organization"} <= types

    website = next(
        node
        for node in payloads[0]["@graph"]
        if node["@type"] == "WebSite"
    )
    assert website["url"] == "https://imovanta.com.br/"
    action = website["potentialAction"]
    assert action["@type"] == "SearchAction"
    assert "{search_term_string}" in action["target"]["urlTemplate"]

    organization = next(
        node for node in payloads[0]["@graph"] if node["@type"] == "Organization"
    )
    assert organization["logo"]["width"] == 1200
    assert organization["logo"]["height"] == 630


def test_og_image_is_1200x630_png():
    data = (PUBLIC / "static" / "og-image.png").read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", data[16:24])
    assert (width, height) == (1200, 630)


def test_404_is_noindex_and_site_is_not():
    assert "noindex" in _html(PUBLIC / "404.html").lower()
    assert "noindex" not in _head().lower()


def test_robots_txt_points_to_sitemap_and_skips_bulk_download():
    text = (PUBLIC / "robots.txt").read_text(encoding="utf-8")
    assert "Sitemap: https://imovanta.com.br/sitemap.xml" in text
    assert "Disallow: /data/busca_imoveis.csv" in text
    assert not re.search(r"^\s*Disallow:\s*/\s*$", text, re.MULTILINE)
    assert "Disallow: /*?*bbox=" in text


def test_security_headers_do_not_block_crawlers():
    text = (PUBLIC / "_headers").read_text(encoding="utf-8")
    assert "X-Robots-Tag" not in text
    assert "/sitemap.xml" in text


def test_committed_sitemap_lists_existing_indexable_pages():
    text = (PUBLIC / "sitemap.xml").read_text(encoding="utf-8")
    assert text.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    urls = re.findall(r"<loc>(.*?)</loc>", text)
    assert urls, "sitemap sem URLs"
    for url in urls:
        assert url.startswith("https://imovanta.com.br/")
        path = url.removeprefix("https://imovanta.com.br")
        target = PUBLIC / path.strip("/")
        target = target / "index.html" if path.endswith("/") or path == "" else target
        assert target.exists(), f"{url} não corresponde a arquivo publicado"


def _make_site(root: Path) -> Path:
    (root / "data").mkdir(parents=True)
    (root / "data" / "ultima_atualizacao.json").write_text(
        json.dumps({"data_atualizacao": "2026-11-17T09:00:00"}), encoding="utf-8"
    )
    (root / "index.html").write_text("<html><body>home</body></html>", encoding="utf-8")
    (root / "404.html").write_text(
        '<html><head><meta name="robots" content="noindex"></head></html>',
        encoding="utf-8",
    )
    (root / "static").mkdir()
    (root / "static" / "app.html").write_text("<html></html>", encoding="utf-8")
    (root / "imoveis" / "rj").mkdir(parents=True)
    (root / "imoveis" / "rj" / "index.html").write_text("<html>RJ</html>", encoding="utf-8")
    (root / "imoveis" / "rj" / "rio-de-janeiro").mkdir()
    (root / "imoveis" / "rj" / "rio-de-janeiro" / "index.html").write_text(
        "<html>Rio</html>", encoding="utf-8"
    )
    (root / "imoveis" / "rj" / "oculta").mkdir()
    (root / "imoveis" / "rj" / "oculta" / "index.html").write_text(
        '<html><head><meta name="robots" content="noindex,follow"></head></html>',
        encoding="utf-8",
    )
    return root


def test_sitemap_collects_pages_and_skips_excluded(tmp_path):
    public = _make_site(tmp_path / "public")
    assert sitemap.collect_urls(public) == [
        "/",
        "/imoveis/rj/",
        "/imoveis/rj/rio-de-janeiro/",
    ]


def test_sitemap_generation_is_idempotent(tmp_path):
    public = _make_site(tmp_path / "public")
    first = sitemap.generate(public)
    assert first.count == 3
    assert first.changed is True
    assert first.lastmod == "2026-11-17"

    second = sitemap.generate(public)
    assert second.changed is False

    text = (public / "sitemap.xml").read_text(encoding="utf-8")
    assert text.count("<url>") == 3
    assert "<loc>https://imovanta.com.br/imoveis/rj/</loc>" in text


def test_sitemap_splits_into_index_when_large(tmp_path):
    public = _make_site(tmp_path / "public")
    result = sitemap.generate(public, max_urls=2)
    assert result.count == 3
    assert "sitemap-1.xml" in result.files and "sitemap-2.xml" in result.files
    index = (public / "sitemap.xml").read_text(encoding="utf-8")
    assert "<sitemapindex" in index
    assert index.count("<sitemap>") == 2


def test_seo_checks_pass_on_home():
    checks = check_page(
        "https://imovanta.com.br/", 200, {}, _html()
    )
    failures = [check for check in checks if not check.ok]
    assert not failures, failures


def test_seo_checks_catch_regressions():
    broken = (
        "<html lang='pt-BR'><head><title>Imovanta</title>"
        '<meta name="robots" content="noindex">'
        "<link rel='canonical' href='/'>"
        "</head><body><h1>Imovanta</h1></body></html>"
    )
    checks = check_page("https://imovanta.com.br/", 200, {}, broken)
    failed = {check.name for check in checks if not check.ok}
    assert "Sem noindex" in failed
    assert "Canonical absoluto e autorreferente" in failed
    assert "JSON-LD válido com WebSite e Organization" in failed
    assert any(name.startswith("Description") for name in failed)
