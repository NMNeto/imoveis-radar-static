#!/usr/bin/env python3
"""Gera ``public/sitemap.xml`` a partir das páginas HTML publicadas.

Uso:
    python scripts/gerar_sitemap.py
    python scripts/gerar_sitemap.py --public public --site-url https://imovanta.com.br
    python scripts/gerar_sitemap.py --lastmod 2026-11-17 --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from imoveis_radar import sitemap  # noqa: E402
from imoveis_radar.config import PROJECT_ROOT  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--public",
        type=Path,
        default=PROJECT_ROOT / "public",
        help="Diretório publicado (padrão: public/)",
    )
    parser.add_argument(
        "--site-url",
        default=sitemap.SITE_URL,
        help=f"URL base do site (padrão: {sitemap.SITE_URL})",
    )
    parser.add_argument(
        "--lastmod",
        default="",
        help="Data ISO para lastmod (padrão: data de ultima_atualizacao.json)",
    )
    parser.add_argument("--json", action="store_true", help="Saída em JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    public = args.public.resolve()
    if not (public / "index.html").exists():
        print(f"Erro: {public} não parece um diretório publicado", file=sys.stderr)
        return 2
    result = sitemap.generate(
        public,
        site_url=args.site_url,
        lastmod=args.lastmod or None,
    )
    if result.count == 0:
        print("Nenhuma página indexável encontrada.", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result.as_dict(), ensure_ascii=False))
    else:
        state = "atualizado" if result.changed else "sem alterações"
        print(
            f"sitemap {state}: {result.count} URL(s) em "
            f"{public / sitemap.SITEMAP_FILE} (lastmod {result.lastmod})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
