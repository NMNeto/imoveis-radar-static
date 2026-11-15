"""Cliente de geocodificação com Nominatim e fallback para Photon.

As duas APIs são públicas e têm limites de uso.  Por isso as requisições são
serializadas, espaçadas e os resultados são guardados em cache pelo chamador.
Nenhum resultado é inventado: quando não há correspondência, o local é
registrado como "não encontrado" por 30 dias.
"""
from __future__ import annotations

import os
import threading
import time
import unicodedata

import requests

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
PHOTON_URL = "https://photon.komoot.io/api/"
USER_AGENT = os.environ.get(
    "IMOVEIS_GEOCODE_USER_AGENT",
    "imoveis-radar-static/1.0 (+https://github.com/NMNeto/imoveis-radar-static)",
)
MIN_INTERVAL = float(os.environ.get("IMOVEIS_GEOCODE_INTERVAL", "1.5"))
MAX_RETRIES = 2

_lock = threading.Lock()
_last_request = 0.0
RATE_LIMITED = object()


class RateLimitError(RuntimeError):
    """Nominatim e Photon recusaram as requisições."""


def _norm(value) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.split()).upper()


def _throttle() -> None:
    global _last_request
    elapsed = time.time() - _last_request
    if elapsed < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - elapsed)
    _last_request = time.time()


def _request(url: str, params: dict, timeout: int):
    with _lock:
        _throttle()
        return requests.get(
            url,
            params=params,
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
        )


def _nominatim(query: str, timeout: int):
    params = {
        "format": "jsonv2",
        "limit": 1,
        "countrycodes": "br",
        "q": query,
    }
    response = _request(NOMINATIM_URL, params, timeout)
    if response.status_code in (429, 503):
        return RATE_LIMITED
    response.raise_for_status()
    data = response.json()
    if not data:
        return None
    return {
        "lat": float(data[0]["lat"]),
        "lng": float(data[0]["lon"]),
        "fonte": "nominatim",
    }


def _photon(query: str, timeout: int, city: str | None = None):
    params = {"q": query, "limit": 5}
    response = _request(PHOTON_URL, params, timeout)
    if response.status_code in (429, 503):
        raise RateLimitError("Photon também limitou as requisições")
    response.raise_for_status()
    data = response.json()
    for feature in data.get("features", []):
        properties = feature.get("properties", {})
        if city and _norm(properties.get("city")) != _norm(city):
            continue
        coordinates = feature.get("geometry", {}).get("coordinates")
        if not coordinates or len(coordinates) < 2:
            continue
        return {
            "lat": float(coordinates[1]),
            "lng": float(coordinates[0]),
            "fonte": "photon",
        }
    return None


def search_detailed(query: str, timeout: int = 20, limit: int = 3):
    """Resultados do Nominatim com detalhes de endereço (``jsonv2``).

    Diferente de :func:`search`, devolve a lista crua de resultados para que o
    chamador possa validar cidade/UF e classificar a precisão.  Retorna
    ``RATE_LIMITED`` quando a API pede para desacelerar.
    """
    params = {
        "format": "jsonv2",
        "limit": limit,
        "countrycodes": "br",
        "addressdetails": 1,
        "q": query,
    }
    response = _request(NOMINATIM_URL, params, timeout)
    if response.status_code in (429, 503):
        return RATE_LIMITED
    response.raise_for_status()
    return response.json() or []


def search(query: str, timeout: int = 20, city: str | None = None):
    """Retorna ``{"lat", "lng", "fonte"}`` do primeiro resultado, ou None."""
    result = None
    for attempt in range(MAX_RETRIES):
        result = _nominatim(query, timeout)
        if result is not RATE_LIMITED:
            break
        if attempt + 1 < MAX_RETRIES:
            time.sleep(min(30.0, 5.0 * (2 ** attempt)))

    if result is not RATE_LIMITED:
        return result or None

    photon = _photon(query, timeout, city=city)
    if photon:
        return photon
    raise RateLimitError("Nominatim e Photon limitaram as requisições")
