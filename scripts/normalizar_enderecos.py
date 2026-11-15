#!/usr/bin/env python3
"""Normaliza endereços de uma planilha e gera a fila de geocodificação.

A planilha de entrada precisa ter, no mínimo, as colunas ``UF``, ``Cidade``,
``Bairro`` e ``Endereço`` (o separador ``;`` ou ``,`` é detectado sozinho).
O script acrescenta colunas normalizadas, sem alterar as originais, e grava
uma segunda planilha com uma linha por endereço único a geocodificar:

    python scripts/normalizar_enderecos.py "Planilha Endereços.csv"

Saídas padrão (ao lado da entrada):

    Planilha Endereços_normalizado.csv    planilha original + colunas novas
    Planilha Endereços_geocodificacao.csv fila única (1 linha por consulta)

Use ``--sem-numero`` para agrupar só pelo logradouro e reduzir ainda mais as
consultas.  Os complementos (quadra, lote, apartamento, bloco…) nunca entram
na chave: eles identificam o imóvel, não o endereço.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from imoveis_radar.addresses import (  # noqa: E402
    geocode_key,
    geocode_query,
    split_address,
)
from imoveis_radar.locations import canonicalize_locations  # noqa: E402
from imoveis_radar.tables import named_column, read_table, write_table  # noqa: E402
from imoveis_radar.text import field_text, norm  # noqa: E402

NORMALIZED_COLUMNS = [
    "Logradouro normalizado",
    "Número normalizado",
    "Complemento",
    "Endereço normalizado",
    "Cidade normalizada",
    "Bairro normalizado",
    "Chave de geocodificação",
    "Consulta de geocodificação",
]

QUEUE_COLUMNS = [
    "Chave de geocodificação",
    "Consulta de geocodificação",
    "UF",
    "Cidade normalizada",
    "Bairro normalizado",
    "Endereço normalizado",
    "Imóveis",
    "Grafias originais",
    "Latitude",
    "Longitude",
    "Precisão geográfica",
]

MAX_GRAPHIES = 5


def normalize_rows(
    rows: list[dict],
    columns: list[str],
    include_number: bool = True,
) -> tuple[list[dict], list[dict], dict]:
    """Normaliza as linhas e devolve (planilha, fila, estatísticas)."""
    uf_col = named_column(columns, "UF")
    cidade_col = named_column(columns, "Cidade")
    bairro_col = named_column(columns, "Bairro")
    endereco_col = named_column(columns, "Endereço")
    lat_col = named_column(columns, "Latitude")
    lng_col = named_column(columns, "Longitude")
    precisao_col = named_column(columns, "Precisão geográfica")
    if not (uf_col and cidade_col and endereco_col):
        raise ValueError("a planilha precisa das colunas UF, Cidade e Endereço")

    # Unifica grafias de cidade/bairro (ex.: "Feijó"/"FEIJO") por UF.
    locations = [
        {
            "uf": field_text(row.get(uf_col)),
            "cidade": field_text(row.get(cidade_col)),
            "bairro": field_text(row.get(bairro_col)) if bairro_col else "",
        }
        for row in rows
    ]
    locations, location_stats = canonicalize_locations(locations)

    normalized_rows: list[dict] = []
    groups: dict[str, dict] = {}
    raw_keys: set[tuple[str, str, str]] = set()
    normalized_keys: set[str] = set()
    street_keys: set[str] = set()
    missing_address = 0

    for row, location in zip(rows, locations):
        uf = location["uf"]
        cidade = location["cidade"]
        bairro = location["bairro"]
        raw = field_text(row.get(endereco_col))
        parts = split_address(raw)

        endereco = parts.logradouro
        if include_number and parts.numero:
            endereco = f"{parts.logradouro}, {parts.numero}"

        key = geocode_key(uf, cidade, endereco) if endereco else ""
        query = geocode_query(uf, cidade, endereco) if endereco else ""

        if endereco:
            raw_keys.add((norm(uf), norm(cidade), norm(raw)))
            normalized_keys.add(key)
            street_keys.add(geocode_key(uf, cidade, parts.logradouro))
        else:
            missing_address += 1

        output = dict(row)
        output.update(
            {
                "Logradouro normalizado": parts.logradouro,
                "Número normalizado": parts.numero,
                "Complemento": parts.complemento,
                "Endereço normalizado": endereco,
                "Cidade normalizada": cidade,
                "Bairro normalizado": bairro,
                "Chave de geocodificação": key,
                "Consulta de geocodificação": query,
            }
        )
        normalized_rows.append(output)

        if not endereco:
            continue
        group = groups.setdefault(
            key,
            {
                "consulta": query,
                "uf": uf,
                "cidade": cidade,
                "bairros": Counter(),
                "endereco": endereco,
                "imoveis": 0,
                "grafias": {},
                "coords": Counter(),
            },
        )
        group["bairros"][bairro] += 1
        group["imoveis"] += 1
        if len(group["grafias"]) < MAX_GRAPHIES:
            group["grafias"][raw or endereco] = None
        lat = field_text(row.get(lat_col)) if lat_col else ""
        lng = field_text(row.get(lng_col)) if lng_col else ""
        precisao = field_text(row.get(precisao_col)) if precisao_col else ""
        if lat and lng:
            group["coords"][(lat, lng, precisao)] += 1

    queue = []
    for key, group in groups.items():
        bairro = group["bairros"].most_common(1)[0][0] if group["bairros"] else ""
        coords = group["coords"].most_common(1)
        lat, lng, precisao = coords[0][0] if coords else ("", "", "")
        queue.append(
            {
                "Chave de geocodificação": key,
                "Consulta de geocodificação": group["consulta"],
                "UF": group["uf"],
                "Cidade normalizada": group["cidade"],
                "Bairro normalizado": bairro,
                "Endereço normalizado": group["endereco"],
                "Imóveis": group["imoveis"],
                "Grafias originais": " | ".join(group["grafias"]),
                "Latitude": lat,
                "Longitude": lng,
                "Precisão geográfica": precisao,
            }
        )
    queue.sort(key=lambda item: (-item["Imóveis"], item["Chave de geocodificação"]))

    before = len(raw_keys)
    after = len(normalized_keys)
    stats = {
        "linhas": len(rows),
        "sem_endereco": missing_address,
        "enderecos_distintos_antes": before,
        "enderecos_distintos_depois": after,
        "logradouros_distintos": len(street_keys),
        "consultas_unicas": len(queue),
        "reducao": round(1 - after / before, 4) if before else 0.0,
        "consultas_agrupando_grafias": sum(1 for g in groups.values() if len(g["grafias"]) > 1),
        **location_stats,
    }
    return normalized_rows, queue, stats


def _default_output(path: Path, suffix: str) -> Path:
    return path.with_name(f"{path.stem}{suffix}{path.suffix or '.csv'}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("planilha", type=Path, help="CSV de entrada (; ou ,)")
    parser.add_argument("--saida", type=Path, help="CSV normalizado de saída")
    parser.add_argument("--fila", type=Path, help="CSV com uma linha por endereço único")
    parser.add_argument(
        "--sem-numero",
        action="store_true",
        help="ignora o número de porta (agrupa pelo logradouro)",
    )
    args = parser.parse_args(argv)

    if not args.planilha.exists():
        print(f"Erro: arquivo não encontrado: {args.planilha}", file=sys.stderr)
        return 1

    saida = args.saida or _default_output(args.planilha, "_normalizado")
    fila = args.fila or _default_output(args.planilha, "_geocodificacao")

    try:
        columns, rows = read_table(args.planilha)
        normalized_rows, queue, stats = normalize_rows(
            rows, columns, include_number=not args.sem_numero
        )
    except (OSError, ValueError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1

    write_table(saida, columns + NORMALIZED_COLUMNS, normalized_rows)
    write_table(fila, QUEUE_COLUMNS, queue)

    print(f"Planilha normalizada: {saida}")
    print(f"Fila de geocodificação: {fila}")
    print(
        "Endereços distintos: "
        f"{stats['enderecos_distintos_antes']} -> {stats['enderecos_distintos_depois']} "
        f"({stats['reducao']:.1%} de redução)"
    )
    print(
        f"Consultas únicas: {stats['consultas_unicas']} | "
        f"logradouros distintos: {stats['logradouros_distintos']} | "
        f"linhas sem endereço: {stats['sem_endereco']}"
    )
    print(
        f"Cidades: {stats['cidades']} ({stats['variantes_cidade']} variantes unificadas) | "
        f"Bairros: {stats['bairros']} ({stats['variantes_bairro']} variantes unificadas)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
