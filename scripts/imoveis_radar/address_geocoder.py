"""Geocodificação de endereços com validação de município e UF.

O Nominatim devolve o primeiro resultado mesmo quando a rua não existe na
cidade pesquisada (por exemplo, uma "Avenida Paulista" em Pederneiras/SP).
Por isso cada candidato é validado:

* o estado (``ISO3166-2-lvl4``) precisa bater com a UF da planilha;
* a cidade precisa bater com o município;
* a rua precisa ter nome semelhante ao logradouro normalizado.

A precisão é classificada de acordo com o resultado (endereço/rua/bairro).
Nada é inventado: quando nenhum candidato passa na validação, o endereço é
marcado como não encontrado.
"""
from __future__ import annotations

import math
import re
from difflib import SequenceMatcher

from . import geocode_client
from .addresses import STREET_TYPES
from .text import norm

UF_NOME = {
    "AC": "ACRE",
    "AL": "ALAGOAS",
    "AP": "AMAPA",
    "AM": "AMAZONAS",
    "BA": "BAHIA",
    "CE": "CEARA",
    "DF": "DISTRITO FEDERAL",
    "ES": "ESPIRITO SANTO",
    "GO": "GOIAS",
    "MA": "MARANHAO",
    "MT": "MATO GROSSO",
    "MS": "MATO GROSSO DO SUL",
    "MG": "MINAS GERAIS",
    "PA": "PARA",
    "PB": "PARAIBA",
    "PR": "PARANA",
    "PE": "PERNAMBUCO",
    "PI": "PIAUI",
    "RJ": "RIO DE JANEIRO",
    "RN": "RIO GRANDE DO NORTE",
    "RS": "RIO GRANDE DO SUL",
    "RO": "RONDONIA",
    "RR": "RORAIMA",
    "SC": "SANTA CATARINA",
    "SP": "SAO PAULO",
    "SE": "SERGIPE",
    "TO": "TOCANTINS",
}

# Tipos de resultado do Nominatim que representam a via, não um imóvel.
ROAD_TYPES = {
    "residential",
    "tertiary",
    "secondary",
    "primary",
    "trunk",
    "motorway",
    "service",
    "unclassified",
    "living_street",
    "pedestrian",
    "footway",
    "cycleway",
    "track",
    "road",
    "path",
    "steps",
    "construction",
}

