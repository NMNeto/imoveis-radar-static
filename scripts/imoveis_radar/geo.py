"""Cache de geocodificação, sementes de estados/cidades e coordenadas."""
from __future__ import annotations

import csv
import hashlib
import json
import logging
import math
import os
from datetime import datetime
from pathlib import Path

from . import geocode_client
from .config import Paths, RunOptions
from .safety import atomic_write_json
from .text import norm

GEOCODE_CACHE_FILE = "geocode_cache.json"
GEO_SEED_CITIES_FILE = "municipios.csv"
GEO_SEED_STATES_FILE = "estados.csv"
MISS_TTL_DAYS = 30

logger = logging.getLogger(__name__)


def _empty_cache() -> dict:
    return {"version": 1, "updated": None, "points": {}, "misses": {}}


def load_geocode_cache(path: Path) -> dict:
    if not path.exists():
        return _empty_cache()
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return _empty_cache()
    if isinstance(data, dict) and "points" in data:
        data.setdefault("version", 1)
        data.setdefault("misses", {})
        return data
    if isinstance(data, dict):
        return {"version": 1, "updated": None, "points": data, "misses": {}}
    return _empty_cache()


def save_geocode_cache(path: Path, cache: dict, root: Path, dry_run: bool = False) -> bool:
    cache["updated"] = datetime.now().isoformat(timespec="seconds")
    if dry_run:
        return False
    return atomic_write_json(path, cache, root)


def _parse_coord(value):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _seed_file(name: str, seeds_dir: Path) -> Path | None:
    candidate = seeds_dir / name
    if candidate.exists():
        return candidate
    return None


def _seed_point(points: dict, key: str, lat: float, lng: float, precision: str, source: str) -> bool:
    existing = points.get(key)
    if existing and existing.get("fonte") not in (None, "municipios", "estados"):
        return False
    point = {"lat": lat, "lng": lng, "precisao": precision, "fonte": source}
    if existing == point:
        return False
    points[key] = point
    return True


