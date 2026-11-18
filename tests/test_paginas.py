from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"
sys.path.insert(0, str(ROOT / "scripts"))

from imoveis_radar import paginas, sitemap  # noqa: E402


def _item(item_id: str, uf: str, cidade: str, fonte: str = "caixa", **extra) -> dict:
    base = {
        "id": item_id,
        "id_fonte": item_id,
        "uf": uf,
        "cidade": cidade,
        "bairro": "CENTRO",
        "endereco": "RUA A, 10",
        "preco": 100000.0,
        "preco_label": "",
        "valor_avaliacao": 200000.0,
        "valor_ajustado": 200000.0,
        "desconto": 50.0,
        "lucro": 20000.0,
        "lucro_pct": 10.0,
        "financiamento": "Sim",
        "modalidade": "Venda Online",
        "fonte": fonte,
        "fonte_nome": paginas.SOURCE_LABELS.get(fonte, fonte),
        "link": "https://exemplo.test/imovel/1",
        "imagem": "https://exemplo.test/foto.jpg",
        "descricao": "Casa",
        "excluido": False,
        "sem_preco": False,
        "sem_avaliacao": False,
        "ajustado": False,
    }
    base.update(extra)
    return base


def _items() -> list[dict]:
    items = []
    for index in range(12):
        items.append(_item(f"rj{index}", "RJ", "RIO DE JANEIRO"))
    for index in range(10):
        items.append(_item(f"sp{index}", "SP", "SAO PAULO", fonte="itau"))
    for index in range(3):
        items.append(_item(f"mg{index}", "MG", "BELO HORIZONTE", fonte="bb"))
    return items


