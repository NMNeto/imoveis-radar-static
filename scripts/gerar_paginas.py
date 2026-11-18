#!/usr/bin/env python3
"""Gera as páginas estáticas de SEO (/imoveis/...) a partir dos dados publicados.

Uso:
    python scripts/gerar_paginas.py
    python scripts/gerar_paginas.py --json
    python scripts/gerar_paginas.py --min-cidades 10

Depois de gerar, rode ``python scripts/gerar_sitemap.py`` para atualizar o
sitemap (ou use o pipeline completo, que faz os dois).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from imoveis_radar import paginas  # noqa: E402
from imoveis_radar.config import PROJECT_ROOT, Paths  # noqa: E402
from imoveis_radar.publish import load_previous_items  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--public",
        type=Path,
        default=PROJECT_ROOT / "public",
        help="Diretório publicado (padrão: public/)",
    )
    parser.add_argument(
        "--min-cidades",
        type=int,
        default=paginas.MIN_CITY_ITEMS,
        help=f"Mínimo de imóveis para gerar página de cidade (padrão: {paginas.MIN_CITY_ITEMS})",
    )
    parser.add_argument("--json", action="store_true", help="Saída em JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    public = args.public.resolve()
    paths = Paths(public=public)
    if not (public / "index.html").exists():
        print(f"Erro: {public} não parece um diretório publicado", file=sys.stderr)
        return 2
    items = load_previous_items(paths)
    if not items:
        print("Nenhum dado publicado em public/data; rode a atualização antes.", file=sys.stderr)
        return 1
    summary = paginas.generate(public, items, min_city_items=args.min_cidades)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False))
    else:
        tipos = summary["tipos"]
        print(
            f"páginas: {summary['paginas']} "
            f"({tipos['cidade']} cidades, {tipos['uf']} UFs, {tipos['banco']} bancos, 1 hub) | "
            f"alteradas: {summary['alteradas']} | removidas: {summary['removidas']} | "
            f"home atualizada: {'sim' if summary['home_cards_alterados'] else 'não'} | "
            f"{summary['segundos']}s"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
