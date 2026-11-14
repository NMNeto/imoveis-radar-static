"""Normalização de nomes de cidades e bairros.

As fontes escrevem o mesmo lugar de formas diferentes ("Niteroi", "Niterói",
"SAO PAULO", "São Paulo").  O filtro já compara sem acento/maiúsculas, mas a
lista de opções exibia duplicatas.  Aqui escolhemos uma grafia de exibição
determinística por chave normalizada, sem alterar a localização real.
"""
from __future__ import annotations

from collections import Counter, defaultdict

from .text import norm


def _has_accent(value: str) -> bool:
    return any(ord(ch) > 127 for ch in value)


def _is_all_caps(value: str) -> bool:
    return bool(value) and value == value.upper() and any(ch.isalpha() for ch in value)


def choose_display_name(counter: Counter) -> str:
    """Escolhe a melhor grafia de exibição para um conjunto de variantes.

    Prioriza uma variante acentuada (a grafia correta em português) e, depois,
    uma variante que não esteja toda em maiúsculas.  A frequência decide os
    empates; variantes muito raras não vencem sozinhas.
    """
    if not counter:
        return ""
    max_count = max(counter.values())
    # Acentos costumam indicar a grafia correta; aceitamos até variantes raras.
    threshold = max(1, int(max_count * 0.02))

    accented = [
        (value, count)
        for value, count in counter.items()
        if _has_accent(value) and count >= threshold
    ]
    if accented:
        return max(accented, key=lambda pair: (pair[1], len(pair[0]), pair[0]))[0]

    mixed_case = [
        (value, count)
        for value, count in counter.items()
        if not _is_all_caps(value) and count >= threshold
    ]
    candidates = mixed_case or list(counter.items())
    return max(candidates, key=lambda pair: (pair[1], len(pair[0]), pair[0]))[0]


def canonicalize_locations(items: list[dict]) -> tuple[list[dict], dict]:
    """Unifica cidades e bairros por UF + nome normalizado.

    Retorna os itens (mutados) e estatísticas para o log/relatório.
    """
    city_variants: dict[tuple[str, str], Counter] = defaultdict(Counter)
    bairro_variants: dict[tuple[str, str, str], Counter] = defaultdict(Counter)

    for item in items:
        uf_key = norm(item.get("uf", ""))
        city = str(item.get("cidade", "")).strip()
        city_key = norm(city)
        if not city_key:
            continue
        city_variants[(uf_key, city_key)][city] += 1
        bairro = str(item.get("bairro", "")).strip()
        if bairro:
            bairro_variants[(uf_key, city_key, norm(bairro))][bairro] += 1

    city_display = {
        key: choose_display_name(counter) for key, counter in city_variants.items()
    }
    bairro_display = {
        key: choose_display_name(counter) for key, counter in bairro_variants.items()
    }

    city_changes = 0
    bairro_changes = 0
    for item in items:
        uf_key = norm(item.get("uf", ""))
        city = str(item.get("cidade", "")).strip()
        city_key = norm(city)
        if city_key:
            chosen_city = city_display.get((uf_key, city_key))
            if chosen_city and item.get("cidade") != chosen_city:
                item["cidade"] = chosen_city
                city_changes += 1
            bairro = str(item.get("bairro", "")).strip()
            if bairro:
                chosen_bairro = bairro_display.get((uf_key, city_key, norm(bairro)))
                if chosen_bairro and item.get("bairro") != chosen_bairro:
                    item["bairro"] = chosen_bairro
                    bairro_changes += 1

    stats = {
        "cidades": len(city_variants),
        "bairros": len(bairro_variants),
        "variantes_cidade": sum(max(0, len(counter) - 1) for counter in city_variants.values()),
        "variantes_bairro": sum(max(0, len(counter) - 1) for counter in bairro_variants.values()),
        "itens_cidade_alterados": city_changes,
        "itens_bairro_alterados": bairro_changes,
    }
    return items, stats