_PLACE_TYPES = {"house", "building", "apartments", "detached", "residential"}
_CONNECTORS = {"DE", "DA", "DO", "DAS", "DOS", "E", "NO", "NA", "DOS", "DAS"}


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Distância em km entre dois pontos (fórmula de Haversine)."""
    radius = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(a))


def _tokens(value: str) -> list[str]:
    type_words = set(STREET_TYPES.values()) | _CONNECTORS
    return [
        token
        for token in norm(value).split()
        if token not in type_words
    ]


def _name_similarity(left: str, right: str) -> float:
    """Semelhança entre nomes de via (0 a 1)."""
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    common = set(left_tokens) & set(right_tokens)
    overlap = len(common) / len(set(right_tokens))
    sequence = SequenceMatcher(
        None, " ".join(left_tokens), " ".join(right_tokens)
    ).ratio()
    return max(overlap, sequence)


def _state_ok(address: dict, uf: str, display_name: str = "") -> bool:
    uf_key = norm(uf)
    iso = norm(address.get("ISO3166-2-lvl4", ""))
    if iso.startswith("BR-"):
        return iso.endswith(f"-{uf_key}")
    state = norm(address.get("state", ""))
    if state:
        return state == uf_key or state == UF_NOME.get(uf_key, "")
    # Alguns resultados rurais vêm sem o campo state; o nome do estado
    # aparece no display_name.
    name = norm(display_name)
    state_name = UF_NOME.get(uf_key, "")
    return bool(name) and re.search(rf"\b{re.escape(state_name)}\b", name) is not None


def _city_values(address: dict) -> list[str]:
    values = []
    for field in ("city", "town", "municipality", "village", "city_district"):
        value = norm(address.get(field, ""))
        if value:
            values.append(value)
    return values


def _city_ok(address: dict, cidade: str, display_name: str = "") -> bool:
    target = norm(cidade)
    if not target:
        return True
    for value in _city_values(address):
        if value == target:
            return True
        if len(value) > 3 and (target in value or value in target):
            return True
    # Nem todo resultado traz city/municipality; a cidade costuma aparecer no
    # display_name.  É preciso descartar o nome do estado: para "Rio de
    # Janeiro" (cidade e estado), um resultado em Nova Iguaçu também contém
    # "Rio de Janeiro" no display_name.
    if not display_name:
        return False
    state = norm(address.get("state", ""))
    parts = [norm(part) for part in display_name.split(",")]
    for part in parts:
        if not part or part == state:
            continue
        if part == target or (len(target) > 3 and target in part):
            return True
    return False


def _bairro_ok(address: dict, bairro: str) -> bool:
    target = norm(bairro)
    if not target:
        return False
    values = [
        norm(address.get(field, ""))
        for field in ("suburb", "neighbourhood", "quarter", "city_district")
    ]
    return any(value and (value == target or target in value or value in target) for value in values)


def _number_equal(left: str, right: str) -> bool:
    def clean(value: str) -> str:
        text = norm(value).replace(" ", "").replace("-", "")
        return text.lstrip("0") or "0"

    return bool(left and right) and clean(left) == clean(right)


def _precision(item: dict, numero: str) -> str:
    """Classifica a precisão do resultado: endereco, rua, bairro ou aproximado."""
    address = item.get("address") or {}
    category = str(item.get("category") or "").lower()
    place_type = str(item.get("type") or "").lower()
    address_type = str(item.get("addresstype") or "").lower()
    house = address.get("house_number", "")

    if house and numero and _number_equal(house, numero):
        return "endereco"
    if category == "highway" or place_type in ROAD_TYPES:
        return "rua"
    if place_type in _PLACE_TYPES or category in {"building", "amenity", "shop", "office", "tourism"}:
        return "endereco" if house else "rua"
    if place_type in {"suburb", "neighbourhood", "quarter", "city_district"}:
        return "bairro"
    if place_type in {"city", "town", "village", "municipality"} or address_type in {
        "city",
        "town",
        "village",
        "municipality",
        "county",
        "state",
        "region",
    }:
        return "cidade"
    return "aproximado"


def _coordinates(item: dict) -> tuple[float, float] | None:
    try:
        return float(item["lat"]), float(item["lon"])
    except (KeyError, TypeError, ValueError):
        return None


def _match(
    item: dict,
    uf: str,
    cidade: str,
    consulta: str,
    numero: str = "",
    logradouro: str = "",
) -> dict | None:
    address = item.get("address") or {}
    display_name = item.get("display_name", "")
    if not _state_ok(address, uf, display_name) or not _city_ok(
        address, cidade, display_name
    ):
        return None
    coordinates = _coordinates(item)
    if not coordinates:
        return None

    precision = _precision(item, numero)
    if precision == "cidade":
        # O centroide do município não melhora a coordenada que a planilha já
        # tem; melhor tentar o bairro ou marcar como não encontrado.
        return None
    if logradouro:
        candidates = [
            address.get("road", ""),
            item.get("name", ""),
            display_name,
        ]
        similarity = max(
            (_name_similarity(candidate, logradouro) for candidate in candidates if candidate),
            default=0.0,
        )
        if similarity < 0.7:
            # A cidade bate, mas não é possível confirmar que é a mesma via.
            precision = "aproximado"
    return {
        "status": "ok",
        "lat": coordinates[0],
        "lng": coordinates[1],
        "precisao": precision,
        "fonte": "nominatim",
        "endereco_retornado": item.get("display_name", ""),
        "consulta": consulta,
    }


def _best_match(
    data,
    uf: str,
    cidade: str,
    consulta: str,
    numero: str = "",
    logradouro: str = "",
) -> dict | None:
    for item in data or []:
        match = _match(item, uf, cidade, consulta, numero, logradouro)
        if match:
            return match
    return None


def _without_type(logradouro: str) -> str:
    """Remove o tipo da via e conectores iniciais ("RUA DO PURUS" → "PURUS")."""
    tokens = logradouro.split()
    if (
        len(tokens) > 1
        and tokens[0] in set(STREET_TYPES.values())
        and not tokens[1][:1].isdigit()
    ):
        tokens = tokens[1:]
    while tokens and tokens[0] in {"DE", "DA", "DO", "DAS", "DOS"}:
        tokens = tokens[1:]
    remainder = " ".join(tokens).strip()
    return remainder if len(remainder) >= 3 else logradouro


def geocode_endereco(
    uf: str,
    cidade: str,
    logradouro: str,
    numero: str = "",
    bairro: str = "",
    include_number: bool = True,
    searcher=None,
    timeout: int = 25,
) -> dict:
    """Geocodifica um endereço normalizado, tentando rua e depois bairro.

    ``searcher`` permite injetar um cliente falso nos testes.  Quando a API
    limita as requisições, ``geocode_client.RateLimitError`` é propagado para
    que o chamador possa parar e retomar depois (o cache guarda o progresso).
    """
    if not logradouro:
        return {"status": "sem_endereco", "consulta": "", "precisao": "", "fonte": ""}

    searcher = searcher or geocode_client.search_detailed
    # Consultar sem o tipo ("PURUS") encontra mais ruas do que com o tipo
    # ("RUA DO PURUS"); a versão completa fica como segunda tentativa.
    consultas: list[str] = []
    if include_number and numero:
        consultas.append(f"{logradouro}, {numero}, {cidade} - {uf}, Brasil")
    consultas.append(f"{_without_type(logradouro)}, {cidade} - {uf}, Brasil")
    consultas.append(f"{logradouro}, {cidade} - {uf}, Brasil")
    # Remove repetidas mantendo a ordem.
    consultas = list(dict.fromkeys(consultas))

    primeira = consultas[0]
    for consulta in consultas:
        data = searcher(consulta, timeout=timeout)
        if data is geocode_client.RATE_LIMITED:
            raise geocode_client.RateLimitError(
                "Nominatim pediu para desacelerar; o cache permite retomar"
            )
        match = _best_match(
            data, uf, cidade, consulta, numero=numero, logradouro=logradouro
        )
        if match:
            return match

    if bairro:
        consulta = f"{bairro}, {cidade} - {uf}, Brasil"
        data = searcher(consulta, timeout=timeout)
        if data is geocode_client.RATE_LIMITED:
            raise geocode_client.RateLimitError(
                "Nominatim pediu para desacelerar; o cache permite retomar"
            )
        match = _best_bairro(data, uf, cidade, bairro, consulta)
        if match:
            return match

    return {
        "status": "nao_encontrado",
        "lat": None,
        "lng": None,
        "precisao": "",
        "fonte": "",
        "endereco_retornado": "",
        "consulta": primeira,
    }


def _best_bairro(data, uf: str, cidade: str, bairro: str, consulta: str) -> dict | None:
    for item in data or []:
        address = item.get("address") or {}
        display_name = item.get("display_name", "")
        if not _state_ok(address, uf, display_name) or not _city_ok(
            address, cidade, display_name
        ):
            continue
        if not _bairro_ok(address, bairro):
            continue
        coordinates = _coordinates(item)
        if not coordinates:
            continue
        return {
            "status": "ok",
            "lat": coordinates[0],
            "lng": coordinates[1],
            "precisao": "bairro",
            "fonte": "nominatim",
            "endereco_retornado": item.get("display_name", ""),
            "consulta": consulta,
        }
    return None
