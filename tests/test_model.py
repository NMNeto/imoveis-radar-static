from __future__ import annotations

from imoveis_radar.csv_sources import load_exclusions, load_market_values, read_source_rows
from imoveis_radar.geo import attach_coordinates, load_geocode_cache, seed_geo_points
from imoveis_radar.model import (
    build_exclusion_index,
    build_item,
    build_meta,
    filter_items,
    load_settings,
    normalize_market_values,
    recompute_item,
    sort_items,
)


def _config(paths):
    settings = load_settings(paths.config_file)
    market_values = normalize_market_values(load_market_values(paths.market_values_file))
    exclude_ids, exclude_locations = load_exclusions(
        paths.exclude_ids_file, paths.exclude_locations_file
    )
    return settings, market_values, exclude_ids, build_exclusion_index(exclude_locations)


def test_build_item_scoring_and_market_override(paths):
    settings, market_values, exclude_ids, index = _config(paths)
    rows = dict(read_source_rows(paths.raw_csv("caixa")))
    item = build_item("caixa", "1002", rows["1002"], "Lista_imoveis_geral.csv", settings, market_values, index, exclude_ids)
    assert item["id"] == "1002"
    assert item["ajustado"] is True
    assert item["valor_ajustado"] == 90000.0
    assert item["desconto"] == 11.11
    # (90000 - 5400 - 40000) - 80000 * 1.05
    assert item["lucro"] == -39400.0
    assert item["lucro_pct"] == -43.78


def test_build_item_bb_no_appraisal(paths):
    settings, market_values, exclude_ids, index = _config(paths)
    rows = dict(read_source_rows(paths.raw_csv("bb")))
    item = build_item("bb", "2001", rows["2001"], "imoveis_bb_geral.csv", settings, market_values, index, exclude_ids)
    assert item["id"] == "bb:2001"
    assert item["preco"] == 0
    assert item["preco_label"] == "Faça sua oferta"
    assert item["sem_avaliacao"] is True
    assert item["desconto"] is None


def test_exclusions_by_id_and_location(paths):
    settings, market_values, exclude_ids, index = _config(paths)
    rows = dict(read_source_rows(paths.raw_csv("caixa")))
    item = build_item("caixa", "1003", rows["1003"], "Lista_imoveis_geral.csv", settings, market_values, index, exclude_ids)
    assert item["excluido"] is True
    assert "excluído" in item["motivo_exclusao"].lower()


def test_recompute_and_coordinates(paths):
    settings, market_values, exclude_ids, index = _config(paths)
    rows = dict(read_source_rows(paths.raw_csv("caixa")))
    item = build_item("caixa", "1001", rows["1001"], "Lista_imoveis_geral.csv", settings, market_values, index, exclude_ids)
    cache = load_geocode_cache(paths.geocode_cache_file)
    seed_geo_points(cache, paths.seeds)
    attach_coordinates(item, cache)
    assert item["geo_precisao"] == "bairro"
    assert item["lat"] is not None
    updated = recompute_item(item, settings, market_values, index, exclude_ids, cache)
    assert updated["geo_precisao"] == "bairro"
    assert updated["valor_ajustado"] == item["valor_ajustado"]


def test_filter_and_sort(paths):
    settings, market_values, exclude_ids, index = _config(paths)
    cache = load_geocode_cache(paths.geocode_cache_file)
    seed_geo_points(cache, paths.seeds)
    items = []
    for source_id in ("caixa", "bb", "santander", "itau"):
        for raw_id, row in read_source_rows(paths.raw_csv(source_id)):
            item = build_item(source_id, raw_id, row, paths.raw_csv(source_id).name, settings, market_values, index, exclude_ids)
            attach_coordinates(item, cache)
            items.append(item)
    params = {"uf": "RJ", "aplicar_exclusoes": True, "lucro_min": -1_000_000}
    filtered = filter_items(items, params, True)
    assert [item["id"] for item in filtered] == ["1002"]
    filtered_all = filter_items(items, params, False)
    assert len(filtered_all) == 2
    sorted_items = sort_items(items, "preco_asc")
    assert sorted_items[0]["preco"] == 0


def test_meta_shape(paths):
    settings, market_values, exclude_ids, index = _config(paths)
    cache = load_geocode_cache(paths.geocode_cache_file)
    seed_geo_points(cache, paths.seeds)
    rows = dict(read_source_rows(paths.raw_csv("caixa")))
    item = build_item("caixa", "1001", rows["1001"], "Lista_imoveis_geral.csv", settings, market_values, index, exclude_ids)
    attach_coordinates(item, cache)
    meta = build_meta(
        [item], {"caixa": "Lista_imoveis_geral.csv"}, "2026-11-12",
        market_values, exclude_ids, [{"cidade": "NITEROI"}], cache, settings,
    )
    assert meta["total_properties"] == 1
    assert meta["ufs"] == ["SP"]
    assert meta["fontes"][0]["id"] == "caixa"
    assert meta["settings"]["taxa_venda"] == 0.06
