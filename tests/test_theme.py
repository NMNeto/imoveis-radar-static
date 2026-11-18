from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"
sys.path.insert(0, str(ROOT / "scripts"))


def _html(path: Path = PUBLIC / "index.html") -> str:
    return path.read_text(encoding="utf-8")


def test_theme_script_runs_before_css():
    html = _html()
    script = html.index('src="static/theme.js"')
    css = html.index('href="static/style.css"')
    assert script < css, "theme.js precisa vir antes do CSS para evitar flash"


def test_theme_toggle_button_is_next_to_notice():
    html = _html()
    theme = html.index('id="btn-theme"')
    notice = html.index('id="btn-notice"')
    assert theme < notice
    button = html[theme - 100 : theme + 400]
    assert "data-theme-toggle" in button
    assert 'aria-pressed="false"' in button


def test_theme_script_persists_choice_and_respects_system():
    js = (PUBLIC / "static" / "theme.js").read_text(encoding="utf-8")
    assert "imoveis-radar-static:theme:v1" in js
    assert "prefers-color-scheme: dark" in js
    assert 'setAttribute("data-theme", next)' in js
    assert "localStorage.setItem(KEY, next)" in js
    assert "[data-theme-toggle]" in js


def test_dark_palette_is_defined():
    css = (PUBLIC / "static" / "style.css").read_text(encoding="utf-8")
    assert 'html[data-theme="dark"] {' in css
    assert "color-scheme: dark" in css
    dark = css.split('html[data-theme="dark"] {', 1)[1].split("}", 1)[0]
    for token in ("--bg:", "--panel:", "--ink:", "--muted:", "--line:"):
        assert token in dark


def test_dark_mode_covers_key_surfaces():
    css = (PUBLIC / "static" / "style.css").read_text(encoding="utf-8")
    for selector in ("dialog", ".topbar", ".skeleton-bar", ".thumb", ".tag", ".toast"):
        assert f'html[data-theme="dark"] {selector}' in css, selector


def test_generated_pages_include_theme_support():
    from imoveis_radar import paginas

    item = {
        "id": "1", "id_fonte": "1", "uf": "RJ", "cidade": "RIO DE JANEIRO",
        "bairro": "CENTRO", "endereco": "RUA A, 10", "preco": 100000.0,
        "preco_label": "", "valor_avaliacao": 200000.0, "valor_ajustado": 200000.0,
        "desconto": 50.0, "lucro": 20000.0, "lucro_pct": 10.0, "financiamento": "Sim",
        "modalidade": "Venda Online", "fonte": "caixa", "fonte_nome": "Caixa",
        "link": "https://exemplo.test/1", "imagem": "", "descricao": "Casa",
        "excluido": False, "sem_preco": False, "sem_avaliacao": False, "ajustado": False,
    }
    spec = next(s for s in paginas.build_specs([item]) if s.kind == "uf")
    html = paginas.render_page(spec, [item])
    assert 'src="/static/theme.js"' in html
    assert "data-theme-toggle" in html
    assert re.search(r"<script[^>]*>", html) is not None
