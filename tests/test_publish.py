from __future__ import annotations

import glob
import json

from imoveis_radar.config import Paths
from imoveis_radar.csv_sources import load_exclusions, load_market_values, read_source_rows
from imoveis_radar.geo import attach_coordinates, load_geocode_cache, seed_geo_points
from imoveis_radar.model import (
    apply_history_timestamps,
    build_exclusion_index,
    build_item,
    build_meta,
    build_stats,
    config_public_payload,
    load_settings,
    normalize_market_values,
)
from imoveis_radar.publish import (
    data_hash,
    load_previous_items,
    publish,
    validate_public_dataset,
)


def make_items(paths: Paths):
    settings = load_settings(paths.config_file)
    market_values = normalize_market_values(load_market_values(paths.market_values_file))
    exclude_ids, exclude_locations = load_exclusions(
        paths.exclude_ids_file, paths.exclude_locations_file
    )
    index = build_exclusion_index(exclude_locations)
    cache = load_geocode_cache(paths.geocode_cache_file)
    seed_geo_points(cache, paths.seeds)
    items = []
    for source_id in ("caixa", "bb", "santander", "itau"):
        for raw_id, row in read_source_rows(paths.raw_csv(source_id)):
            item = build_item(
                source_id,
                raw_id,
                row,
                paths.raw_csv(source_id).name,
                settings,
                market_values,
                index,
                exclude_ids,
            )
            attach_coordinates(item, cache)
            items.append(item)
    return items, settings, market_values, exclude_ids, exclude_locations, cache, index


def make_bundle(paths: Paths, items):
    now = "2026-11-14T00:00:00"
    items, new_ids, changed_ids = apply_history_timestamps(items, [], now)
    meta = build_meta(
        items,
        {"caixa": "Lista_imoveis_geral.csv"},
        "2026-11-12",
        {},
        set(),
        [],
        {"points": {}, "misses": {}},
        {},
    )
    digest = data_hash(items)
    stats = build_stats(items, [], new_ids, changed_ids, [], {"enabled": False}, {}, digest, now)
    last_update = {
        "data_atualizacao": now,
        "ultima_execucao": now,
        "total": len(items),
        "novos": len(new_ids),
        "alterados": len(changed_ids),
        "removidos": 0,
        "sha256": digest,
        "fontes": {},
        "geocodificacao": {"enabled": False},
    }
    config = config_public_payload(
        {
            "settings": {},
            "market_values": {},
            "exclude_ids": set(),
            "exclude_locations": [],
        }
    )
    return items, meta, stats, last_update, config


def test_publish_and_idempotency(paths):
    items, *_ = make_items(paths)
    bundle = make_bundle(paths, items)
    result = publish(paths, *bundle, chunk_size=100)
    assert result.changed is True
    assert result.validation_errors == []
    manifest = json.loads((paths.public_data / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["total"] == len(items)
    assert len(manifest["chunks"]) == 1
    assert (paths.public_data / "meta.json").exists()
    assert (paths.public_data / "estatisticas.json").exists()
    assert (paths.public_data / "config.json").exists()
    assert (paths.public_data / "busca_imoveis.csv").exists()
    report = validate_public_dataset(paths)
    assert report["ok"], report["errors"]
    assert report["total"] == len(items)

    previous = load_previous_items(paths)
    assert len(previous) == len(items)

    second = publish(paths, *bundle, chunk_size=100)
    assert second.changed is False
    assert second.files_written == []


def test_publish_removes_old_chunks_and_versions_names(paths):
    items, *_ = make_items(paths)
    bundle = make_bundle(paths, items)
    first = publish(paths, *bundle, chunk_size=100)
    old_chunks = set(glob.glob(str(paths.public_data / "imoveis-*.json")))
    assert old_chunks
    items[0]["preco"] = float(items[0]["preco"]) + 1
    bundle = make_bundle(paths, items)
    second = publish(paths, *bundle, chunk_size=100, force=True)
    assert second.changed is True
    assert first.chunks != second.chunks
    keep = {str(paths.public_data / name) for name in second.chunks}
    remaining = set(glob.glob(str(paths.public_data / "imoveis-*.json")))
    assert remaining == keep


def test_dry_run_does_not_touch_public(paths):
    items, *_ = make_items(paths)
    bundle = make_bundle(paths, items)
    result = publish(paths, *bundle, chunk_size=100, dry_run=True)
    assert result.changed is True
    assert not (paths.public_data / "manifest.json").exists()


def test_validate_rejects_invalid_item(paths):
    item = {"id": "", "fonte": "caixa"}
    result = publish(
        paths,
        [item],
        {"fontes": []},
        {},
        {"data_atualizacao": "x"},
        {},
        chunk_size=100,
    )
    assert result.changed is False
    assert result.validation_errors
