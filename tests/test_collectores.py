from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from imoveis_radar import collect  # noqa: E402
from imoveis_radar.collect import CollectedSource  # noqa: E402
from imoveis_radar.collectors import extrair_bb, extrair_caixa  # noqa: E402
from imoveis_radar.config import Paths, RunOptions  # noqa: E402


def _fonte(status: str, geracao: str | None = None) -> CollectedSource:
    return CollectedSource(
        source_id="caixa",
        status=status,
        details={"generation_date": geracao} if geracao else {},
    )


def test_mais_recente_aceita_arquivo_com_geracao_maior():
    atual = _fonte("ok", "2026-11-19")
    novo = _fonte("ok", "2026-11-27")
    assert collect._mais_recente(novo, atual)
    assert not collect._mais_recente(atual, novo)


def test_mais_recente_aceita_quando_o_atual_falhou():
    assert collect._mais_recente(_fonte("ok", "2026-11-19"), _fonte("falhou"))


def test_mais_recente_recusa_alternativa_com_falha():
    assert not collect._mais_recente(_fonte("falhou"), _fonte("ok", "2026-11-19"))


def test_mais_recente_recusa_arquivo_sem_data():
    assert not collect._mais_recente(_fonte("ok"), _fonte("ok", "2026-11-19"))


def test_id_do_link_extrai_o_numero_do_imovel():
    assert extrair_bb.id_do_link("https://www.seuimovelbb.com.br/imovel/id/90756") == "90756"
    assert extrair_bb.id_do_link("https://x/imovel/id/123?utm=1") == "123"
    assert extrair_bb.id_do_link("") == ""


def test_pode_reaproveitar_quando_preco_e_avaliacao_nao_mudaram():
    anterior = {
        "Preço": "100.000,00",
        "Valor de avaliação": "120.000,00",
        "Endereço": "Rua A, 10",
    }
    cartao = {"valor": "R$ 100.000,00", "avaliacao": "R$ 120.000,00"}
    assert extrair_bb.pode_reaproveitar(anterior, cartao)


def test_pode_reaproveitar_recusa_quando_preco_mudou():
    anterior = {"Preço": "100.000,00", "Valor de avaliação": "120.000,00", "Endereço": "Rua A"}
    cartao = {"valor": "R$ 90.000,00", "avaliacao": "R$ 120.000,00"}
    assert not extrair_bb.pode_reaproveitar(anterior, cartao)


def test_pode_reaproveitar_recusa_quando_avaliacao_mudou():
    anterior = {"Preço": "100.000,00", "Valor de avaliação": "120.000,00", "Endereço": "Rua A"}
    cartao = {"valor": "R$ 100.000,00", "avaliacao": "R$ 130.000,00"}
    assert not extrair_bb.pode_reaproveitar(anterior, cartao)


def test_pode_reaproveitar_recusa_sem_detalhe_anterior():
    assert not extrair_bb.pode_reaproveitar(None, {"valor": "R$ 1,00"})
    assert not extrair_bb.pode_reaproveitar({"Preço": "1,00"}, {"valor": "R$ 1,00"})


def test_carregar_anteriores_indexa_pelo_numero(tmp_path):
    caminho = tmp_path / "imoveis_bb_geral.csv"
    caminho.write_text(
        "Nº do imóvel;UF;Cidade;Preço;Link de acesso\n"
        "90756;GO;Santo Antônio;16.860,00;https://x/imovel/id/90756\n",
        encoding="utf-8-sig",
    )
    anteriores = extrair_bb.carregar_anteriores(str(caminho))
    assert anteriores["90756"]["Preço"] == "16.860,00"
    assert anteriores["90756"]["Cidade"] == "Santo Antônio"
    assert set(anteriores["90756"]) == set(extrair_bb.CAMPOS)


def test_carregar_anteriores_sem_arquivo():
    assert extrair_bb.carregar_anteriores("") == {}
    assert extrair_bb.carregar_anteriores("/caminho/que/nao/existe.csv") == {}


