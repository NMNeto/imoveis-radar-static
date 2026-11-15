from __future__ import annotations

from imoveis_radar.config import RunOptions
from imoveis_radar.geo import (
    attach_coordinates,
    geocode_key,
    geocode_missing,
    is_geocode_miss,
    is_useful_street,
    item_street_key,
    load_geocode_cache,
    mark_geocode_miss,
    missing_pairs,
    seed_geo_points,
    set_bairro_point,
)


def test_seed_and_key(paths):
    cache = load_geocode_cache(paths.geocode_cache_file)
    added = seed_geo_points(cache, paths.seeds)
    assert added > 0
    assert geocode_key("São Paulo", "São Paulo", "Centro") == "SAO PAULO|SAO PAULO|CENTRO"
    assert "SP||" in cache["points"]
    assert "SP|SAO PAULO|" in cache["points"]


def test_attach_coordinates_fallback(paths):
    cache = load_geocode_cache(paths.geocode_cache_file)
    seed_geo_points(cache, paths.seeds)
    item = {
        "id": "1",
        "uf": "SP",
        "cidade": "SAO PAULO",
        "bairro": "CENTRO",
    }
    attach_coordinates(item, cache)
    assert item["geo_precisao"] == "bairro"
    first = (item["lat"], item["lng"])
    attach_coordinates(item, cache)
    assert (item["lat"], item["lng"]) == first

    city_only = {"id": "2", "uf": "SP", "cidade": "CAMPINAS", "bairro": "NAO EXISTE"}
    attach_coordinates(city_only, cache)
    assert city_only["geo_precisao"] == "cidade"

    state_only = {"id": "3", "uf": "RS", "cidade": "CIDADE NOVA", "bairro": ""}
    attach_coordinates(state_only, cache)
    assert state_only["geo_precisao"] == "estado"


def test_missing_pairs_and_miss(paths):
    cache = load_geocode_cache(paths.geocode_cache_file)
    seed_geo_points(cache, paths.seeds)
    item = {"id": "1", "uf": "SP", "cidade": "SAO PAULO", "bairro": "BAIRRO NOVO"}
    pairs = missing_pairs([item], cache)
    assert any(pair["bairro"] == "BAIRRO NOVO" for pair in pairs)
    key = geocode_key("SP", "SAO PAULO", "BAIRRO NOVO")
    mark_geocode_miss(cache, key)
    assert is_geocode_miss(cache, key)
    assert not any(pair["key"] == key for pair in missing_pairs([item], cache))


def test_geocode_disabled_does_not_network(paths):
    cache = load_geocode_cache(paths.geocode_cache_file)
    options = RunOptions(geocode=False)
    stats = geocode_missing([], cache, paths, options)
    assert stats["enabled"] is False
    assert stats["requested"] == 0


def test_item_street_key_agrupa_variacoes_de_quadra_e_lote():
    base = {
        "uf": "AC",
        "cidade": "CRUZEIRO DO SUL",
        "bairro": "COHAB",
    }
    enderecos = [
        "RUA DO PURUS, N. S/N, QUARTEIRAO 272 LOTE 11",
        "RUA DO PURUS, N. S/N, QUARTEIRAO 272 LOTE 12",
        "RUA DO PURUS, N. S/N, QUARTEIRAO 272, LOTE 10",
    ]
    chaves = {
        item_street_key({**base, "endereco": endereco})
        for endereco in enderecos
    }
    assert chaves == {"AC|CRUZEIRO DO SUL|RUA DO PURUS"}


def test_is_useful_street():
    assert is_useful_street("RUA B")
    assert is_useful_street("RUA 8")
    assert is_useful_street("CSB 9")
    assert not is_useful_street("")
    assert not is_useful_street("RUA")
    assert not is_useful_street("LOTE")
    assert not is_useful_street("SEM DENOMINACAO")
    assert not is_useful_street("QUADRA QUADRA")


def test_cache_versao_1_ganha_secao_ruas(tmp_path):
    path = tmp_path / "cache.json"
    path.write_text(
        '{"version": 1, "updated": null, "points": {"SP|SAO PAULO|":'
        ' {"lat": -23.5, "lng": -46.6, "precisao": "cidade"}}, "misses": {}}',
        encoding="utf-8",
    )
    cache = load_geocode_cache(path)
    assert cache["ruas"] == {}
    assert cache["version"] == 2
    assert "SP|SAO PAULO|" in cache["points"]
    assert cache["misses"] == {}


def test_attach_coordinates_prefere_rua(paths):
    cache = load_geocode_cache(paths.geocode_cache_file)
    seed_geo_points(cache, paths.seeds)
    cache["ruas"]["SP|SAO PAULO|RUA A"] = {
        "status": "ok",
        "lat": -23.56,
        "lng": -46.64,
        "precisao": "rua",
        "fonte": "nominatim",
    }
    item = {
        "id": "1",
        "uf": "SP",
        "cidade": "SAO PAULO",
        "bairro": "CENTRO",
        "endereco": "RUA A, 10",
    }
    attach_coordinates(item, cache)
    assert item["geo_precisao"] == "rua"
    first = (item["lat"], item["lng"])
    attach_coordinates(item, cache)
    assert (item["lat"], item["lng"]) == first


def test_attach_coordinates_ignora_rua_de_baixa_precisao(paths):
    cache = load_geocode_cache(paths.geocode_cache_file)
    seed_geo_points(cache, paths.seeds)
    cache["ruas"]["SP|SAO PAULO|RUA A"] = {
        "status": "ok",
        "lat": -23.0,
        "lng": -46.0,
        "precisao": "bairro",
        "fonte": "nominatim",
    }
    item = {
        "id": "1",
        "uf": "SP",
        "cidade": "SAO PAULO",
        "bairro": "CENTRO",
        "endereco": "RUA A, 10",
    }
    attach_coordinates(item, cache)
    assert item["geo_precisao"] == "bairro"


def test_set_bairro_point_nao_rebaixa_precisao():
    cache = {"points": {}, "misses": {}, "ruas": {}}
    key = geocode_key("SP", "SAO PAULO", "CENTRO")
    assert set_bairro_point(cache, "SP", "SAO PAULO", "CENTRO", -23.5, -46.6)
    assert cache["points"][key]["precisao"] == "bairro"
    assert not set_bairro_point(cache, "SP", "SAO PAULO", "CENTRO", -23.4, -46.5)
    assert cache["points"][key]["lat"] == -23.5

    city_key = geocode_key("SP", "CAMPINAS", "CENTRO")
    cache["points"][city_key] = {
        "lat": -22.9,
        "lng": -47.06,
        "precisao": "cidade",
        "fonte": "municipios",
    }
    assert set_bairro_point(cache, "SP", "CAMPINAS", "CENTRO", -22.91, -47.07)
    assert cache["points"][city_key]["precisao"] == "bairro"


def test_missing_pairs_ignora_imoveis_com_rua(paths):
    cache = load_geocode_cache(paths.geocode_cache_file)
    item = {
        "id": "1",
        "uf": "SP",
        "cidade": "SAO PAULO",
        "bairro": "BAIRRO NOVO",
        "geo_precisao": "rua",
    }
    assert missing_pairs([item], cache) == []