def _html(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_build_specs_creates_hub_ufs_cities_and_banks():
    specs = paginas.build_specs(_items())
    kinds = [spec.kind for spec in specs]
    paths = {spec.path for spec in specs}
    assert kinds.count("hub") == 1
    assert kinds.count("uf") == 3
    assert kinds.count("cidade") == 2  # MG tem 3 imóveis, abaixo do mínimo
    assert kinds.count("banco") == 3
    assert "/imoveis/" in paths
    assert "/imoveis/rj/" in paths
    assert "/imoveis/rj/rio-de-janeiro/" in paths
    assert "/imoveis/banco/itau/" in paths


def test_slugify_handles_accents_and_symbols():
    assert paginas.slugify("São Gonçalo") == "sao-goncalo"
    assert paginas.slugify("Itaboraí") == "itaborai"
    assert paginas.slugify("  Rio   de Janeiro ") == "rio-de-janeiro"
    assert paginas.slugify("") == "cidade"


def test_rendered_city_page_has_content_and_metadata():
    spec = next(
        s for s in paginas.build_specs(_items()) if s.path == "/imoveis/rj/rio-de-janeiro/"
    )
    html = paginas.render_page(spec, _items())
    title = re.search(r"<title>(.*?)</title>", html).group(1)
    assert "Rio de Janeiro" in title
    assert '<link rel="canonical" href="https://imovanta.com.br/imoveis/rj/rio-de-janeiro/">' in html
    assert html.count('<article class="card"') == paginas.CARDS_PAGE
    assert '<h1 class="lp-title">Imóveis de leilão em Rio de Janeiro/RJ</h1>' in html
    assert '<meta name="robots" content="index, follow' in html
    assert "app.js" not in html  # página estática, sem JS do app
    assert '<span class="lp-stat-value">12</span>' in html
    assert "Outras cidades em Rio de Janeiro" not in html  # só há uma cidade no RJ


def test_rendered_page_counts_match_between_title_intro_and_stats():
    for spec in paginas.build_specs(_items()):
        html = paginas.render_page(spec, _items())
        stats = re.search(r'<span class="lp-stat-value">([\d.]+)</span>', html).group(1)
        intro = re.search(r"<strong>([\d.]+) imóveis</strong>", html).group(1)
        assert stats == intro


def test_json_ld_is_valid_collection_page():
    spec = next(
        s for s in paginas.build_specs(_items()) if s.path == "/imoveis/rj/"
    )
    html = paginas.render_page(spec, _items())
    block = re.search(
        r'<script type="application/ld\+json">(.*?)</script>', html, re.S
    ).group(1)
    payload = json.loads(block)
    types = {node["@type"] for node in payload["@graph"]}
    assert {"BreadcrumbList", "CollectionPage"} <= types
    page = next(n for n in payload["@graph"] if n["@type"] == "CollectionPage")
    assert page["url"] == "https://imovanta.com.br/imoveis/rj/"
    assert page["mainEntity"]["numberOfItems"] == 12
    assert len(page["mainEntity"]["itemListElement"]) == paginas.CARDS_PAGE


def test_generate_writes_pages_and_is_idempotent(tmp_path):
    public = tmp_path / "public"
    public.mkdir()
    (public / "index.html").write_text(
        '<html><body><div id="cards">\n<!-- cards:inicio -->\n<!-- cards:fim -->\n</div></body></html>',
        encoding="utf-8",
    )
    first = paginas.generate(public, _items())
    assert first["paginas"] == 9  # hub + 3 UFs + 2 cidades + 3 bancos
    assert (public / "imoveis" / "rj" / "rio-de-janeiro" / "index.html").exists()
    assert "cards:inicio" in (public / "index.html").read_text(encoding="utf-8")
    assert '<article class="card"' in (public / "index.html").read_text(encoding="utf-8")

    second = paginas.generate(public, _items())
    assert second["alteradas"] == 0


def test_generate_removes_pages_that_no_longer_qualify(tmp_path):
    public = tmp_path / "public"
    public.mkdir()
    (public / "index.html").write_text("<html></html>", encoding="utf-8")
    stale = public / "imoveis" / "rj" / "cidade-antiga" / "index.html"
    stale.parent.mkdir(parents=True)
    stale.write_text("<html>antiga</html>", encoding="utf-8")
    paginas.generate(public, _items())
    assert not stale.exists()
    assert (public / "imoveis" / "rj" / "rio-de-janeiro" / "index.html").exists()


def test_sitemap_includes_generated_pages(tmp_path):
    public = tmp_path / "public"
    public.mkdir()
    (public / "index.html").write_text("<html></html>", encoding="utf-8")
    (public / "data").mkdir()
    (public / "data" / "ultima_atualizacao.json").write_text(
        '{"data_atualizacao": "2026-11-17T09:00:00"}', encoding="utf-8"
    )
    paginas.generate(public, _items())
    sitemap.generate(public, lastmod="2026-11-17")
    text = (public / "sitemap.xml").read_text(encoding="utf-8")
    assert "<loc>https://imovanta.com.br/imoveis/rj/rio-de-janeiro/</loc>" in text
    assert "<loc>https://imovanta.com.br/imoveis/banco/itau/</loc>" in text
    assert "<loc>https://imovanta.com.br/</loc>" in text


def test_cards_escape_user_content():
    item = _item("x1", "RJ", "RIO DE JANEIRO", endereco='RUA "A" <script>', bairro="CENTRO")
    html = paginas.card_html(item)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html or "&quot;" in html


def test_static_cards_have_no_local_only_actions():
    item = _item("x1", "RJ", "RIO DE JANEIRO")
    static = paginas.card_html(item)
    interactive = paginas.card_html(item, interactive=True)
    assert 'data-action="exclude"' not in static
    assert 'data-action="exclude"' in interactive


def test_committed_pages_exist_for_every_sitemap_url():
    text = _html(PUBLIC / "sitemap.xml")
    urls = re.findall(r"<loc>(.*?)</loc>", text)
    assert len(urls) > 1
    for url in urls:
        path = url.removeprefix("https://imovanta.com.br").strip("/")
        target = PUBLIC / path
        if not path or url.endswith("/"):
            target = PUBLIC / path / "index.html"
        assert target.exists(), url