def test_validar_aceita_csv_da_caixa(tmp_path, monkeypatch):
    monkeypatch.setattr(extrair_caixa, "MIN_BYTES", 10)
    caminho = tmp_path / "Lista_imoveis_geral.csv"
    caminho.write_bytes(
        (
            "Lista de Imóveis da Caixa;;Data de geração:;27/11/2026\n"
            "N° do imóvel;UF;Cidade;Bairro;Endereço;Preço\n"
        ).encode("latin1")
    )
    extrair_caixa._validar(caminho)


def test_validar_recusa_html(tmp_path, monkeypatch):
    monkeypatch.setattr(extrair_caixa, "MIN_BYTES", 10)
    caminho = tmp_path / "Lista_imoveis_geral.csv"
    caminho.write_bytes(b"<html><title>Radware Bot Manager CAPTCHA</title></html>")
    with pytest.raises(RuntimeError, match="HTML/CAPTCHA"):
        extrair_caixa._validar(caminho)


def test_validar_recusa_arquivo_pequeno(tmp_path, monkeypatch):
    monkeypatch.setattr(extrair_caixa, "MIN_BYTES", 100)
    caminho = tmp_path / "Lista_imoveis_geral.csv"
    caminho.write_bytes(b"N\xb0 do im\xf3vel;UF\n")
    with pytest.raises(RuntimeError, match="pequeno"):
        extrair_caixa._validar(caminho)


def test_validar_recusa_arquivo_ausente(tmp_path):
    with pytest.raises(RuntimeError, match="não gerou"):
        extrair_caixa._validar(tmp_path / "nao-existe.csv")


def _coleta_caixa(monkeypatch, tmp_path, direto, alternativo):
    from imoveis_radar import collect as coletor

    monkeypatch.setattr(coletor, "download_caixa", lambda *a, **k: direto)
    monkeypatch.setattr(coletor, "_run_collector_once", lambda *a, **k: alternativo)
    monkeypatch.setattr(coletor, "_write_source_status", lambda *a, **k: None)
    paths = Paths(root=tmp_path, data=tmp_path / "data", public=tmp_path / "public")
    options = RunOptions(sources=("caixa",), skip_collect=False)
    statuses, _ = coletor.collect_all(
        paths, options, coletor.CollectionContext(), persist=False
    )
    return statuses["caixa"]


def test_caixa_troca_pelo_fluxo_do_navegador_quando_o_csv_esta_velho(monkeypatch, tmp_path):
    direto = _fonte("ok", "2026-11-19")
    direto.details["desatualizado"] = True
    alternativo = _fonte("ok", "2026-11-27")
    escolhido = _coleta_caixa(monkeypatch, tmp_path, direto, alternativo)
    assert escolhido.details["generation_date"] == "2026-11-27"


def test_caixa_mantem_o_csv_direto_quando_o_alternativo_e_mais_antigo(monkeypatch, tmp_path):
    direto = _fonte("ok", "2026-11-27")
    direto.details["desatualizado"] = True
    alternativo = _fonte("ok", "2026-11-19")
    escolhido = _coleta_caixa(monkeypatch, tmp_path, direto, alternativo)
    assert escolhido.details["generation_date"] == "2026-11-27"


def test_caixa_nao_tenta_navegador_quando_o_csv_esta_em_dia(monkeypatch, tmp_path):
    from imoveis_radar import collect as coletor

    chamadas = []

    def alternativo(*a, **k):
        chamadas.append(1)
        return _fonte("ok", "2026-11-27")

    direto = _fonte("ok", "2026-11-27")
    escolhido = _coleta_caixa(monkeypatch, tmp_path, direto, alternativo)
    assert chamadas == []
    assert escolhido is direto


CAIXA_CSV = (
    "Lista de Imóveis da Caixa;;Data de geração:;{data};;;;;;;\n"
    "N° do imóvel;UF;Cidade;Bairro;Endereço;Preço;Valor de avaliação;"
    "Desconto;Financiamento;Descrição;Modalidade de venda;Link de acesso\n"
    "123;RJ;Rio de Janeiro;Centro;Rua A;100.000,00;120.000,00;10%;Sim;casa;"
    "Venda direta;http://x\n"
)


