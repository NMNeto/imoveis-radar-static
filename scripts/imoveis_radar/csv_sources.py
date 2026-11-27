"""Leitura e validação dos CSVs das quatro fontes.

O formato é exatamente o do projeto original:

* Caixa: latin1, ``;``, linhas de título antes do cabeçalho;
* BB/Santander/Itaú: UTF-8 com BOM, ``;``.
"""
from __future__ import annotations

import csv
import glob
import os
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from .config import SOURCE_FILES, SOURCE_NAMES, SOURCE_ORDER
from .text import find_column, norm, parse_money


class SourceValidationError(RuntimeError):
    pass


@dataclass
class SourceFile:
    source_id: str
    path: Path
    rows: int
    generation_date: str | None
    encoding: str


def header_index(lines) -> int:
    """Encontra a linha de cabeçalho (o CSV da Caixa tem título antes)."""
    for index, line in enumerate(lines[:10]):
        low = norm(line)
        if "UF" in low and "CIDADE" in low and "BAIRRO" in low and "PRECO" in low:
            return index
    return 2


def _read_lines(path: Path):
    for encoding in ("utf-8-sig", "latin1"):
        try:
            with open(path, encoding=encoding, newline="") as handle:
                return handle.readlines(), encoding
        except UnicodeDecodeError:
            continue
    raise SourceValidationError(f"Não foi possível decodificar {path}")


def read_source_rows(path: Path) -> list[tuple[str, dict]]:
    """Lê um CSV de fonte e devolve [(id_bruto, linha), ...]."""
    lines, _encoding = _read_lines(path)
    reader = csv.DictReader(lines[header_index(lines):], delimiter=";")
    fieldnames = [(name or "").strip() for name in (reader.fieldnames or [])]
    reader.fieldnames = fieldnames
    id_col = find_column(fieldnames, "imovel") or find_column(fieldnames, "imóvel")
    if not id_col:
        raise SourceValidationError(
            f"Coluna de ID do imóvel não encontrada em {path}"
        )
    rows: list[tuple[str, dict]] = []
    for row in reader:
        cleaned = {
            (key or "").strip(): (value or "").strip()
            for key, value in row.items()
            if key
        }
        raw_id = cleaned.get(id_col, "").strip()
        if raw_id:
            rows.append((raw_id, cleaned))
    return rows


def read_generation_date(path: Path) -> str | None:
    import re

    try:
        with open(path, encoding="latin1") as handle:
            head = "".join(handle.readline() for _ in range(10))
    except OSError:
        return None
    match = re.search(
        r"Data de gera[cç][ãa]o:[;:\s]*([0-9]{2}/[0-9]{2}/[0-9]{4})", head, re.I
    )
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%d/%m/%Y").date().isoformat()
    except ValueError:
        return None


def stale_days(generation_date: str | None, today: date | None = None) -> int | None:
    """Dias entre a data de geração do CSV e hoje. ``None`` se desconhecida."""
    if not generation_date:
        return None
    try:
        generated = date.fromisoformat(str(generation_date)[:10])
    except ValueError:
        return None
    return max(0, ((today or date.today()) - generated).days)


def count_csv_rows(path: Path) -> int:
    try:
        return len(read_source_rows(path))
    except (OSError, SourceValidationError, csv.Error):
        return 0


