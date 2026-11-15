from __future__ import annotations

from datetime import date

from importar_geocache_local import (
    collect_bairros,
    import_bairros,
    import_streets,
)

TODAY = date(2026, 11, 15)


def _query(status, *, precisao="", lat=None, lng=None):
    result = {"status": status, "precisao": precisao}
    if lat is not None:
        result["lat"] = lat
        result["lng"] = lng
        result["fonte"] = "nominatim"
        result["endereco_retornado"] = "Rua, cidade, Brasil"
        result["consulta"] = "RUA, cidade - UF, Brasil"
    return result


def test_import_streets_copia_terminais_e_baixa_precisao():
    queries = {
        "AC|CRUZEIRO DO SUL|RUA A": _query("ok", precisao="rua", lat=-7.6, lng=-72.6),
        "AC|CRUZEIRO DO SUL|RUA B": _query("ok", precisao="bairro", lat=-7.7, lng=-72.7),
        "AC|CRUZEIRO DO SUL|RUA C": _query("nao_encontrado"),
        "AC|CRUZEIRO DO SUL|RUA ORFA": _query("ok", precisao="rua", lat=-7.8, lng=-72.8),
    }
    project_keys = {
        "AC|CRUZEIRO DO SUL|RUA A",
        "AC|CRUZEIRO DO SUL|RUA B",
        "AC|CRUZEIRO DO SUL|RUA C",
    }
    cache = {"points": {}, "misses": {}, "ruas": {}}
    stats = import_streets(cache, queries, project_keys, TODAY)

    assert stats == {
        "terminais": 1,
        "baixa_precisao": 1,
        "nao_encontradas": 1,
        "ignoradas": 1,
        "existentes": 0,
    }
    assert cache["ruas"]["AC|CRUZEIRO DO SUL|RUA A"]["precisao"] == "rua"
    assert cache["ruas"]["AC|CRUZEIRO DO SUL|RUA A"]["proxima_tentativa"] is None
    assert cache["ruas"]["AC|CRUZEIRO DO SUL|RUA B"]["status"] == "baixa_precisao"
    assert "lat" not in cache["ruas"]["AC|CRUZEIRO DO SUL|RUA B"]
    assert (
        cache["ruas"]["AC|CRUZEIRO DO SUL|RUA B"]["proxima_tentativa"]
        == TODAY.isoformat()
    )
    assert "AC|CRUZEIRO DO SUL|RUA ORFA" not in cache["ruas"]


def test_import_streets_e_idempotente_e_nao_rebaixa_terminal():
    terminal = _query("ok", precisao="rua", lat=-7.6, lng=-72.6)
    cache = {
        "points": {},
        "misses": {},
        "ruas": {
            "AC|CRUZEIRO DO SUL|RUA A": {
                "status": "ok",
                "lat": -7.1,
                "lng": -72.1,
                "precisao": "endereco",
                "proxima_tentativa": None,
            }
        },
    }
    keys = {"AC|CRUZEIRO DO SUL|RUA A", "AC|CRUZEIRO DO SUL|RUA B"}
    queries = {
        "AC|CRUZEIRO DO SUL|RUA A": terminal,
        "AC|CRUZEIRO DO SUL|RUA B": _query("ok", precisao="bairro"),
    }
    first = import_streets(cache, queries, keys, TODAY)
    second = import_streets(cache, queries, keys, TODAY)
    assert first["existentes"] == 1
    assert second["existentes"] == 2
    assert cache["ruas"]["AC|CRUZEIRO DO SUL|RUA A"]["lat"] == -7.1


def _row(bairro="Centro", *, lat="-7.6355", lng="-72.6669", precisao="bairro", status="ok"):
    return {
        "Status geocodificação": status,
        "Precisão geocodificada": precisao,
        "UF": "AC",
        "Cidade normalizada": "Cruzeiro do Sul",
        "Bairro normalizado": bairro,
        "Latitude geocodificada": lat,
        "Longitude geocodificada": lng,
    }


def test_collect_bairros_escolhe_coordenada_mais_frequente():
    rows = [
        _row(),
        _row(),
        _row(lat="-7.63", lng="-72.66"),
        _row(precisao="rua"),
        _row(status="nao_encontrado"),
    ]
    bairros = collect_bairros(rows)
    assert len(bairros) == 1
    bairro = bairros["AC|CRUZEIRO DO SUL|CENTRO"]
    assert (bairro["lat"], bairro["lng"]) == (-7.6355, -72.6669)


def test_import_bairros_grava_points_sem_rebaixar():
    cache = {"points": {}, "misses": {}, "ruas": {}}
    rows = [_row()]
    stats = import_bairros(cache, rows)
    assert stats == {"distintos": 1, "adicionados": 1, "existentes": 0}
    point = cache["points"]["AC|CRUZEIRO DO SUL|CENTRO"]
    assert point["precisao"] == "bairro"
    assert point["lat"] == -7.6355

    stats = import_bairros(cache, rows)
    assert stats == {"distintos": 1, "adicionados": 0, "existentes": 1}
    assert cache["points"]["AC|CRUZEIRO DO SUL|CENTRO"]["lat"] == -7.6355
