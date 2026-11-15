from __future__ import annotations

from datetime import date, timedelta

import pytest

import geocodificar_ruas as job
from imoveis_radar import geocode_client

TODAY = date(2026, 11, 15)


def _item(
    item_id,
    endereco,
    *,
    bairro="CENTRO",
    cidade="CRUZEIRO DO SUL",
    uf="AC",
    precisao="cidade",
    excluido=False,
):
    return {
        "id": item_id,
        "uf": uf,
        "cidade": cidade,
        "bairro": bairro,
        "endereco": endereco,
        "geo_precisao": precisao,
        "excluido": excluido,
    }


def _target(key, *, uf="AC", cidade="CRUZEIRO DO SUL", logradouro="RUA A", bairro="CENTRO"):
    return {
        "key": key,
        "uf": uf,
        "cidade": cidade,
        "logradouro": logradouro,
        "bairro": bairro,
        "imoveis": 1,
        "criticos": 0,
        "nova": True,
    }


def test_collect_streets_agrupa_e_ignora_excluidos():
    items = [
        _item("1", "RUA A, 10", bairro="CENTRO"),
        _item("2", "RUA A, 20", bairro="CENTRO"),
        _item("3", "RUA A, 30", bairro="COHAB"),
        _item("4", "RUA B, 40", excluido=True),
    ]
    streets = job.collect_streets(items)
    assert len(streets) == 1
    street = streets[0]
    assert street["key"] == "AC|CRUZEIRO DO SUL|RUA A"
    assert street["imoveis"] == 3
    assert street["bairro"] == "CENTRO"


def test_build_queue_coloca_novas_antes_de_retentativas():
    items = [
        _item("1", "RUA NOVA GRANDE, 10"),
        _item("2", "RUA NOVA GRANDE, 20"),
        _item("3", "RUA NOVA GRANDE, 30"),
        _item("4", "RUA RETORNO, 10"),
        _item("5", "RUA TERMINAL, 10"),
    ]
    cache = {
        "points": {},
        "misses": {},
        "ruas": {
            "AC|CRUZEIRO DO SUL|RUA RETORNO": {
                "status": "baixa_precisao",
                "precisao": "bairro",
                "proxima_tentativa": (TODAY - timedelta(days=1)).isoformat(),
                "atualizado_em": (TODAY - timedelta(days=91)).isoformat(),
            },
            "AC|CRUZEIRO DO SUL|RUA TERMINAL": {
                "status": "ok",
                "lat": -7.6,
                "lng": -72.6,
                "precisao": "rua",
            },
        },
    }
    queue = job.build_queue(items, cache, TODAY)
    keys = [street["key"] for street in queue]
    assert keys == [
        "AC|CRUZEIRO DO SUL|RUA NOVA GRANDE",
        "AC|CRUZEIRO DO SUL|RUA RETORNO",
    ]


def test_build_queue_prioriza_imoveis_sem_coordenada():
    items = [
        _item("1", "RUA CRITICA, 10", precisao=None),
        *[
            _item(str(index), f"RUA GRANDE, {index}0", precisao="cidade")
            for index in range(2, 8)
        ],
    ]
    queue = job.build_queue(items, {"ruas": {}}, TODAY)
    assert queue[0]["key"] == "AC|CRUZEIRO DO SUL|RUA CRITICA"


def test_street_needs_retry():
    assert job.street_needs_retry(None, TODAY)
    terminal = {"status": "ok", "lat": 1, "lng": 2, "precisao": "rua"}
    assert not job.street_needs_retry(terminal, TODAY)

    future = {
        "status": "baixa_precisao",
        "proxima_tentativa": (TODAY + timedelta(days=1)).isoformat(),
    }
    assert not job.street_needs_retry(future, TODAY)
    past = {
        "status": "baixa_precisao",
        "proxima_tentativa": (TODAY - timedelta(days=1)).isoformat(),
    }
    assert job.street_needs_retry(past, TODAY)

    old = {
        "status": "nao_encontrado",
        "atualizado_em": (TODAY - timedelta(days=91)).isoformat(),
    }
    assert job.street_needs_retry(old, TODAY)
    recent = {
        "status": "nao_encontrado",
        "atualizado_em": (TODAY - timedelta(days=89)).isoformat(),
    }
    assert not job.street_needs_retry(recent, TODAY)


