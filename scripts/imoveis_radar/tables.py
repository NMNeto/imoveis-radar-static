"""Leitura e escrita de planilhas CSV usadas pelos scripts auxiliares."""
from __future__ import annotations

import csv
from pathlib import Path

from .text import find_column, norm


def detect_delimiter(sample: str) -> str:
    first_line = sample.splitlines()[0] if sample.strip() else ""
    return ";" if first_line.count(";") >= first_line.count(",") else ","


def read_table(path: Path) -> tuple[list[str], list[dict]]:
    with open(path, encoding="utf-8-sig", newline="") as handle:
        sample = handle.read(4096)
        handle.seek(0)
        delimiter = detect_delimiter(sample)
        reader = csv.DictReader(handle, delimiter=delimiter)
        columns = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]
    return columns, rows


def write_table(path: Path, columns: list[str], rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=columns,
            delimiter=";",
            lineterminator="\n",
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


def named_column(columns, name: str):
    """Acha uma coluna pelo nome exato; se não houver, pelo trecho."""
    target = norm(name)
    for column in columns:
        if norm(column) == target:
            return column
    return find_column(columns, name)
