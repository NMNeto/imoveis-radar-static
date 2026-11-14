from __future__ import annotations

from imoveis_radar.locations import canonicalize_locations, choose_display_name
from collections import Counter


def test_choose_display_prefers_accented_variant():
    counter = Counter({"Niteroi": 10, "Niterói": 8, "NITEROI": 2})
    assert choose_display_name(counter) == "Niterói"


def test_choose_display_prefers_mixed_case_without_accent():
    counter = Counter({"CENTRO": 20, "Centro": 6})
    assert choose_display_name(counter) == "Centro"


def test_choose_display_accepts_rare_accented_variant():
    # Caso real: "NITEROI" aparece muito, mas "Niterói" é a grafia correta.
    counter = Counter({"NITEROI": 89, "Niterói": 2})
    assert choose_display_name(counter) == "Niterói"


def test_canonicalize_cities_and_bairros():
    items = [
        {"uf": "RJ", "cidade": "Niteroi", "bairro": "CENTRO"},
        {"uf": "RJ", "cidade": "Niterói", "bairro": "Centro"},
        {"uf": "RJ", "cidade": "NITEROI", "bairro": "CENTRO"},
        {"uf": "SP", "cidade": "São Paulo", "bairro": "Sé"},
        {"uf": "SP", "cidade": "SAO PAULO", "bairro": "SE"},
    ]
    result, stats = canonicalize_locations(items)
    assert {item["cidade"] for item in result if item["uf"] == "RJ"} == {"Niterói"}
    assert {item["bairro"] for item in result if item["uf"] == "RJ"} == {"Centro"}
    assert {item["cidade"] for item in result if item["uf"] == "SP"} == {"São Paulo"}
    assert stats["cidades"] == 2
    assert stats["variantes_cidade"] >= 2

    # Idempotente
    again, stats2 = canonicalize_locations(result)
    assert stats2["itens_cidade_alterados"] == 0
    assert stats2["itens_bairro_alterados"] == 0
    assert [item["cidade"] for item in again] == [item["cidade"] for item in result]
