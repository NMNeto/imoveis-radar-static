from __future__ import annotations

from imoveis_radar.config import RunOptions
from imoveis_radar.geo import (
    attach_coordinates,
    geocode_key,
    geocode_missing,
    is_geocode_miss,
    load_geocode_cache,
    mark_geocode_miss,
    missing_pairs,
    seed_geo_points,
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