def _csv_caixa(data: str) -> bytes:
    return CAIXA_CSV.format(data=data).encode("latin1")


class _Resposta:
    status_code = 200

    def __init__(self, content: bytes):
        self.content = content

    def raise_for_status(self):
        return None


def _opcoes_caixa(**kwargs) -> RunOptions:
    base = dict(
        sources=("caixa",),
        allow_source_drop=True,
        http_retries=1,
        min_caixa_bytes=10,
        max_stale_days=3,
    )
    base.update(kwargs)
    return RunOptions(**base)


def test_download_caixa_nao_sobrescreve_arquivo_mais_novo(monkeypatch, tmp_path):
    from imoveis_radar import collect as coletor

    paths = Paths(root=tmp_path, data=tmp_path / "data", public=tmp_path / "public")
    alvo = paths.raw_csv("caixa")
    alvo.parent.mkdir(parents=True)
    alvo.write_bytes(_csv_caixa("27/11/2026"))

    monkeypatch.setattr(
        coletor.requests, "get", lambda *a, **k: _Resposta(_csv_caixa("19/11/2026"))
    )
    contexto = coletor.CollectionContext()
    try:
        status = coletor.download_caixa(paths, _opcoes_caixa(), contexto, persist=True)
    finally:
        contexto.cleanup()

    assert status.ok
    assert status.details["download_ignorado"] == "2026-11-19"
    assert status.details["generation_date"] == "2026-11-27"
    assert b"27/11/2026" in alvo.read_bytes()


def test_download_caixa_aceita_arquivo_mais_novo(monkeypatch, tmp_path):
    from imoveis_radar import collect as coletor

    paths = Paths(root=tmp_path, data=tmp_path / "data", public=tmp_path / "public")
    alvo = paths.raw_csv("caixa")
    alvo.parent.mkdir(parents=True)
    alvo.write_bytes(_csv_caixa("19/11/2026"))

    monkeypatch.setattr(
        coletor.requests, "get", lambda *a, **k: _Resposta(_csv_caixa("27/11/2026"))
    )
    contexto = coletor.CollectionContext()
    try:
        status = coletor.download_caixa(paths, _opcoes_caixa(), contexto, persist=True)
    finally:
        contexto.cleanup()

    assert status.ok
    assert "download_ignorado" not in status.details
    assert status.details["generation_date"] == "2026-11-27"
    assert b"27/11/2026" in alvo.read_bytes()


def test_geracao_extrai_a_data_do_csv_da_caixa(tmp_path):
    caminho = tmp_path / "Lista_imoveis_geral.csv"
    caminho.write_bytes(_csv_caixa("27/11/2026"))
    assert extrair_caixa.geracao(caminho) == "2026-11-27"
    assert extrair_caixa.geracao(tmp_path / "nao-existe.csv") is None


def test_coletor_da_caixa_nao_sobrescreve_arquivo_mais_novo(tmp_path, monkeypatch):
    salvo = tmp_path / "Lista_imoveis_geral.csv"
    salvo.write_bytes(_csv_caixa("27/11/2026"))
    candidato = tmp_path / "candidato.download"
    candidato.write_bytes(_csv_caixa("19/11/2026"))
    monkeypatch.setattr(extrair_caixa, "SAIDA", salvo)
    assert extrair_caixa._manter_mais_novo(candidato) is True
    assert b"27/11/2026" in salvo.read_bytes()


def test_coletor_da_caixa_aceita_candidato_mais_novo(tmp_path, monkeypatch):
    salvo = tmp_path / "Lista_imoveis_geral.csv"
    salvo.write_bytes(_csv_caixa("19/11/2026"))
    candidato = tmp_path / "candidato.download"
    candidato.write_bytes(_csv_caixa("27/11/2026"))
    monkeypatch.setattr(extrair_caixa, "SAIDA", salvo)
    assert extrair_caixa._manter_mais_novo(candidato) is False