def seed_geo_points(cache: dict, seeds_dir: Path) -> int:
    """Semeia centroides de estados e cidades a partir dos CSVs empacotados."""
    points = cache.setdefault("points", {})
    added = 0

    states_path = _seed_file(GEO_SEED_STATES_FILE, seeds_dir)
    if states_path:
        with open(states_path, encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                uf = (row.get("uf") or "").strip()
                lat = _parse_coord(row.get("latitude"))
                lng = _parse_coord(row.get("longitude"))
                if not uf or lat is None or lng is None:
                    continue
                key = geocode_key(uf, "", "")
                if _seed_point(points, key, lat, lng, "estado", "estados"):
                    added += 1

    cities_path = _seed_file(GEO_SEED_CITIES_FILE, seeds_dir)
    if cities_path:
        with open(cities_path, encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                uf = (row.get("uf") or "").strip()
                cidade = (row.get("cidade") or "").strip()
                lat = _parse_coord(row.get("latitude"))
                lng = _parse_coord(row.get("longitude"))
                if not uf or not cidade or lat is None or lng is None:
                    continue
                key = geocode_key(uf, cidade, "")
                if _seed_point(points, key, lat, lng, "cidade", "municipios"):
                    added += 1

    return added


def geocode_key(uf, cidade, bairro="") -> str:
    return f"{norm(uf)}|{norm(cidade)}|{norm(bairro)}"


def is_geocode_miss(cache: dict, key: str, max_age_days: int = MISS_TTL_DAYS) -> bool:
    miss = cache.get("misses", {}).get(key)
    if not miss:
        return False
    updated = miss.get("updated")
    if not updated:
        return True
    try:
        age = datetime.now() - datetime.fromisoformat(updated)
    except ValueError:
        return True
    return age.total_seconds() < max_age_days * 86400


def mark_geocode_miss(cache: dict, key: str) -> None:
    cache.setdefault("misses", {})[key] = {
        "status": "not_found",
        "updated": datetime.now().isoformat(timespec="seconds"),
    }


def _jitter(seed: str, lat: float, lng: float, radius: float):
    digest = hashlib.md5(seed.encode("utf-8")).hexdigest()
    angle = int(digest[:8], 16) / 0xFFFFFFFF * 2 * math.pi
    distance = math.sqrt(int(digest[8:16], 16) / 0xFFFFFFFF) * radius
    dlat = distance * math.cos(angle)
    dlng = distance * math.sin(angle) / max(math.cos(math.radians(lat)), 0.2)
    return round(lat + dlat, 6), round(lng + dlng, 6)


def attach_coordinates(item: dict, cache: dict) -> None:
    """Anexa coordenadas com precisão bairro → cidade → estado."""
    points = cache.get("points", {})
    candidates = (
        (geocode_key(item["uf"], item["cidade"], item["bairro"]), "bairro", 0.006),
        (geocode_key(item["uf"], item["cidade"], ""), "cidade", 0.03),
        (geocode_key(item["uf"], "", ""), "estado", 0.15),
    )
    for key, precision, radius in candidates:
        point = points.get(key)
        if not point or point.get("lat") is None or point.get("lng") is None:
            continue
        lat, lng = _jitter(item["id"], float(point["lat"]), float(point["lng"]), radius)
        item["lat"] = lat
        item["lng"] = lng
        item["geo_precisao"] = precision
        item["geo_fonte"] = point.get("fonte")
        return
    item["lat"] = None
    item["lng"] = None
    item["geo_precisao"] = None
    item["geo_fonte"] = None


def missing_pairs(items: list[dict], cache: dict, max_items: int = 0) -> list[dict]:
    """Locais que ainda não têm ponto e não estão em quarentena de erro."""
    points = cache.get("points", {})
    seen: set[str] = set()
    pairs: list[dict] = []

    def add(uf, cidade, bairro, precision):
        key = geocode_key(uf, cidade, bairro)
        if not key.strip("|") or key in points or key in seen:
            return
        if is_geocode_miss(cache, key):
            return
        seen.add(key)
        pairs.append(
            {
                "uf": uf,
                "cidade": cidade,
                "bairro": bairro,
                "precisao": precision,
                "key": key,
            }
        )

    for item in items:
        if item.get("geo_precisao") == "bairro":
            continue
        if item.get("bairro"):
            add(item.get("uf", ""), item.get("cidade", ""), item.get("bairro", ""), "bairro")
        if item.get("geo_precisao") in (None, "estado"):
            add(item.get("uf", ""), item.get("cidade", ""), "", "cidade")

    if max_items and max_items > 0:
        pairs = pairs[:max_items]
    return pairs


def geocode_missing(
    items: list[dict],
    cache: dict,
    paths: Paths,
    options: RunOptions,
) -> dict:
    """Geocodifica bairros/cidades ausentes respeitando o limite de taxa."""
    if not options.geocode:
        return {"enabled": False, "requested": 0, "resolved": 0, "misses": 0, "errors": 0}
    pairs = missing_pairs(items, cache, options.geocode_max)
    stats = {
        "enabled": True,
        "requested": len(pairs),
        "resolved": 0,
        "misses": 0,
        "errors": 0,
        "rate_limited": False,
    }
    if not pairs:
        return stats

    logger.info("Geocodificando %s localidade(s) nova(s)…", len(pairs))
    points = cache.setdefault("points", {})
    for index, pair in enumerate(pairs, start=1):
        query = (
            f"{pair['bairro']}, {pair['cidade']}, {pair['uf']}, Brasil"
            if pair.get("bairro")
            else f"{pair['cidade']}, {pair['uf']}, Brasil"
        )
        try:
            result = geocode_client.search(
                query, timeout=options.http_timeout, city=pair.get("cidade")
            )
        except geocode_client.RateLimitError as exc:
            logger.warning("Geocodificação interrompida: %s", exc)
            stats["rate_limited"] = True
            break
        except Exception as exc:  # rede instável não vira "não encontrado"
            stats["errors"] += 1
            logger.warning("Falha ao geocodificar %s: %s", query, exc)
            continue

        if result:
            points[pair["key"]] = {
                "lat": result["lat"],
                "lng": result["lng"],
                "precisao": pair["precisao"],
                "fonte": result.get("fonte", "nominatim"),
            }
            stats["resolved"] += 1
        else:
            mark_geocode_miss(cache, pair["key"])
            stats["misses"] += 1

        if index % 5 == 0:
            save_geocode_cache(paths.geocode_cache_file, cache, paths.root, options.dry_run)
            logger.info("Geocodificação: %s/%s", index, len(pairs))

    save_geocode_cache(paths.geocode_cache_file, cache, paths.root, options.dry_run)
    logger.info(
        "Geocodificação concluída: %s resolvidos, %s não encontrados, %s erros",
        stats["resolved"],
        stats["misses"],
        stats["errors"],
    )
    return stats
