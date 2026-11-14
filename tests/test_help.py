from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_help_markup_and_content():
    html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    for marker in (
        'id="btn-help"',
        'id="help-dialog"',
        'id="btn-help-close"',
        'id="btn-notice-help"',
        "criada para aprendizado com a ajuda de IA",
        "Como calculamos o desconto e o lucro",
        "Faça sua oferta",
        "Imóveis sem avaliação, sem preço ou com proposta",
        "Configurações",
        "Mapa e localização",
    ):
        assert marker in html, marker


def test_help_is_wired_in_app():
    app = (ROOT / "public" / "static" / "app.js").read_text(encoding="utf-8")
    assert "function openHelp" in app
    assert '#btn-help' in app
    assert '#btn-help-close' in app
    assert '#btn-notice-help' in app
