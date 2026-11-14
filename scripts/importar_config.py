#!/usr/bin/env python3
"""Aplica um config-local.json exportado pelo site aos arquivos do repositório.

O site estático permite editar custos, exclusões e valores de venda no próprio
navegador.  Para tornar essas mudanças permanentes (e válidas para todos os
visitantes), exporte o arquivo pela caixa de Configurações e rode:

    python scripts/importar_config.py ~/Downloads/config-local.json

O script grava exclusivamente em ``data/config/``.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from imoveis_radar.config import Paths  # noqa: E402
from imoveis_radar.model import normalize_settings  # noqa: E402
from imoveis_radar.safety import (  # noqa: E402
    assert_isolated,
    atomic_write_bytes,
)
from imoveis_radar.text import parse_money  # noqa: E402


def _id_sort_key(value: str):
    return (0, int(value)) if value.isdigit() else (1, value)


def _exclude_ids_text(values) -> bytes:
    ids = sorted({str(value).strip() for value in values if str(value).strip()}, key=_id_sort_key)
    return ("\n".join(ids) + ("\n" if ids else "")).encode("utf-8")


def _locations_text(values) -> bytes:
    rows = []
    for location in values or []:
        cidade = str(location.get("cidade", "")).strip()
        bairro = str(location.get("bairro", "")).strip()
        endereco = str(location.get("endereco", "")).strip()
        if cidade or bairro or endereco:
            rows.append((cidade, bairro, endereco))
    rows = sorted(set(rows))
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["Cidade", "Bairro", "Endereço"])
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def _market_values_text(values) -> bytes:
    rows = []
    for item_id, value in (values or {}).items():
        parsed = parse_money(value)
        if parsed is not None:
            rows.append((str(item_id).strip(), parsed))
    rows = [row for row in rows if row[0]]
    rows.sort(key=lambda row: _id_sort_key(row[0]))
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["ID", "Valor de Venda Aproximado"])
    for item_id, value in rows:
        writer.writerow([item_id, f"{value:.2f}"])
    return output.getvalue().encode("utf-8")


def _settings_text(values) -> bytes:
    settings = normalize_settings(values)
    return (
        json.dumps(settings, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def apply_config(paths: Paths, payload: dict, dry_run: bool = False) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("O arquivo precisa conter um objeto JSON")
    settings = payload.get("settings")
    exclude_ids = payload.get("exclude_ids")
    exclude_locations = payload.get("exclude_locations")
    market_values = payload.get("market_values")
    if settings is not None and not isinstance(settings, dict):
        raise ValueError("settings deve ser um objeto")
    if exclude_ids is not None and not isinstance(exclude_ids, list):
        raise ValueError("exclude_ids deve ser uma lista")
    if exclude_locations is not None and not isinstance(exclude_locations, list):
        raise ValueError("exclude_locations deve ser uma lista")
    if market_values is not None and not isinstance(market_values, dict):
        raise ValueError("market_values deve ser um objeto")

    writes = {
        paths.config_file: _settings_text(settings or {}),
        paths.exclude_ids_file: _exclude_ids_text(exclude_ids or []),
        paths.exclude_locations_file: _locations_text(exclude_locations or []),
        paths.market_values_file: _market_values_text(market_values or {}),
    }
    written = []
    for path, content in writes.items():
        if dry_run:
            written.append(path.name)
        elif atomic_write_bytes(path, content, paths.data):
            written.append(path.name)
    return {
        "ok": True,
        "dry_run": dry_run,
        "arquivos": written,
        "ids": len(exclude_ids or []),
        "locais": len(exclude_locations or []),
        "valores": len(market_values or {}),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("arquivo", type=Path, help="config-local.json exportado pelo site")
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    paths = Paths.from_env()
    if args.data_dir:
        paths = Paths(root=paths.root, data=args.data_dir.resolve(), public=paths.public)
    assert_isolated(paths)

    try:
        with open(args.arquivo, encoding="utf-8") as handle:
            payload = json.load(handle)
        result = apply_config(paths, payload, dry_run=args.dry_run)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
