from __future__ import annotations

import json

from importar_config import apply_config


def test_apply_config_writes_repository_files(paths):
    payload = {
        "settings": {
            "taxa_venda": 0.07,
            "custo_fixo": 5,
            "custo_fixo_modo": "percentual",
            "fator_preco": 1.1,
        },
        "exclude_ids": ["10", "2"],
        "exclude_locations": [
            {"cidade": "RIO DE JANEIRO", "bairro": "all", "endereco": "all"}
        ],
        "market_values": {"1001": 250000},
    }
    result = apply_config(paths, payload)
    assert result["ok"] is True
    settings = json.loads(paths.config_file.read_text(encoding="utf-8"))
    assert settings["taxa_venda"] == 0.07
    assert settings["custo_fixo_modo"] == "percentual"
    assert paths.exclude_ids_file.read_text(encoding="utf-8") == "2\n10\n"
    assert "RIO DE JANEIRO,all,all" in paths.exclude_locations_file.read_text(encoding="utf-8")
    assert "1001,250000.00" in paths.market_values_file.read_text(encoding="utf-8")


def test_apply_config_dry_run(paths):
    original = paths.config_file.read_text(encoding="utf-8")
    result = apply_config(
        paths,
        {
            "settings": {"taxa_venda": 0.5},
            "exclude_ids": [],
            "exclude_locations": [],
            "market_values": {},
        },
        dry_run=True,
    )
    assert result["dry_run"] is True
    assert paths.config_file.read_text(encoding="utf-8") == original
