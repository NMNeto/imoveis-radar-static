"""Geração do ``sitemap.xml`` a partir das páginas HTML publicadas.

O sitemap é derivado do que realmente existe em ``public/``: nada de URL
inventada.  Arquivos com ``noindex`` e a página 404 ficam de fora, assim como
os diretórios que não são páginas de conteúdo (``data``, ``static``).

Quando as landing pages por estado/cidade/banco forem geradas, elas entram no
sitemap automaticamente — basta existir o ``index.html`` correspondente.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from xml.sax.saxutils import escape

from .safety import atomic_write_bytes

logger = logging.getLogger(__name__)

SITE_URL = "https://imovanta.com.br"
SITEMAP_FILE = "sitemap.xml"
MAX_URLS_PER_FILE = 45_000
SKIP_DIRS = {"static", "data", ".well-known"}
SKIP_FILES = {"404.html"}
GOOGLE_VERIFICATION_RE = re.compile(r"^google[0-9a-f]+\.html$", re.IGNORECASE)
NOINDEX_RE = re.compile(
    r"<meta[^>]+name\s*=\s*[\"']robots[\"'][^>]*\bnoindex\b", re.IGNORECASE
)


@dataclass
class SitemapResult:
    count: int
    changed: bool
    files: list[str] = field(default_factory=list)
    lastmod: str = ""

    def as_dict(self) -> dict:
        return {
            "urls": self.count,
            "alterado": self.changed,
            "arquivos": self.files,
            "lastmod": self.lastmod,
        }


def page_url(relative: Path) -> str:
    """Converte um caminho relativo em URL pública canônica."""
    parts = list(relative.parts)
    if parts[-1] == "index.html":
        parts.pop()
        return "/" + "".join(f"{part}/" for part in parts)
    return "/" + "/".join(parts)


def is_indexable(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return not NOINDEX_RE.search(text)


def collect_urls(public: Path) -> list[str]:
    """URLs de todas as páginas HTML publicadas que podem ser indexadas."""
    public = Path(public)
    urls: set[str] = set()
    for path in public.rglob("*.html"):
        relative = path.relative_to(public)
        if any(part in SKIP_DIRS for part in relative.parts[:-1]):
            continue
        if relative.name in SKIP_FILES:
            continue
        if GOOGLE_VERIFICATION_RE.match(relative.name):
            continue
        if not is_indexable(path):
            continue
        urls.add(page_url(relative))
    return sorted(urls)


def data_lastmod(public: Path) -> str:
    """Data de atualização dos dados, usada como ``lastmod`` das páginas."""
    path = Path(public) / "data" / "ultima_atualizacao.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return date.today().isoformat()
    value = str(payload.get("data_atualizacao") or payload.get("ultima_execucao") or "")
    try:
        return datetime.fromisoformat(value).date().isoformat()
    except ValueError:
        return date.today().isoformat()


def render_urlset(urls: list[str], site_url: str, lastmod: str) -> str:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for url in urls:
        lines.append("  <url>")
        lines.append(f"    <loc>{escape(site_url.rstrip('/') + url)}</loc>")
        lines.append(f"    <lastmod>{lastmod}</lastmod>")
        lines.append("  </url>")
    lines.append("</urlset>")
    return "\n".join(lines) + "\n"


def render_index(parts: list[str], site_url: str, lastmod: str) -> str:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for name in parts:
        lines.append("  <sitemap>")
        lines.append(f"    <loc>{escape(site_url.rstrip('/') + '/' + name)}</loc>")
        lines.append(f"    <lastmod>{lastmod}</lastmod>")
        lines.append("  </sitemap>")
    lines.append("</sitemapindex>")
    return "\n".join(lines) + "\n"


def generate(
    public: Path,
    *,
    site_url: str = SITE_URL,
    lastmod: str | None = None,
    max_urls: int = MAX_URLS_PER_FILE,
) -> SitemapResult:
    """Gera ``public/sitemap.xml``.  Idempotente: só grava se mudou."""
    public = Path(public)
    urls = collect_urls(public)
    if not urls:
        return SitemapResult(count=0, changed=False, lastmod=lastmod or "")
    stamp = lastmod or data_lastmod(public)
    changed = False
    written: list[str] = []

    if len(urls) <= max_urls:
        payload = render_urlset(urls, site_url, stamp)
        if atomic_write_bytes(public / SITEMAP_FILE, payload.encode("utf-8"), public):
            changed = True
        written.append(SITEMAP_FILE)
    else:
        parts: list[str] = []
        for index in range(0, len(urls), max_urls):
            name = f"sitemap-{index // max_urls + 1}.xml"
            payload = render_urlset(urls[index : index + max_urls], site_url, stamp)
            if atomic_write_bytes(public / name, payload.encode("utf-8"), public):
                changed = True
            parts.append(name)
            written.append(name)
        payload = render_index(parts, site_url, stamp)
        if atomic_write_bytes(public / SITEMAP_FILE, payload.encode("utf-8"), public):
            changed = True
        written.insert(0, SITEMAP_FILE)

    if changed:
        logger.info("Sitemap atualizado: %s URL(s) em %s", len(urls), ", ".join(written))
    else:
        logger.info("Sitemap sem alterações: %s URL(s)", len(urls))
    return SitemapResult(
        count=len(urls), changed=changed, files=written, lastmod=stamp
    )
