#!/usr/bin/env python3
"""Geocodifica uma planilha de endereços normalizados, com cache resumível.

A entrada é o arquivo gerado por ``normalizar_enderecos.py`` (a planilha
normalizada ou a fila de geocodificação).  Para cada chave única é consultado
o Nominatim, validando município/UF e classificando a precisão do resultado:

* ``endereco``   — o número de porta foi encontrado;
* ``rua``        — a via foi encontrada, sem o número;
* ``bairro``     — só o bairro foi localizado;
* ``aproximado`` — a cidade bate, mas a via não pôde ser confirmada.

O cache JSON guarda cada consulta; se o script for interrompido (ou o limite
de requisições for atingido), basta rodar de novo para continuar de onde parou:

    python scripts/geocodificar_planilha.py "Planilha Endereços_normalizado.csv"

Saídas padrão, ao lado da entrada:

    Planilha Endereços_normalizado_geocodificado.csv
    Planilha Endereços_normalizado_geocache.json

O Nominatim é público e aceita no máximo 1 requisição por segundo; o padrão de
1,05 s respeita esse limite.  Para um teste rápido use ``--limite 50``.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from imoveis_radar import geocode_client  # noqa: E402
from imoveis_radar.address_geocoder import geocode_endereco, haversine_km  # noqa: E402
from imoveis_radar.addresses import geocode_key, split_address  # noqa: E402
from imoveis_radar.tables import named_column, read_table, write_table  # noqa: E402
from imoveis_radar.text import field_text  # noqa: E402

GEO_COLUMNS = [
    "Status geocodificação",
    "Latitude geocodificada",
    "Longitude geocodificada",
    "Precisão geocodificada",
    "Fonte geocodificação",
    "Endereço retornado",
    "Distância da sede (km)",
]


def _parse_coord(value) -> float | None:
    try:
        return float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None


def load_cache(path: Path) -> dict:
    if not path.exists():
        return {"version": 1, "updated": None, "queries": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"version": 1, "updated": None, "queries": {}}
    if not isinstance(data, dict) or "queries" not in data:
        return {"version": 1, "updated": None, "queries": {}}
    return data


def save_cache(path: Path, cache: dict) -> None:
    cache["updated"] = datetime.now().isoformat(timespec="seconds")
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    os.replace(temporary, path)


def collect_targets(
    rows: list[dict], columns: list[str], por_numero: bool = False
) -> list[dict]:
    key_col = named_column(columns, "Chave de geocodificação")
    endereco_col = named_column(columns, "Endereço normalizado")
    uf_col = named_column(columns, "UF")
    cidade_col = named_column(columns, "Cidade normalizada") or named_column(
        columns, "Cidade"
    )
    bairro_col = named_column(columns, "Bairro normalizado") or named_column(
        columns, "Bairro"
    )
    lat_col = named_column(columns, "Latitude")
    lng_col = named_column(columns, "Longitude")
    if not (key_col and endereco_col and uf_col and cidade_col):
        raise ValueError(
            "a planilha precisa das colunas Chave de geocodificação, "
            "Endereço normalizado, UF e Cidade"
        )

    unique_input = "Imóveis" in columns
    targets: dict[str, dict] = {}
    for row in rows:
        full_key = field_text(row.get(key_col))
        if not full_key:
            continue
        endereco = field_text(row.get(endereco_col))
        parts = split_address(endereco)
        uf = field_text(row.get(uf_col))
        cidade = field_text(row.get(cidade_col))
        key = (
            full_key
            if por_numero
            else geocode_key(uf, cidade, parts.logradouro)
        )
        if key not in targets:
            targets[key] = {
                "key": key,
                "uf": uf,
                "cidade": cidade,
                "bairro": field_text(row.get(bairro_col)) if bairro_col else "",
                "logradouro": parts.logradouro,
                "numero": parts.numero if por_numero else "",
                "endereco": endereco,
                "imoveis": 0,
                "lat0": _parse_coord(row.get(lat_col)) if lat_col else None,
                "lng0": _parse_coord(row.get(lng_col)) if lng_col else None,
            }
        if unique_input:
            targets[key]["imoveis"] += int(field_text(row.get("Imóveis")) or 1)
        else:
            targets[key]["imoveis"] += 1
    return sorted(targets.values(), key=lambda item: (-item["imoveis"], item["key"]))


def geocode_targets(
    targets: list[dict],
    cache: dict,
    limit: int = 0,
    interval: float = 1.05,
    timeout: int = 25,
    save_every: int = 25,
    cache_path: Path | None = None,
) -> dict:
    """Consulta os alvos ainda ausentes do cache e devolve estatísticas."""
    queries = cache.setdefault("queries", {})
    pending = [target for target in targets if target["key"] not in queries]
    if limit > 0:
        pending = pending[:limit]

    geocode_client.MIN_INTERVAL = interval
    stats = {
        "pendentes_antes": len(pending),
        "novas": 0,
        "resolvidos": 0,
        "nao_encontrados": 0,
        "limite_atingido": False,
    }
    precisions: Counter = Counter()
    started = time.time()

    for index, target in enumerate(pending, start=1):
        try:
            result = geocode_endereco(
                target["uf"],
                target["cidade"],
                target["logradouro"],
                numero=target["numero"],
                bairro=target["bairro"],
                timeout=timeout,
            )
        except geocode_client.RateLimitError as exc:
            print(f"  Limite da API atingido: {exc}")
            stats["limite_atingido"] = True
            break

        queries[target["key"]] = result
        stats["novas"] += 1
        if result["status"] == "ok":
            stats["resolvidos"] += 1
            precisions[result["precisao"] or "aproximado"] += 1
        else:
            stats["nao_encontrados"] += 1

        if cache_path and index % save_every == 0:
            save_cache(cache_path, cache)
            elapsed = time.time() - started
            rate = index / elapsed if elapsed else 0
            remaining = len(pending) - index
            eta = remaining / rate / 60 if rate else 0
            print(
                f"  {index}/{len(pending)} consultas · "
                f"{stats['resolvidos']} encontrados · ETA {eta:.0f} min"
            )

    if cache_path:
        save_cache(cache_path, cache)
    stats["precisoes"] = dict(precisions)
    stats["segundos"] = round(time.time() - started, 1)
    return stats


def apply_results(
    rows: list[dict], columns: list[str], queries: dict, por_numero: bool = False
) -> list[dict]:
    key_col = named_column(columns, "Chave de geocodificação")
    endereco_col = named_column(columns, "Endereço normalizado")
    uf_col = named_column(columns, "UF")
    cidade_col = named_column(columns, "Cidade normalizada") or named_column(
        columns, "Cidade"
    )
    lat_col = named_column(columns, "Latitude")
    lng_col = named_column(columns, "Longitude")
    output = []
    for row in rows:
        full_key = field_text(row.get(key_col))
        if not full_key:
            key = ""
        elif por_numero:
            key = full_key
        else:
            parts = split_address(field_text(row.get(endereco_col)))
            key = geocode_key(
                field_text(row.get(uf_col)),
                field_text(row.get(cidade_col)),
                parts.logradouro,
            )
        result = queries.get(key)
        values = {
            "Status geocodificação": "",
            "Latitude geocodificada": "",
            "Longitude geocodificada": "",
            "Precisão geocodificada": "",
            "Fonte geocodificação": "",
            "Endereço retornado": "",
            "Distância da sede (km)": "",
        }
        if not key:
            values["Status geocodificação"] = "sem_endereco"
        elif not result:
            values["Status geocodificação"] = "pendente"
        elif result.get("status") == "ok":
            lat, lng = float(result["lat"]), float(result["lng"])
            values.update(
                {
                    "Status geocodificação": "ok",
                    "Latitude geocodificada": f"{lat:.6f}",
                    "Longitude geocodificada": f"{lng:.6f}",
                    "Precisão geocodificada": result.get("precisao", ""),
                    "Fonte geocodificação": result.get("fonte", ""),
                    "Endereço retornado": result.get("endereco_retornado", ""),
                }
            )
            lat0 = _parse_coord(row.get(lat_col)) if lat_col else None
            lng0 = _parse_coord(row.get(lng_col)) if lng_col else None
            if lat0 is not None and lng0 is not None:
                values["Distância da sede (km)"] = (
                    f"{haversine_km(lat0, lng0, lat, lng):.1f}"
                )
        else:
            values["Status geocodificação"] = result.get("status", "nao_encontrado")
        merged = dict(row)
        merged.update(values)
        output.append(merged)
    return output


def _default_path(path: Path, suffix: str, extension: str | None = None) -> Path:
    extension = extension or path.suffix or ".csv"
    return path.with_name(f"{path.stem}{suffix}{extension}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("planilha", type=Path, help="CSV normalizado ou fila de geocodificação")
    parser.add_argument("--saida", type=Path, help="CSV geocodificado de saída")
    parser.add_argument("--cache", type=Path, help="cache JSON (permite retomar)")
    parser.add_argument(
        "--limite",
        type=int,
        default=0,
        help="máximo de consultas novas nesta execução (0 = todas)",
    )
    parser.add_argument(
        "--intervalo",
        type=float,
        default=1.05,
        help="segundos entre requisições (Nominatim exige pelo menos 1)",
    )
    parser.add_argument("--timeout", type=int, default=25)
    parser.add_argument(
        "--por-numero",
        action="store_true",
        help="consulta cada número de porta (padrão: uma consulta por logradouro)",
    )
    args = parser.parse_args(argv)

    if not args.planilha.exists():
        print(f"Erro: arquivo não encontrado: {args.planilha}", file=sys.stderr)
        return 1

    saida = args.saida or _default_path(args.planilha, "_geocodificado")
    cache_path = args.cache or _default_path(
        args.planilha, "_geocache", ".json"
    )

    try:
        columns, rows = read_table(args.planilha)
        targets = collect_targets(rows, columns, por_numero=args.por_numero)
    except (OSError, ValueError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1

    cache = load_cache(cache_path)
    print(
        f"{len(targets)} endereços únicos · "
        f"{len(cache['queries'])} já no cache · iniciando…"
    )
    stats = geocode_targets(
        targets,
        cache,
        limit=args.limite,
        interval=args.intervalo,
        timeout=args.timeout,
        cache_path=cache_path,
    )

    output = apply_results(
        rows, columns, cache["queries"], por_numero=args.por_numero
    )
    write_table(saida, columns + GEO_COLUMNS, output)

    print(f"Arquivo: {saida}")
    print(
        f"Novas consultas: {stats['novas']} · encontrados: {stats['resolvidos']} · "
        f"não encontrados: {stats['nao_encontrados']} · "
        f"tempo: {stats['segundos']}s"
    )
    if stats["precisoes"]:
        detalhe = " · ".join(
            f"{name}: {count}"
            for name, count in sorted(
                stats["precisoes"].items(), key=lambda item: -item[1]
            )
        )
        print(f"Precisão dos resultados: {detalhe}")
    if stats["limite_atingido"]:
        print("Progresso salvo no cache; rode o mesmo comando para continuar.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
