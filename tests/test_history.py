from __future__ import annotations

from datetime import datetime, timedelta

from imoveis_radar.csv_sources import load_exclusions, load_market_values, read_source_rows
from imoveis_radar.model import (
    apply_history_timestamps,
    build_exclusion_index,
    build_item,
    find_removed,
    load_settings,
    normalize_market_values,
)
from imoveis_radar.publish import update_history


def make_items(paths):
    settings = load_settings(paths.config_file)
    market_values = normalize_market_values(load_market_values(paths.market_values_file))
    exclude_ids, exclude_locations = load_exclusions(
        paths.exclude_ids_file, paths.exclude_locations_file
    )
    index = build_exclusion_index(exclude_locations)
    items = []
    for source_id in ("caixa", "bb", "santander", "itau"):
        for raw_id, row in read_source_rows(paths.raw_csv(source_id)):
            items.append(
                build_item(
                    source_id,
                    raw_id,
                    row,
                    paths.raw_csv(source_id).name,
                    settings,
                    market_values,
                    index,
                    exclude_ids,
                )
            )
    return items


def test_history_timestamps_and_changes(paths):
    items = make_items(paths)
    now = "2026-11-14T00:00:00"
    stamped, new_ids, changed_ids = apply_history_timestamps(items, [], now)
    assert len(new_ids) == len(stamped)
    assert changed_ids == []
    assert all(item["primeira_visao"] == now for item in stamped)

    again, new_ids, changed_ids = apply_history_timestamps(stamped, stamped, now)
    assert new_ids == []
    assert changed_ids == []
    assert all(item["primeira_visao"] == now for item in again)

    previous = [dict(item) for item in again]
    stamped[0]["preco"] = float(stamped[0]["preco"]) + 1
    _, new_ids, changed_ids = apply_history_timestamps(stamped, previous, now)
    assert new_ids == []
    assert changed_ids == [stamped[0]["id"]]


def test_find_removed_only_for_successful_sources(paths):
    previous = make_items(paths)
    current_ids = {item["id"] for item in previous if item["fonte"] != "caixa"}
    removed = find_removed(previous, current_ids, {"caixa"})
    assert removed
    assert all(item["fonte"] == "caixa" for item in removed)
    assert find_removed(previous, current_ids, {"bb"}) == []
    assert find_removed(previous, current_ids, set()) == []


def test_update_history_add_remove_and_prune(paths):
    items = make_items(paths)
    item = items[0]
    old = (datetime.now() - timedelta(days=400)).isoformat(timespec="seconds")
    history = {
        "version": 1,
        "updated": None,
        "items": {"antigo": {"removido_em": old, "item": {"id": "antigo"}}},
    }
    changed = update_history(history, [item], set(), "2026-11-14T00:00:00", 365)
    assert changed is True
    assert item["id"] in history["items"]
    assert "antigo" not in history["items"]

    changed = update_history(history, [], {item["id"]}, "2026-11-14T00:00:00", 365)
    assert changed is True
    assert item["id"] not in history["items"]
