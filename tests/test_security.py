from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _headers_text() -> str:
    return (ROOT / "public" / "_headers").read_text(encoding="utf-8")


def test_security_headers_are_present():
    text = _headers_text()
    required = [
        "Content-Security-Policy:",
        "X-Frame-Options: SAMEORIGIN",
        "X-Content-Type-Options: nosniff",
        "Referrer-Policy: strict-origin-when-cross-origin",
        "Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=()",
        "Strict-Transport-Security: max-age=63072000; includeSubDomains; preload",
        "Cross-Origin-Opener-Policy: same-origin",
        "Cross-Origin-Resource-Policy: same-origin",
        "Access-Control-Allow-Origin: https://imovanta.com.br",
    ]
    for header in required:
        assert header in text, header


def test_csp_is_restrictive_and_has_no_unsafe_eval():
    text = _headers_text()
    csp = next(
        line.split(":", 1)[1].strip()
        for line in text.splitlines()
        if line.strip().startswith("Content-Security-Policy:")
    )
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp
    assert "https://www.googletagmanager.com" in csp
    assert "object-src 'none'" in csp
    assert "base-uri 'self'" in csp
    assert "frame-ancestors 'self'" in csp
    assert "unsafe-eval" not in csp
    assert "unsafe-inline" not in csp


def test_no_source_maps_or_source_map_references():
    for directory in (ROOT / "public", ROOT / "functions"):
        assert not list(directory.rglob("*.map")), directory
    for js in (ROOT / "public" / "static").rglob("*.js"):
        text = js.read_text(encoding="utf-8", errors="ignore")
        assert "sourceMappingURL" not in text, js


def test_image_function_has_no_wildcard_cors():
    text = (ROOT / "functions" / "api" / "image.js").read_text(encoding="utf-8")
    assert "Access-Control-Allow-Origin" not in text
    assert "Access-Control-Allow-Credentials" not in text
    assert "__imoveis_cache" in text


def test_has_404_page():
    assert (ROOT / "public" / "404.html").exists()


def test_gtm_is_consent_gated_and_initialized_locally():
    loader = (ROOT / "public" / "static" / "gtm-loader.js").read_text(encoding="utf-8")
    assert "GTM-PQ5NNHX6" in loader
    assert "imoveis-radar-static:analytics-consent:v1" in loader
    assert "__loadGTM" in loader
    for page in ("index.html", "404.html"):
        html = (ROOT / "public" / page).read_text(encoding="utf-8")
        assert "/static/gtm-loader.js" in html


def test_no_inline_event_handlers_in_app():
    for path in (ROOT / "public" / "index.html", ROOT / "public" / "static" / "app.js"):
        text = path.read_text(encoding="utf-8")
        assert "onerror=" not in text, path
        assert "onclick=" not in text, path


def test_no_obvious_private_secrets():
    patterns = (
        "ghp_",
        "github_pat_",
        "sk-",
        "-----BEGIN PRIVATE KEY-----",
        "-----BEGIN RSA PRIVATE KEY-----",
        "password=",
        "password:",
    )
    current = Path(__file__).resolve()
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.resolve() == current:
            continue
        # O próprio relatório cita os padrões de busca; não é um segredo.
        if path.name == "security-audit.md":
            continue
        if any(part in {".git", ".venv", "__pycache__", "node_modules"} for part in path.parts):
            continue
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".ico", ".csv"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pattern in patterns:
            assert pattern not in text, f"{pattern} in {path}"
