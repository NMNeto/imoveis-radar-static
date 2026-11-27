from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from checar_fontes import check_summary  # noqa: E402
from enviar_alerta_email import build_message  # noqa: E402
from imoveis_radar import collect  # noqa: E402
from imoveis_radar.config import Paths, RunOptions  # noqa: E402

NOW = datetime(2026, 11, 27, 12, 0, 0)


def _summary(**fontes) -> dict:
    return {
        "data_atualizacao": "2026-11-27T11:30:00",
        "fontes": fontes,
    }


def test_stale_days_conta_dias_desde_a_geracao():
    assert collect.stale_days("2026-11-19", today=date(2026, 11, 27)) == 8
    assert collect.stale_days("2026-11-27T10:00:00", today=date(2026, 11, 27)) == 0
    assert collect.stale_days(None) is None
    assert collect.stale_days("data-invalida") is None


def test_stale_details_marca_atraso_acima_do_limite(monkeypatch):
    monkeypatch.setattr(collect, "date", _FixedDate)
    assert collect.stale_details("2026-11-26", 3) == {"stale_days": 1}
    detalhes = collect.stale_details("2026-11-19", 3)
    assert detalhes["desatualizado"] is True
    assert detalhes["stale_days"] == 8
    assert "8 dias" in detalhes["aviso"]


class _FixedDate(date):
    @classmethod
    def today(cls):
        return cls(2026, 11, 27)


def test_check_summary_sem_problemas():
    problemas = check_summary(
        _summary(caixa={"status": "ok", "stale_days": 1}),
        now=NOW,
        max_age_hours=0,
    )
    assert problemas == []


def test_check_summary_aponta_fonte_com_falha():
    problemas = check_summary(
        _summary(
            bb={
                "status": "falhou",
                "last_error": "RuntimeError: nenhum imóvel do BB foi coletado",
            }
        ),
        now=NOW,
    )
    assert [p.fonte for p in problemas] == ["bb"]
    assert problemas[0].motivo == "coleta falhou"
    assert "nunca" not in problemas[0].detalhe


def test_check_summary_aponta_csv_desatualizado():
    problemas = check_summary(
        _summary(caixa={"status": "ok", "desatualizado": True, "stale_days": 8}),
        now=NOW,
        max_stale_days=3,
    )
    assert [p.fonte for p in problemas] == ["caixa"]
    assert problemas[0].motivo == "dados desatualizados"
    assert "8" in problemas[0].detalhe


def test_check_summary_calcula_atraso_pela_data_de_geracao():
    problemas = check_summary(
        _summary(caixa={"status": "ok", "generation_date": "2026-11-19"}),
        now=NOW,
        max_stale_days=3,
    )
    assert [p.fonte for p in problemas] == ["caixa"]


def test_check_summary_ignora_fonte_configurada():
    problemas = check_summary(
        _summary(bb={"status": "falhou", "last_error": "x"}),
        now=NOW,
        ignore=("bb",),
    )
    assert problemas == []


def test_check_summary_verifica_parada_geral():
    problemas = check_summary(
        {"data_atualizacao": "2026-11-20T12:00:00", "fontes": {}},
        now=NOW,
        max_age_hours=30,
    )
    assert [p.fonte for p in problemas] == ["atualização"]
    assert problemas[0].motivo == "atualização parada"


def test_email_tem_assunto_e_corpo_uteis():
    resumo = _summary(
        bb={"status": "falhou", "last_error": "sem imóveis", "rows": 821},
        caixa={"status": "ok", "rows": 25223, "desatualizado": True, "stale_days": 8},
    )
    problemas = check_summary(resumo, now=NOW, max_stale_days=3)
    assunto, corpo = build_message(
        resumo, problemas, link="https://github.com/x/y/actions/runs/1"
    )
    assert "Falha na atualização" in assunto
    assert "bb" in assunto and "caixa" in assunto
    assert "coleta falhou" in corpo
    assert "dados desatualizados" in corpo
    assert "https://github.com/x/y/actions/runs/1" in corpo
    assert "nada foi apagado" in corpo


def test_run_collector_repete_ate_ter_sucesso(monkeypatch):
    tentativas = []

    def fake(source_id, paths, options, context, persist):
        tentativas.append(source_id)
        status = "ok" if len(tentativas) == 2 else "falhou"
        return collect.CollectedSource(source_id=source_id, status=status, last_error="x")

    monkeypatch.setattr(collect, "_run_collector_once", fake)
    options = RunOptions(sources=("bb",), collector_attempts=2, collector_retry_delay=0)
    status = collect.run_collector(
        "bb", Paths(), options, collect.CollectionContext(), persist=False
    )
    assert status.ok
    assert len(tentativas) == 2


def test_run_collector_desiste_apos_o_limite(monkeypatch):
    tentativas = []

    def fake(source_id, paths, options, context, persist):
        tentativas.append(source_id)
        return collect.CollectedSource(source_id=source_id, status="falhou", last_error="x")

    monkeypatch.setattr(collect, "_run_collector_once", fake)
    options = RunOptions(sources=("bb",), collector_attempts=3, collector_retry_delay=0)
    status = collect.run_collector(
        "bb", Paths(), options, collect.CollectionContext(), persist=False
    )
    assert not status.ok
    assert len(tentativas) == 3
