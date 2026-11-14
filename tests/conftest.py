from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from imoveis_radar.config import Paths


CAIXA_HEADER = [
    "Nº do imóvel",
    "UF",
    "Cidade",
    "Bairro",
    "Endereço",
    "Preço",
    "Valor de avaliação",
    "Desconto",
    "Financiamento",
    "Descrição",
    "Modalidade de venda",
    "Link de acesso",
]
BB_HEADER = CAIXA_HEADER + ["Imagem"]

CAIXA_ROWS = [
    ["1001", "SP", "SAO PAULO", "CENTRO", "RUA A, 10", "100.000,00", "200.000,00", "50%", "Não", "Casa 1", "Venda Online", "https://caixa/1001"],
    ["1002", "RJ", "RIO DE JANEIRO", "COPACABANA", "RUA B, 20", "80.000,00", "100.000,00", "20%", "Sim", "Casa 2", "Venda Direta", "https://caixa/1002"],
    ["1003", "RJ", "NITEROI", "CENTRO", "RUA C, 30", "50.000,00", "100.000,00", "50%", "Não", "Casa 3", "Venda Online", "https://caixa/1003"],
]
BB_ROWS = [
    ["2001", "SP", "CAMPINAS", "CENTRO", "RUA D, 40", "0,00", "", "", "Sim", "Casa BB", "Venda direta", "https://bb/2001", "https://www.seuimovelbb.com.br/imagem/imovel/1.jpg"],
]
SANTANDER_ROWS = [
    ["02.00001", "SP", "SOROCABA", "ITANGUA", "RODOVIA X, KM 1", "100.000,00", "200.000,00", "50%", "", "Casa S", "Leilão", "https://santander/1", "https://shi.santander.com.br/1.jpg"],
]
ITAU_ROWS = [
    ["3001", "RS", "PORTO ALEGRE", "", "", "0,00", "", "", "", "Apartamento", "Leilão", "https://itau/3001", "https://cdn.frazaoleiloes.com.br/1.jpg"],
]


def _write_csv(path: Path, header, rows, *, encoding="utf-8-sig", title=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding=encoding, newline="") as handle:
        if title:
            handle.write(" Lista de Imóveis da Caixa;;Data de geração:;12/11/2026;;;;;;;\n\n")
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(header)
        writer.writerows(rows)


@pytest.fixture()
def paths(tmp_path: Path) -> Paths:
    root = tmp_path / "projeto"
    data = root / "data"
    public = root / "public"
    p = Paths(root=root, data=data, public=public)
    p.ensure_dirs()
    _write_csv(p.raw / "caixa" / "Lista_imoveis_geral.csv", CAIXA_HEADER, CAIXA_ROWS, encoding="latin1", title=True)
    _write_csv(p.raw / "bb" / "imoveis_bb_geral.csv", BB_HEADER, BB_ROWS)
    _write_csv(p.raw / "santander" / "santander_imoveis_geral.csv", BB_HEADER, SANTANDER_ROWS)
    _write_csv(p.raw / "itau" / "itau_imoveis_geral.csv", BB_HEADER, ITAU_ROWS)

    (p.config / "settings.json").write_text(
        json.dumps(
            {
                "taxa_venda": 0.06,
                "custo_fixo": 40000.0,
                "custo_fixo_modo": "fixo",
                "fator_preco": 1.05,
            }
        ),
        encoding="utf-8",
    )
    (p.config / "exclude_ids.txt").write_text("1003\n", encoding="utf-8")
    (p.config / "exclude_locations.csv").write_text(
        "Cidade,Bairro,Endereço\nNITEROI,all,all\n", encoding="utf-8"
    )
    (p.config / "market_value.csv").write_text(
        "ID,Valor de Venda Aproximado\n1002,90000.00\n", encoding="utf-8"
    )
    (p.seeds / "estados.csv").write_text(
        "uf,latitude,longitude\nSP,-23.5,-46.6\nRJ,-22.9,-43.2\nRS,-30.0,-51.2\n",
        encoding="utf-8",
    )
    (p.seeds / "municipios.csv").write_text(
        "uf,cidade,latitude,longitude\n"
        "SP,SAO PAULO,-23.55,-46.63\n"
        "SP,CAMPINAS,-22.9,-47.06\n"
        "SP,SOROCABA,-23.5,-47.45\n"
        "RJ,RIO DE JANEIRO,-22.9,-43.2\n"
        "RJ,NITEROI,-22.88,-43.1\n"
        "RS,PORTO ALEGRE,-30.03,-51.23\n",
        encoding="utf-8",
    )
    (p.geo / "geocode_cache.json").write_text(
        json.dumps(
            {
                "version": 1,
                "updated": "2026-01-01T00:00:00",
                "points": {
                    "SP|SAO PAULO|CENTRO": {
                        "lat": -23.55,
                        "lng": -46.63,
                        "precisao": "bairro",
                        "fonte": "nominatim",
                    },
                    "RJ|RIO DE JANEIRO|COPACABANA": {
                        "lat": -22.97,
                        "lng": -43.19,
                        "precisao": "bairro",
                        "fonte": "nominatim",
                    },
                },
                "misses": {},
            }
        ),
        encoding="utf-8",
    )
    return p