def test_build_entry_aproximado_nao_vira_rua():
    entry, kind = job.build_entry(
        {
            "status": "ok",
            "lat": -7.6,
            "lng": -72.6,
            "precisao": "aproximado",
            "fonte": "nominatim",
        },
        TODAY,
        attempts=1,
    )
    assert kind == "baixa_precisao"
    assert entry["status"] == "baixa_precisao"
    assert "lat" not in entry
    assert entry["proxima_tentativa"] == (TODAY + timedelta(days=90)).isoformat()


def test_run_queue_respeita_limite_e_salva(monkeypatch):
    calls = []
    saves = []

    def fake_geocode(*args, **kwargs):
        calls.append(kwargs)
        return {
            "status": "ok",
            "lat": -7.63,
            "lng": -72.68,
            "precisao": "rua",
            "fonte": "nominatim",
            "endereco_retornado": "Rua A, Cruzeiro do Sul, Acre, Brasil",
            "consulta": "A, Cruzeiro do Sul - AC, Brasil",
        }

    monkeypatch.setattr(job, "geocode_endereco", fake_geocode)
    targets = [
        _target("AC|CRUZEIRO DO SUL|RUA A"),
        _target("AC|CRUZEIRO DO SUL|RUA B", logradouro="RUA B"),
    ]
    cache = {"points": {}, "misses": {}, "ruas": {}}
    stats = job.run_queue(
        targets,
        cache,
        max_seconds=100,
        limit=1,
        searcher=object(),
        clock=lambda: 0.0,
        today=TODAY,
        save=lambda: saves.append(True),
    )
    assert stats["consultadas"] == 1
    assert stats["terminal"] == 1
    assert stats["rua"] == 1
    assert len(calls) == 1
    assert saves
    assert cache["ruas"]["AC|CRUZEIRO DO SUL|RUA A"]["precisao"] == "rua"


def test_run_queue_orcamento_zero_nao_consulta(monkeypatch):
    def fake_geocode(*args, **kwargs):
        raise AssertionError("não deveria consultar")

    monkeypatch.setattr(job, "geocode_endereco", fake_geocode)
    cache = {"points": {}, "misses": {}, "ruas": {}}
    stats = job.run_queue(
        [_target("AC|CRUZEIRO DO SUL|RUA A")],
        cache,
        max_seconds=0,
        today=TODAY,
        clock=lambda: 0.0,
    )
    assert stats["consultadas"] == 0
    assert stats["orcamento_esgotado"] is True


def test_run_queue_bairro_alimenta_points(monkeypatch):
    def fake_geocode(*args, **kwargs):
        return {
            "status": "ok",
            "lat": -7.6355,
            "lng": -72.6669,
            "precisao": "bairro",
            "fonte": "nominatim",
            "endereco_retornado": "Centro, Cruzeiro do Sul, Acre, Brasil",
            "consulta": "CENTRO, Cruzeiro do Sul - AC, Brasil",
        }

    monkeypatch.setattr(job, "geocode_endereco", fake_geocode)
    cache = {"points": {}, "misses": {}, "ruas": {}}
    stats = job.run_queue(
        [_target("AC|CRUZEIRO DO SUL|RUA A")],
        cache,
        max_seconds=100,
        today=TODAY,
        clock=lambda: 0.0,
    )
    assert stats["baixa_precisao"] == 1
    assert stats["bairros_adicionados"] == 1
    assert cache["ruas"]["AC|CRUZEIRO DO SUL|RUA A"]["status"] == "baixa_precisao"
    assert cache["points"]["AC|CRUZEIRO DO SUL|CENTRO"]["precisao"] == "bairro"


def test_run_queue_rate_limit_salva(monkeypatch):
    def fake_geocode(*args, **kwargs):
        raise geocode_client.RateLimitError("desacelere")

    monkeypatch.setattr(job, "geocode_endereco", fake_geocode)
    saves = []
    cache = {"points": {}, "misses": {}, "ruas": {}}
    stats = job.run_queue(
        [_target("AC|CRUZEIRO DO SUL|RUA A")],
        cache,
        max_seconds=100,
        today=TODAY,
        clock=lambda: 0.0,
        save=lambda: saves.append(True),
    )
    assert stats["limite_api"] is True
    assert stats["consultadas"] == 0
    assert saves
