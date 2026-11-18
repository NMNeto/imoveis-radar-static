#!/usr/bin/env python3
"""Verificação de SEO técnico de uma página publicada.

Valida o que o Googlebot recebe no HTML: título, description, canonical,
robots, H1, dados estruturados, robots.txt e sitemap.

Uso:
    python scripts/verificar_seo.py
    python scripts/verificar_seo.py --url https://imovanta.com.br/
    python scripts/verificar_seo.py --url http://127.0.0.1:8080/

Sai com código 1 quando alguma verificação falha.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

USER_AGENT = (
    "Mozilla/5.0 (compatible; ImovantaSeoCheck/1.0; +https://imovanta.com.br/)"
)
TIMEOUT = 25
TITLE_MIN, TITLE_MAX = 15, 65
DESC_MIN, DESC_MAX = 70, 160


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


def fetch(url: str) -> tuple[int, dict[str, str], str]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            headers = {key.lower(): value for key, value in response.headers.items()}
            return response.status, headers, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        headers = {key.lower(): value for key, value in exc.headers.items()}
        return exc.code, headers, exc.read().decode("utf-8", "replace")


def _meta(soup: BeautifulSoup, **attrs) -> str:
    tag = soup.find("meta", attrs=attrs)
    return (tag.get("content") or "").strip() if tag else ""


def _json_ld_blocks(soup: BeautifulSoup) -> list[dict]:
    blocks = []
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            payload = json.loads(tag.string or "")
        except (ValueError, TypeError):
            continue
        if isinstance(payload, dict):
            blocks.append(payload)
    return blocks


def _types(payload: dict) -> set[str]:
    found: set[str] = set()
    graph = payload.get("@graph")
    nodes = graph if isinstance(graph, list) else [payload]
    for node in nodes:
        if isinstance(node, dict) and node.get("@type"):
            kind = node["@type"]
            found.update(kind if isinstance(kind, list) else [kind])
    return found


def check_page(
    url: str,
    status: int,
    headers: dict[str, str],
    html: str,
    expected_canonical: str | None = None,
) -> list[Check]:
    soup = BeautifulSoup(html, "html.parser")
    expected = (expected_canonical or url).split("?")[0].rstrip("/")
    checks = [
        Check("Página responde 200", status == 200, f"status {status}"),
    ]

    robots = _meta(soup, name="robots").lower()
    checks.append(
        Check(
            "Sem noindex",
            "noindex" not in robots,
            f"meta robots = {robots or '(ausente)'}",
        )
    )
    checks.append(
        Check(
            "Sem X-Robots-Tag bloqueando",
            "noindex" not in headers.get("x-robots-tag", "").lower(),
            headers.get("x-robots-tag", "(ausente)"),
        )
    )

    title = (soup.title.string or "").strip() if soup.title else ""
    checks.append(
        Check(
            f"Title entre {TITLE_MIN} e {TITLE_MAX} caracteres",
            TITLE_MIN <= len(title) <= TITLE_MAX,
            f'{len(title)} caracteres: "{title}"',
        )
    )

    description = _meta(soup, name="description")
    checks.append(
        Check(
            f"Description entre {DESC_MIN} e {DESC_MAX} caracteres",
            DESC_MIN <= len(description) <= DESC_MAX,
            f"{len(description)} caracteres",
        )
    )

    canonical = soup.find("link", rel="canonical")
    canonical_url = (canonical.get("href") or "").strip() if canonical else ""
    checks.append(
        Check(
            "Canonical absoluto e autorreferente",
            bool(canonical_url)
            and urlparse(canonical_url).scheme in ("http", "https")
            and canonical_url.rstrip("/") == expected,
            canonical_url or "(ausente)",
        )
    )

    h1s = soup.find_all("h1")
    h1_text = " ".join(h.get_text(" ", strip=True) for h in h1s).strip()
    checks.append(
        Check(
            "Exatamente um H1 com texto",
            len(h1s) == 1 and len(h1_text) >= 10,
            f'{len(h1s)} H1: "{h1_text[:80]}"',
        )
    )

    blocks = _json_ld_blocks(soup)
    types = set().union(*[_types(block) for block in blocks]) if blocks else set()
    checks.append(
        Check(
            "JSON-LD válido com WebSite e Organization",
            {"WebSite", "Organization"} <= types,
            f"{len(blocks)} bloco(s); tipos: {sorted(types) or 'nenhum'}",
        )
    )

    og_image = _meta(soup, property="og:image")
    og_w = _meta(soup, property="og:image:width")
    og_h = _meta(soup, property="og:image:height")
    checks.append(
        Check(
            "og:image absoluta em 1200x630",
            og_image.startswith("https://") and og_w == "1200" and og_h == "630",
            f"{og_image or '(ausente)'} {og_w}x{og_h}".strip(),
        )
    )

    checks.append(
        Check(
            "og:title e og:description preenchidos",
            bool(_meta(soup, property="og:title")) and bool(_meta(soup, property="og:description")),
            "",
        )
    )
    return checks


def check_robots(base: str) -> list[Check]:
    url = urljoin(base, "/robots.txt")
    try:
        status, _, body = fetch(url)
    except Exception as exc:  # noqa: BLE001 - relatório, não exceção
        return [Check("robots.txt acessível", False, str(exc))]
    return [
        Check("robots.txt acessível", status == 200, f"status {status}"),
        Check(
            "robots.txt aponta o sitemap",
            bool(re.search(r"^\s*Sitemap:\s*\S+", body, re.IGNORECASE | re.MULTILINE)),
            "",
        ),
        Check(
            "robots.txt não bloqueia o site inteiro",
            not re.search(r"^\s*Disallow:\s*/\s*$", body, re.MULTILINE),
            "",
        ),
    ]


def check_sitemap(base: str) -> list[Check]:
    url = urljoin(base, "/sitemap.xml")
    try:
        status, headers, body = fetch(url)
    except Exception as exc:  # noqa: BLE001
        return [Check("sitemap.xml acessível", False, str(exc))]
    urls = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", body)
    return [
        Check("sitemap.xml acessível", status == 200, f"status {status}"),
        Check("sitemap.xml é XML", body.lstrip().startswith("<?xml"), ""),
        Check("sitemap.xml com URLs", len(urls) > 0, f"{len(urls)} URL(s)"),
        Check(
            "sitemap.xml usa o domínio canônico",
            all(urlparse(u).netloc == "imovanta.com.br" for u in urls) if urls else False,
            urls[0] if urls else "(vazio)",
        ),
        Check(
            "sitemap.xml com Content-Type XML",
            "xml" in headers.get("content-type", ""),
            headers.get("content-type", "(ausente)"),
        ),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="https://imovanta.com.br/")
    parser.add_argument(
        "--canonical",
        default="https://imovanta.com.br/",
        help="Canonical esperado (use para testar em localhost)",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Não consulta robots.txt/sitemap.xml (apenas o HTML)",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    base = args.url.rstrip("/") + "/"
    try:
        status, headers, html = fetch(base)
    except Exception as exc:  # noqa: BLE001
        print(f"Erro ao buscar {base}: {exc}", file=sys.stderr)
        return 2

    checks = check_page(base, status, headers, html, args.canonical)
    if not args.offline:
        checks += check_robots(base)
        checks += check_sitemap(base)

    failures = [check for check in checks if not check.ok]
    if args.json:
        print(
            json.dumps(
                {
                    "url": base,
                    "ok": not failures,
                    "checks": [check.__dict__ for check in checks],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        for check in checks:
            mark = "OK  " if check.ok else "FALHA"
            extra = f" — {check.detail}" if check.detail else ""
            print(f"[{mark}] {check.name}{extra}")
        print(f"\n{len(checks) - len(failures)}/{len(checks)} verificações passaram")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
