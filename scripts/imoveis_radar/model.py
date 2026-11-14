"""Construção dos itens, pontuação, exclusões, metadados e validação.

Este módulo é uma porta fiel de ``web/caixa_data.py`` do projeto original,
com os mesmos nomes de campos e as mesmas fórmulas.  A diferença é que os
dados são lidos de ``data/raw/`` e publicados em JSON estático.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import os
import statistics
from datetime import datetime
from pathlib import Path

from .config import SOURCE_NAMES, SOURCE_ORDER
from .csv_sources import load_exclusions, load_market_values
from .geo import attach_coordinates
from .text import br_number, field_text, norm, parse_float, parse_money

logger = logging.getLogger(__name__)

TAXA_VENDA = 0.06
CUSTO_FIXO = 40000
FATOR_PRECO = 1.05

DEFAULT_SETTINGS = {
    "taxa_venda": TAXA_VENDA,
    "custo_fixo": float(CUSTO_FIXO),
    "custo_fixo_modo": "fixo",
    "fator_preco": FATOR_PRECO,
}

DEFAULT_FILTERS = {
    "uf": "all",
    "cidade": "all",
    "bairro": "all",
    "preco_min": 0,
    "preco_max": 0,
    "desconto_min": 0,
    "lucro_min": 0,
    "financiamento": "all",
    "modalidade": "all",
    "fonte": "all",
    "q": "",
    "bbox": "",
    "aplicar_exclusoes": True,
    "sort": "desconto_desc",
}

REQUIRED_FIELDS = ("id", "id_fonte", "fonte", "uf", "cidade", "modalidade")
TIMESTAMP_FIELDS = ("primeira_visao", "atualizado_em")


# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------

def normalize_settings(raw) -> dict:
    settings = dict(DEFAULT_SETTINGS)
    if not isinstance(raw, dict):
        return settings

    taxa = parse_float(raw.get("taxa_venda"))
    if taxa is not None and taxa >= 0:
        if taxa > 1:
            taxa = taxa / 100
        settings["taxa_venda"] = min(taxa, 1.0)

    mode = norm(raw.get("custo_fixo_modo") or raw.get("modo") or "fixo")
    settings["custo_fixo_modo"] = (
        "percentual" if ("PERC" in mode or "PORC" in mode) else "fixo"
    )

    custo = parse_float(raw.get("custo_fixo"))
    if custo is not None and custo >= 0:
        settings["custo_fixo"] = (
            min(custo, 100.0)
            if settings["custo_fixo_modo"] == "percentual"
            else custo
        )

    fator = parse_float(raw.get("fator_preco"))
    if fator is not None and fator >= 0:
        if 0 < fator < 1:
            fator = 1 + fator
        settings["fator_preco"] = fator

    return settings


def load_settings(path: Path) -> dict:
    if not path.exists():
        return dict(DEFAULT_SETTINGS)
    try:
        with open(path, encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, ValueError):
        logger.warning("settings.json inválido; usando padrões")
        return dict(DEFAULT_SETTINGS)
    return normalize_settings(raw)


def fixed_cost_for(settings: dict, valor_ajustado: float) -> float:
    custo = float(settings.get("custo_fixo") or 0)
    if settings.get("custo_fixo_modo") == "percentual":
        return valor_ajustado * custo / 100
    return custo


def normalize_market_values(market_values) -> dict[str, float]:
    values = {}
    for item_id, value in (market_values or {}).items():
        parsed = parse_money(value)
        if parsed is not None:
            values[str(item_id).strip()] = parsed
    return values


# ---------------------------------------------------------------------------
# Exclusões
# ---------------------------------------------------------------------------

def build_exclusion_index(exclude_locations) -> dict:
    index: dict[str, list] = {}
    for location in exclude_locations:
        prepared = {
            "cidade_norm": norm(location.get("cidade", "")),
            "bairro_norm": norm(location.get("bairro", "")),
            "endereco_norm": norm(location.get("endereco", "")),
            "raw": location,
        }
        index.setdefault(prepared["cidade_norm"], []).append(prepared)
    return index


def matches_location(item, location, item_norm=None) -> bool:
    cidade = location.get("cidade_norm")
    if cidade is None:
        cidade = norm(location.get("cidade", ""))
    bairro = location.get("bairro_norm")
    if bairro is None:
        bairro = norm(location.get("bairro", ""))
    endereco = location.get("endereco_norm")
    if endereco is None:
        endereco = norm(location.get("endereco", ""))
    if not cidade:
        return False
    if item_norm is None:
        item_cidade = norm(item.get("cidade", ""))
        item_bairro = norm(item.get("bairro", ""))
        item_endereco = norm(item.get("endereco", ""))
    else:
        item_cidade, item_bairro, item_endereco = item_norm
    if item_cidade != cidade:
        return False
    if bairro == "ALL" and endereco == "ALL":
        return True
    if bairro == "ALL":
        prefix = endereco[:-1] if endereco.endswith("*") else endereco
        return item_endereco.startswith(prefix)
    if item_bairro != bairro:
        return False
    if endereco == "ALL":
        return True
    prefix = endereco[:-1] if endereco.endswith("*") else endereco
    return item_endereco.startswith(prefix)


def exclusion_reason(item, exclude_ids, exclude_locations):
    if item.get("id_fonte") in exclude_ids or item["id"] in exclude_ids:
        return "ID excluído"
    item_norm = (
        norm(item.get("cidade", "")),
        norm(item.get("bairro", "")),
        norm(item.get("endereco", "")),
    )
    if isinstance(exclude_locations, dict):
        candidates = exclude_locations.get(item_norm[0], ())
    else:
        candidates = exclude_locations
    for location in candidates:
        if matches_location(item, location, item_norm):
            raw = location.get("raw", location)
            parts = [
                raw.get("cidade", ""),
                raw.get("bairro", ""),
                raw.get("endereco", ""),
            ]
            label = " / ".join(part for part in parts if part)
            return f"Local excluído: {label}"
    return None


# ---------------------------------------------------------------------------
# Itens
# ---------------------------------------------------------------------------

def image_url(item_id: str, source_id: str = "caixa") -> str | None:
    if source_id != "caixa":
        return None
    if not str(item_id).isdigit():
        return None
    return f"https://venda-imoveis.caixa.gov.br/fotos/F{int(item_id):013d}21.jpg"


def _market_value_for(item_id: str, raw_id: str, market_values: dict):
    if item_id in market_values:
        return market_values[item_id], True
    if raw_id and raw_id in market_values:
        return market_values[raw_id], True
    return None, False


def _apply_derived(item: dict, settings: dict, market_values: dict, exclusion_index: dict) -> dict:
    """Recalcula valor ajustado, desconto, lucro e exclusão."""
    preco = float(item.get("preco") or 0)
    valor_bruto = item.get("valor_avaliacao")
    if valor_bruto is not None and valor_bruto <= 0:
        valor_bruto = None
    item["valor_avaliacao"] = round(valor_bruto, 2) if valor_bruto is not None else None

    override, adjusted = _market_value_for(
        item["id"], item.get("id_fonte", ""), market_values
    )
    valor_ajustado = override if override is not None else valor_bruto
    if valor_ajustado is not None and valor_ajustado <= 0:
        valor_ajustado = None

    item["preco"] = round(preco, 2)
    item["ajustado"] = adjusted
    item["valor_ajustado"] = (
        round(valor_ajustado, 2) if valor_ajustado is not None else None
    )
    item["sem_avaliacao"] = valor_ajustado is None
    item["sem_preco"] = preco <= 0
    item["preco_label"] = (
        "Sob consulta"
        if preco <= 0 and item.get("fonte") == "itau"
        else "Faça sua oferta"
        if preco <= 0
        else None
    )

    if valor_ajustado is None:
        item["desconto"] = None
        item["lucro"] = None
        item["lucro_pct"] = None
    else:
        item["desconto"] = round(
            (valor_ajustado - preco) / valor_ajustado * 100, 2
        )
        fator = (
            1
            if norm(item.get("modalidade", "")) in {"VENDA ONLINE", "VENDA DIRETA ONLINE"}
            else settings["fator_preco"]
        )
        lucro = (
            valor_ajustado
            - valor_ajustado * settings["taxa_venda"]
            - fixed_cost_for(settings, valor_ajustado)
            - preco * fator
        )
        item["lucro"] = round(lucro, 2)
        item["lucro_pct"] = round(lucro / valor_ajustado * 100, 2)

    reason = exclusion_reason(item, item.get("_exclude_ids", set()), exclusion_index)
    item["excluido"] = bool(reason)
    item["motivo_exclusao"] = reason
    return item


def build_item(
    source_id: str,
    raw_id: str,
    row: dict,
    file_name: str,
    settings: dict,
    market_values: dict,
    exclusion_index: dict,
    exclude_ids: set[str],
) -> dict:
    item_id = raw_id if source_id == "caixa" else f"{source_id}:{raw_id}"
    preco = parse_money(row.get("Preço")) or 0.0
    valor_bruto = parse_money(row.get("Valor de avaliação"))
    if valor_bruto is not None and valor_bruto <= 0:
        valor_bruto = None
    modalidade = field_text(row.get("Modalidade de venda", ""))
    imagem = field_text(row.get("Imagem") or row.get("imagem") or "")
    item = {
        "id": item_id,
        "id_fonte": raw_id,
        "fonte": source_id,
        "fonte_nome": SOURCE_NAMES.get(source_id, source_id),
        "uf": field_text(row.get("UF", "")),
        "cidade": field_text(row.get("Cidade", "")),
        "bairro": field_text(row.get("Bairro", "")),
        "endereco": field_text(row.get("Endereço", "")),
        "preco": preco,
        "valor_avaliacao": valor_bruto,
        "financiamento": field_text(row.get("Financiamento", "")),
        "descricao": field_text(row.get("Descrição", "")),
        "modalidade": modalidade,
        "link": field_text(row.get("Link de acesso", "")),
        "imagem": imagem or image_url(raw_id, source_id),
        "arquivo": file_name,
        "_exclude_ids": exclude_ids,
    }
    _apply_derived(item, settings, market_values, exclusion_index)
    item.pop("_exclude_ids", None)
    return item


def recompute_item(
    item: dict,
    settings: dict,
    market_values: dict,
    exclusion_index: dict,
    exclude_ids: set[str],
    cache: dict,
) -> dict:
    """Recalcula um item vindo da versão anterior (fonte que falhou)."""
    result = dict(item)
    result["_exclude_ids"] = exclude_ids
    _apply_derived(result, settings, market_values, exclusion_index)
    result.pop("_exclude_ids", None)
    attach_coordinates(result, cache)
    return result


# ---------------------------------------------------------------------------
# Metadados e estatísticas
# ---------------------------------------------------------------------------

def build_meta(
    items: list[dict],
    source_files: dict[str, str],
    generation_date: str | None,
    market_values: dict,
    exclude_ids: set,
    exclude_locations: list,
    cache: dict,
    settings: dict,
) -> dict:
    ufs = sorted({item["uf"] for item in items if item["uf"]})
    cidades: dict[str, set] = {}
    bairros: dict[str, set] = {}
    for item in items:
        cidades.setdefault(item["uf"], set()).add(item["cidade"])
        bairros.setdefault(f"{item['uf']}|{item['cidade']}", set()).add(item["bairro"])
    modalidades = sorted({item["modalidade"] for item in items if item["modalidade"]})
    prices = [item["preco"] for item in items if item.get("preco") is not None]
    fontes_counts: dict[str, int] = {}
    for item in items:
        fontes_counts[item.get("fonte", "caixa")] = (
            fontes_counts.get(item.get("fonte", "caixa"), 0) + 1
        )
    fontes = [
        {
            "id": source_id,
            "nome": SOURCE_NAMES.get(source_id, source_id),
            "count": fontes_counts[source_id],
        }
        for source_id in SOURCE_ORDER
        if fontes_counts.get(source_id)
    ]
    return {
        "csv_file": " + ".join(source_files.values()) if source_files else "",
        "source_files": source_files,
        "generation_date": generation_date,
        "total_properties": len(items),
        "ufs": ufs,
        "cidades": {uf: sorted(values) for uf, values in cidades.items()},
        "bairros": {key: sorted(values) for key, values in bairros.items()},
        "modalidades": modalidades,
        "fontes": fontes,
        "preco_min": round(min(prices), 2) if prices else 0,
        "preco_max": round(max(prices), 2) if prices else 0,
        "market_values_count": len(market_values),
        "exclude_ids_count": len(exclude_ids),
        "exclude_locations_count": len(exclude_locations),
        "geocode_cached": len(cache.get("points", {})),
        "geocode_misses": len(cache.get("misses", {})),
        "geocode_updated": cache.get("updated"),
        "settings": settings,
    }


def _percentile(values: list[float], fraction: float):
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * fraction))))
    return ordered[index]


def build_stats(
    items: list[dict],
    previous_items: list[dict],
    new_ids: list[str],
    changed_ids: list[str],
    removed_ids: list[str],
    geocode_stats: dict,
    source_status: dict,
    data_hash: str,
    generated_at: str,
) -> dict:
    by_source = {}
    for source_id in SOURCE_ORDER:
        subset = [item for item in items if item.get("fonte") == source_id]
        by_source[source_id] = {
            "nome": SOURCE_NAMES[source_id],
            "total": len(subset),
            "excluidos": sum(1 for item in subset if item.get("excluido")),
            "com_imagem": sum(1 for item in subset if item.get("imagem")),
            "com_coordenadas": sum(
                1 for item in subset if item.get("lat") is not None
            ),
        }
    prices = [item["preco"] for item in items if item.get("preco") and item["preco"] > 0]
    descontos = [
        item["desconto"] for item in items if item.get("desconto") is not None
    ]
    lucros = [item["lucro"] for item in items if item.get("lucro") is not None]
    uf_counts: dict[str, int] = {}
    for item in items:
        uf_counts[item.get("uf", "")] = uf_counts.get(item.get("uf", ""), 0) + 1
    return {
        "gerado_em": generated_at,
        "sha256": data_hash,
        "total": len(items),
        "total_anterior": len(previous_items),
        "novos": len(new_ids),
        "alterados": len(changed_ids),
        "removidos": len(removed_ids),
        "excluidos": sum(1 for item in items if item.get("excluido")),
        "com_imagem": sum(1 for item in items if item.get("imagem")),
        "com_coordenadas": sum(1 for item in items if item.get("lat") is not None),
        "precisao_geo": {
            (precision or "nao_informado"): sum(
                1 for item in items if item.get("geo_precisao") == precision
            )
            for precision in ("bairro", "cidade", "estado", None)
        },
        "fontes": by_source,
        "preco": {
            "min": round(min(prices), 2) if prices else 0,
            "max": round(max(prices), 2) if prices else 0,
            "mediana": round(statistics.median(prices), 2) if prices else 0,
            "p25": round(_percentile(prices, 0.25) or 0, 2),
            "p75": round(_percentile(prices, 0.75) or 0, 2),
        },
        "desconto": {
            "mediana": round(statistics.median(descontos), 2) if descontos else None,
            "p90": round(_percentile(descontos, 0.90), 2) if descontos else None,
        },
        "lucro": {
            "mediana": round(statistics.median(lucros), 2) if lucros else None,
            "positivos": sum(1 for value in lucros if value > 0),
        },
        "ufs": dict(sorted(uf_counts.items(), key=lambda pair: pair[1], reverse=True)),
        "geocodificacao": geocode_stats,
        "coleta": source_status,
    }


# ---------------------------------------------------------------------------
# Comparação e validação
# ---------------------------------------------------------------------------

def item_content_signature(item: dict) -> str:
    payload = {
        key: value
        for key, value in item.items()
        if key not in TIMESTAMP_FIELDS
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def apply_history_timestamps(
    items: list[dict],
    previous_items: list[dict],
    now: str,
) -> tuple[list[dict], list[str], list[str]]:
    """Preserva ``primeira_visao``/``atualizado_em`` e classifica mudanças."""
    previous = {item["id"]: item for item in previous_items}
    changed: list[str] = []
    new: list[str] = []
    for item in items:
        old = previous.get(item["id"])
        if not old:
            item["primeira_visao"] = now
            item["atualizado_em"] = now
            new.append(item["id"])
            continue
        item["primeira_visao"] = old.get("primeira_visao") or old.get("atualizado_em") or now
        if item_content_signature(item) != item_content_signature(old):
            item["atualizado_em"] = now
            changed.append(item["id"])
        else:
            item["atualizado_em"] = old.get("atualizado_em") or now
    return items, new, changed


def find_removed(
    previous_items: list[dict],
    current_ids: set[str],
    successful_sources: set[str],
) -> list[dict]:
    """Itens ausentes apenas em fontes que responderam com sucesso."""
    removed = []
    for item in previous_items:
        if item.get("fonte") not in successful_sources:
            continue
        if item["id"] not in current_ids:
            removed.append(item)
    return removed


def dedupe_items(items: list[dict]) -> tuple[list[dict], int]:
    """Remove IDs duplicados; a última ocorrência vence."""
    unique: dict[str, dict] = {}
    duplicates = 0
    for item in items:
        if item["id"] in unique:
            duplicates += 1
        unique[item["id"]] = item
    return list(unique.values()), duplicates


def sort_items_deterministic(items: list[dict]) -> list[dict]:
    """Ordena por fonte preservando a ordem das linhas dentro de cada CSV.

    O projeto original monta o dataset na ordem dos arquivos e usa uma
    ordenação estável por desconto/lucro.  Preservar a ordem dentro da fonte
    mantém os empates exatamente iguais aos do site atual.
    """
    order = {source_id: index for index, source_id in enumerate(SOURCE_ORDER)}
    return sorted(items, key=lambda item: order.get(item.get("fonte", "caixa"), 99))


def validate_items(items: list[dict]) -> list[str]:
    """Valida tipos e campos obrigatórios.  Retorna lista de erros."""
    errors: list[str] = []
    if not items:
        return ["Nenhum imóvel para publicar"]
    seen: set[str] = set()
    for index, item in enumerate(items):
        prefix = f"item[{index}] id={item.get('id', '?')!r}"
        for field in REQUIRED_FIELDS:
            value = item.get(field)
            if value is None or (isinstance(value, str) and not value.strip()):
                errors.append(f"{prefix}: campo obrigatório vazio: {field}")
        item_id = item.get("id")
        if not isinstance(item_id, str):
            errors.append(f"{prefix}: id deve ser string")
        if item_id in seen:
            errors.append(f"{prefix}: id duplicado")
        seen.add(item_id)
        if item.get("fonte") not in SOURCE_NAMES:
            errors.append(f"{prefix}: fonte inválida {item.get('fonte')!r}")
        for field in ("preco", "valor_avaliacao", "valor_ajustado", "desconto", "lucro", "lucro_pct"):
            value = item.get(field)
            if value is None:
                continue
            if not isinstance(value, (int, float)):
                errors.append(f"{prefix}: {field} não numérico")
            elif value != value or value in (float("inf"), float("-inf")):
                errors.append(f"{prefix}: {field} inválido (NaN/Inf)")
        for field in ("lat", "lng"):
            value = item.get(field)
            if value is None:
                continue
            lower, upper = (-90, 90) if field == "lat" else (-180, 180)
            if not isinstance(value, (int, float)) or not (lower <= value <= upper):
                errors.append(f"{prefix}: {field} fora de faixa")
        for field in ("link", "imagem"):
            value = item.get(field)
            if value and not str(value).startswith(("http://", "https://")):
                errors.append(f"{prefix}: {field} não é URL http(s)")
        if not isinstance(item.get("excluido"), bool):
            errors.append(f"{prefix}: excluido deve ser booleano")
    return errors


# ---------------------------------------------------------------------------
# Filtros (usados em testes e validação; o frontend replica em JS)
# ---------------------------------------------------------------------------

def filter_items(items, params, apply_exclusions=True):
    uf = (params.get("uf") or "all").strip()
    cidade = (params.get("cidade") or "all").strip()
    bairro = (params.get("bairro") or "all").strip()
    preco_min = float(params.get("preco_min") or 0)
    preco_max = float(params.get("preco_max") or 0) or float("inf")
    desconto_min = float(params.get("desconto_min") or 0)
    lucro_min = float(params.get("lucro_min") or 0)
    financiamento = (params.get("financiamento") or "all").strip().lower()
    modalidade = (params.get("modalidade") or "all").strip()
    fonte = (params.get("fonte") or "all").strip().lower()
    query = norm(params.get("q") or "")
    bbox_values = None
    bbox = (params.get("bbox") or "").strip()
    if bbox:
        try:
            values = [float(part) for part in bbox.split(",")]
        except ValueError:
            values = []
        if len(values) == 4:
            bbox_values = values

    uf_values = None if uf.lower() == "all" else {norm(v) for v in uf.split(",") if v.strip()}
    cidade_value = None if cidade.lower() == "all" else norm(cidade)
    bairro_value = None if bairro.lower() == "all" else norm(bairro)
    modalidade_value = None if modalidade.lower() == "all" else norm(modalidade)
    fonte_value = None if fonte == "all" else fonte

    result = []
    for item in items:
        if apply_exclusions and item.get("excluido"):
            continue
        if uf_values and norm(item["uf"]) not in uf_values:
            continue
        if cidade_value and norm(item["cidade"]) != cidade_value:
            continue
        if bairro_value and norm(item["bairro"]) != bairro_value:
            continue
        if item["preco"] < preco_min or item["preco"] > preco_max:
            continue
        desconto = item.get("desconto")
        if desconto is None:
            if desconto_min > 0:
                continue
        elif desconto < desconto_min:
            continue
        lucro = item.get("lucro")
        if lucro is None:
            if lucro_min > 0:
                continue
        elif lucro < lucro_min:
            continue
        if financiamento == "sim" and norm(item["financiamento"]) != "SIM":
            continue
        if financiamento == "nao" and norm(item["financiamento"]) == "SIM":
            continue
        if modalidade_value and norm(item["modalidade"]) != modalidade_value:
            continue
        if fonte_value and item.get("fonte", "caixa") != fonte_value:
            continue
        if bbox_values:
            lat = item.get("lat")
            lng = item.get("lng")
            if lat is None or lng is None:
                continue
            min_lat, min_lng, max_lat, max_lng = bbox_values
            if not (min_lat <= lat <= max_lat and min_lng <= lng <= max_lng):
                continue
        if query:
            haystack = norm(
                " ".join(
                    [
                        item["id"],
                        item["uf"],
                        item["cidade"],
                        item["bairro"],
                        item["endereco"],
                        item["descricao"],
                        item["modalidade"],
                    ]
                )
            )
            if query not in haystack:
                continue
        result.append(item)
    return result


def _sort_metric(item, key):
    value = item.get(key)
    return (value is not None, value if value is not None else 0)


def sort_items(items, sort_key):
    if sort_key == "preco_asc":
        return sorted(items, key=lambda item: item["preco"])
    if sort_key == "preco_desc":
        return sorted(items, key=lambda item: item["preco"], reverse=True)
    if sort_key == "lucro_desc":
        return sorted(items, key=lambda item: _sort_metric(item, "lucro"), reverse=True)
    if sort_key == "lucro_pct_desc":
        return sorted(items, key=lambda item: _sort_metric(item, "lucro_pct"), reverse=True)
    if sort_key == "endereco":
        return sorted(
            items,
            key=lambda item: (
                norm(item["uf"]),
                norm(item["cidade"]),
                norm(item["bairro"]),
                norm(item["endereco"]),
            ),
        )
    return sorted(items, key=lambda item: _sort_metric(item, "desconto"), reverse=True)


def items_to_csv(items) -> str:
    """CSV combinado, idêntico ao ``/api/csv`` do projeto original."""
    columns = [
        "Fonte",
        "ID",
        "ID na fonte",
        "UF",
        "Cidade",
        "Bairro",
        "Endereço",
        "Preço",
        "Condição de preço",
        "Valor de avaliação",
        "Valor ajustado",
        "Desconto (%)",
        "Lucro (R$)",
        "Lucro (%)",
        "Financiamento",
        "Modalidade",
        "Descrição",
        "Link",
        "Imagem",
        "Latitude",
        "Longitude",
        "Precisão geográfica",
        "Excluído",
        "Motivo da exclusão",
    ]
    source_order = {source_id: index for index, source_id in enumerate(SOURCE_ORDER)}
    ordered = sorted(
        items,
        key=lambda item: (
            source_order.get(item.get("fonte", "caixa"), 99),
            norm(item.get("uf", "")),
            norm(item.get("cidade", "")),
            norm(item.get("bairro", "")),
            norm(item.get("endereco", "")),
            item.get("id", ""),
        ),
    )
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";", lineterminator="\r\n")
    writer.writerow(columns)
    for item in ordered:
        writer.writerow(
            [
                SOURCE_NAMES.get(item.get("fonte", "caixa"), item.get("fonte", "")),
                item.get("id", ""),
                item.get("id_fonte", ""),
                item.get("uf", ""),
                item.get("cidade", ""),
                item.get("bairro", ""),
                item.get("endereco", ""),
                br_number(item.get("preco")),
                item.get("preco_label") or "",
                br_number(item.get("valor_avaliacao")),
                br_number(item.get("valor_ajustado")),
                br_number(item.get("desconto")),
                br_number(item.get("lucro")),
                br_number(item.get("lucro_pct")),
                item.get("financiamento", ""),
                item.get("modalidade", ""),
                item.get("descricao", ""),
                item.get("link", ""),
                item.get("imagem") or "",
                item.get("lat") if item.get("lat") is not None else "",
                item.get("lng") if item.get("lng") is not None else "",
                item.get("geo_precisao") or "",
                "Sim" if item.get("excluido") else "Não",
                item.get("motivo_exclusao") or "",
            ]
        )
    return "\ufeff" + output.getvalue()


def load_config_bundle(paths) -> dict:
    """Carrega configuração e devolve tudo o que o build precisa."""
    settings = load_settings(paths.config_file)
    market_values = normalize_market_values(load_market_values(paths.market_values_file))
    exclude_ids, exclude_locations = load_exclusions(
        paths.exclude_ids_file, paths.exclude_locations_file
    )
    return {
        "settings": settings,
        "market_values": market_values,
        "exclude_ids": exclude_ids,
        "exclude_locations": exclude_locations,
        "exclusion_index": build_exclusion_index(exclude_locations),
    }


def config_public_payload(config: dict) -> dict:
    """Pequeno JSON consumido pela caixa de Configurações do site."""
    return {
        "settings": config["settings"],
        "market_values": config["market_values"],
        "exclude_ids": sorted(
            config["exclude_ids"],
            key=lambda value: (0, int(value)) if value.isdigit() else (1, value),
        ),
        "exclude_locations": config["exclude_locations"],
    }
