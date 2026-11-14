from __future__ import annotations

import pytest

from imoveis_radar.csv_sources import (
    SourceValidationError,
    load_exclusions,
    load_market_values,
    read_generation_date,
    read_source_rows,
    validate_source_csv,
)


def test_read_caixa_with_title_lines(paths):
    path = paths.raw_csv("caixa")
    rows = read_source_rows(path)
    assert len(rows) == 3
    assert rows[0][0] == "1001"
    assert read_generation_date(path) == "2026-11-12"


def test_read_collector_csv(paths):
    rows = read_source_rows(paths.raw_csv("bb"))
    assert rows[0][0] == "2001"
    assert rows[0][1]["Cidade"] == "CAMPINAS"


def test_validate_source_rows_and_drop_ratio(paths):
    info = validate_source_csv(paths.raw_csv("caixa"), "caixa", min_rows=1)
    assert info.rows == 3
    with pytest.raises(SourceValidationError):
        validate_source_csv(
            paths.raw_csv("caixa"),
            "caixa",
            min_rows=1,
            previous_rows=100,
            min_rows_ratio=0.5,
        )
    # A opção explícita permite assumir a queda.
    info = validate_source_csv(
        paths.raw_csv("caixa"),
        "caixa",
        min_rows=1,
        previous_rows=100,
        min_rows_ratio=0.5,
        allow_source_drop=True,
    )
    assert info.rows == 3


def test_load_config_files(paths):
    values = load_market_values(paths.market_values_file)
    assert values == {"1002": 90000.0}
    ids, locations = load_exclusions(paths.exclude_ids_file, paths.exclude_locations_file)
    assert "1003" in ids
    assert locations[0]["cidade"] == "NITEROI"