def validate_source_csv(
    path: Path,
    source_id: str,
    *,
    min_rows: int = 1,
    min_rows_ratio: float = 0.0,
    previous_rows: int = 0,
    allow_source_drop: bool = False,
) -> SourceFile:
    """Valida existência, cabeçalho, quantidade e campos mínimos."""
    if not path.exists() or path.stat().st_size == 0:
        raise SourceValidationError(f"{source_id}: arquivo ausente ou vazio: {path}")
    rows = read_source_rows(path)
    total = len(rows)
    if total <= 0:
        raise SourceValidationError(f"{source_id}: nenhuma linha de imóvel em {path}")
    if total < min_rows and not allow_source_drop:
        raise SourceValidationError(
            f"{source_id}: apenas {total} imóveis (mínimo {min_rows}); "
            "provável bloqueio ou resposta incompleta"
        )
    if (
        previous_rows
        and not allow_source_drop
        and total < previous_rows * min_rows_ratio
    ):
        raise SourceValidationError(
            f"{source_id}: {total} imóveis, abaixo de "
            f"{min_rows_ratio:.0%} dos {previous_rows} anteriores; "
            "mantendo a versão anterior"
        )
    # Valida que o cabeçalho contém as colunas essenciais.
    with open(path, encoding="utf-8-sig" if source_id != "caixa" else "latin1", newline="") as handle:
        lines = handle.readlines()
    reader = csv.DictReader(lines[header_index(lines):], delimiter=";")
    fieldnames = [(name or "").strip() for name in (reader.fieldnames or [])]
    missing = [
        name
        for name in ("UF", "Cidade", "Preço", "Link de acesso")
        if not find_column(fieldnames, name)
    ]
    if missing:
        raise SourceValidationError(
            f"{source_id}: colunas obrigatórias ausentes: {', '.join(missing)}"
        )
    encoding = "utf-8-sig" if source_id != "caixa" else "latin1"
    return SourceFile(
        source_id=source_id,
        path=path,
        rows=total,
        generation_date=read_generation_date(path),
        encoding=encoding,
    )


def find_source_path(data_dir: Path, source_id: str) -> Path | None:
    """Compatibilidade: procura o CSV em ``raw/<fonte>`` e na raiz de dados."""
    exact = data_dir / "raw" / source_id / SOURCE_FILES[source_id]
    if exact.exists():
        return exact
    candidates = []
    for directory in (data_dir / "raw" / source_id, data_dir):
        candidates.extend(glob.glob(str(directory / f"*{SOURCE_FILES[source_id]}")))
    if not candidates:
        return None
    return Path(max(candidates, key=os.path.getmtime))


def find_caixa_csv(data_dir: Path) -> Path | None:
    exact = data_dir / "raw" / "caixa" / "Lista_imoveis_geral.csv"
    if exact.exists():
        return exact
    matches = glob.glob(str(data_dir / "raw" / "caixa" / "*Lista_imoveis_geral.csv"))
    if not matches:
        matches = glob.glob(str(data_dir / "*Lista_imoveis_geral.csv"))
    if not matches:
        return None
    return Path(max(matches, key=os.path.getmtime))


def load_market_values(path: Path) -> dict[str, float]:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            return {}
        id_col = None
        value_col = None
        for name in reader.fieldnames:
            key = norm(name)
            if id_col is None and ("ID" in key or "IMOVEL" in key):
                id_col = name
            if value_col is None and "VALOR" in key and (
                "VENDA" in key or "APROXIMADO" in key or "MARKET" in key or "PRECO" in key
            ):
                value_col = name
        if not id_col or not value_col:
            return {}
        values: dict[str, float] = {}
        for row in reader:
            item_id = str(row.get(id_col, "")).strip()
            value = parse_money(row.get(value_col))
            if item_id and value is not None:
                values[item_id] = value
        return values


def load_exclusions(path_ids: Path, path_locations: Path):
    ids: set[str] = set()
    if path_ids.exists():
        with open(path_ids, encoding="utf-8") as handle:
            ids = {line.strip() for line in handle if line.strip()}
    locations: list[dict] = []
    if path_locations.exists():
        with open(path_locations, encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                cidade = (row.get("Cidade") or row.get("cidade") or "").strip()
                bairro = (row.get("Bairro") or row.get("bairro") or "").strip()
                endereco = (
                    row.get("Endereço")
                    or row.get("Endereco")
                    or row.get("endereço")
                    or ""
                ).strip()
                if cidade or bairro or endereco:
                    locations.append(
                        {"cidade": cidade, "bairro": bairro, "endereco": endereco}
                    )
    return ids, locations


def source_label(source_id: str) -> str:
    return SOURCE_NAMES.get(source_id, source_id)


def ordered_sources() -> tuple[str, ...]:
    return SOURCE_ORDER
