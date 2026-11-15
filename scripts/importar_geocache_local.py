#!/usr/bin/env python3
"""Importa o resultado de um bulk local para o cache do projeto.

Uso único, depois de rodar ``geocodificar_planilha.py`` na planilha
normalizada. O importador:

* copia ruas terminais (``endereco``/``rua``) para ``cache["ruas"]``;
* registra ruas de baixa precisão sem coordenada, elegíveis para retentativa;
* copia os centroides de bairro para ``cache["points"]``;
* ignora chaves que não existem entre os imóveis publicados;
* é idempotente e nunca rebaixa uma entrada melhor.

Exemplo:

    python scripts/importar_geocache_local.py \
        --planilha "Planilha Endereços_normalizado_geocodificado.csv" \
        --cache-local "Planilha Endereços_normalizado_geocache.json"
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from imoveis_radar import publish  # noqa: E402
from imoveis_radar.config import Paths  # noqa: E402
from imoveis_radar.geo import (  # noqa: E402
    geocode_key,
    item_street_key,
    load_geocode_cache,
    save_geocode_cache,
    set_bairro_point,
)
from imoveis_radar.tables import read_table  # noqa: E402
from imoveis_radar.text import field_text  # noqa: E402

TERMINAL_PRECISIONS = {"endereco", "rua"}


def _parse_coord(value) -> float | None:
    try:
        return float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _project_keys(paths: Paths) -> set[str]:
    items = publish.load_previous_items(paths)
    keys = {
        item_street_key(item)
        for item in items
        if not item.get("excluido")
    }
    keys.discard("")
    return keys


def import_streets(
    cache: dict,
    queries: dict,
    project_keys: set[str],
    today: date | None = None,
) -> dict:
    """Copia as ruas do cache local, sem rebaixar entradas terminais."""
    today = today or date.today()
    ruas = cache.setdefault("ruas", {})
    stats = {
        "terminais": 0,
        "baixa_precisao": 0,
        "nao_encontradas": 0,
        "ignoradas": 0,
        "existentes": 0,
    }
    for key, result in queries.items():
        if key not in project_keys:
            stats["ignoradas"] += 1
            continue

        terminal = (
            result.get("status") == "ok"
            and result.get("precisao") in TERMINAL_PRECISIONS
            and result.get("lat") is not None
            and result.get("lng") is not None
        )
        existing = ruas.get(key)
        if existing and (
            existing.get("status") == "ok"
            and existing.get("precisao") in TERMINAL_PRECISIONS
        ):
            stats["existentes"] += 1
            continue

        if terminal:
            ruas[key] = {
                "status": "ok",
                "lat": float(result["lat"]),
                "lng": float(result["lng"]),
                "precisao": result["precisao"],
                "fonte": result.get("fonte") or "nominatim",
                "endereco_retornado": result.get("endereco_retornado", ""),
                "consulta": result.get("consulta", ""),
                "tentativas": int(result.get("tentativas") or 1),
                "atualizado_em": result.get("atualizado_em") or _now_iso(),
                "proxima_tentativa": None,
            }
            stats["terminais"] += 1
            continue

        if existing:
            stats["existentes"] += 1
            continue

        status = "baixa_precisao" if result.get("status") == "ok" else (
            result.get("status") or "nao_encontrado"
        )
        ruas[key] = {
            "status": status,
            "precisao": result.get("precisao") or "",
            "tentativas": int(result.get("tentativas") or 1),
            "atualizado_em": result.get("atualizado_em") or _now_iso(),
            "proxima_tentativa": today.isoformat(),
        }
        if result.get("status") == "ok":
            stats["baixa_precisao"] += 1
        else:
            stats["nao_encontradas"] += 1
    return stats


def collect_bairros(rows: list[dict]) -> dict[str, dict]:
    """Agrupa os centroides de bairro do CSV, escolhendo o mais frequente."""
    grouped: dict[str, dict] = {}
    for row in rows:
        if field_text(row.get("Status geocodificação")) != "ok":
            continue
        if field_text(row.get("Precisão geocodificada")) != "bairro":
            continue
        uf = field_text(row.get("UF"))
        cidade = field_text(row.get("Cidade normalizada"))
        bairro = field_text(row.get("Bairro normalizado"))
        lat = _parse_coord(row.get("Latitude geocodificada"))
        lng = _parse_coord(row.get("Longitude geocodificada"))
        if not (uf and cidade and bairro) or lat is None or lng is None:
            continue
        key = geocode_key(uf, cidade, bairro)
        entry = grouped.setdefault(
            key,
            {
                "uf": uf,
                "cidade": cidade,
                "bairro": bairro,
                "coordenadas": Counter(),
            },
        )
        entry["coordenadas"][(round(lat, 6), round(lng, 6))] += 1

    result = {}
    for key, entry in grouped.items():
        (lat, lng), _ = entry["coordenadas"].most_common(1)[0]
        result[key] = {
            "uf": entry["uf"],
            "cidade": entry["cidade"],
            "bairro": entry["bairro"],
            "lat": lat,
            "lng": lng,
        }
    return result


def import_bairros(cache: dict, rows: list[dict]) -> dict:
    """Grava os centroides de bairro em ``points``."""
    bairros = collect_bairros(rows)
    added = 0
    existing = 0
    for bairro in bairros.values():
        changed = set_bairro_point(
            cache,
            bairro["uf"],
            bairro["cidade"],
            bairro["bairro"],
            bairro["lat"],
            bairro["lng"],
        )
        if changed:
            added += 1
        else:
            existing += 1
    return {
        "distintos": len(bairros),
        "adicionados": added,
        "existentes": existing,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--planilha",
        type=Path,
        default=Path("Planilha Endereços_normalizado_geocodificado.csv"),
        help="CSV geocodificado do bulk local",
    )
    parser.add_argument(
        "--cache-local",
        type=Path,
        default=Path("Planilha Endereços_normalizado_geocache.json"),
        help="cache JSON gerado por geocodificar_planilha.py",
    )
    parser.add_argument(
        "--cache",
        type=Path,
        help="cache do projeto (padrão: data/geo/geocode_cache.json)",
    )
    parser.add_argument("--sem-bairros", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if not args.planilha.exists():
        print(f"Erro: planilha não encontrada: {args.planilha}", file=sys.stderr)
        return 1
    if not args.cache_local.exists():
        print(f"Erro: cache local não encontrado: {args.cache_local}", file=sys.stderr)
        return 1

    try:
        payload = json.loads(args.cache_local.read_text(encoding="utf-8"))
        queries = payload.get("queries") or {}
    except (OSError, ValueError) as exc:
        print(f"Erro ao ler cache local: {exc}", file=sys.stderr)
        return 1

    paths = Paths()
    cache_path = args.cache or paths.geocode_cache_file
    cache = load_geocode_cache(cache_path)
    project_keys = _project_keys(paths)
    if not project_keys:
        print(
            "Aviso: nenhum imóvel publicado encontrado; importando sem filtro.",
            file=sys.stderr,
        )
        project_keys = set(queries)

    street_stats = import_streets(cache, queries, project_keys)
    columns, rows = read_table(args.planilha)
    bairro_stats = (
        {"distintos": 0, "adicionados": 0, "existentes": 0}
        if args.sem_bairros
        else import_bairros(cache, rows)
    )

    saved = False
    if not args.dry_run:
        save_geocode_cache(cache_path, cache, paths.root)
        saved = True

    summary = {
        "cache": str(cache_path),
        "salvo": saved,
        "ruas": street_stats,
        "bairros": bairro_stats,
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False))
    else:
        print(f"Cache: {cache_path}")
        print(
            "Ruas: {terminais} terminais · {baixa_precisao} baixa precisão · "
            "{nao_encontradas} não encontradas · {ignoradas} ignoradas · "
            "{existentes} já existentes".format(**street_stats)
        )
        print(
            "Bairros: {distintos} distintos · {adicionados} adicionados · "
            "{existentes} já existentes".format(**bairro_stats)
        )
        if not saved:
            print("Simulação: cache não foi gravado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
