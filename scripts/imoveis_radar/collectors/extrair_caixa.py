#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Baixa a lista completa de imóveis da Caixa pela tela de download.

A URL direta do CSV (``listaweb/Lista_imoveis_geral.csv``) fica atrás do
Radware Bot Manager e passou a devolver o mesmo arquivo por dias.  Este
coletor usa um Chromium real: abre ``/sistema/download-lista.asp``, escolhe
"Todos" e clica em "Próxima", capturando o download.

O CSV é gravado em ``SOURCE_OUTPUT_DIR/Lista_imoveis_geral.csv`` (mesmo nome
consumido pelo pipeline).  Sem download, sai com código != 0 e o pipeline
mantém a versão anterior.
"""
from __future__ import annotations

import logging
import os
import re
import sys
import time
from pathlib import Path

PAGINA = "https://venda-imoveis.caixa.gov.br/sistema/download-lista.asp"
SAIDA_DIR = Path(os.environ.get("SOURCE_OUTPUT_DIR", "reports"))
SAIDA = SAIDA_DIR / "Lista_imoveis_geral.csv"
TENTATIVAS = int(os.environ.get("CAIXA_TENTATIVAS", "2"))
TEMPO_DOWNLOAD_MS = int(os.environ.get("CAIXA_DOWNLOAD_TIMEOUT_MS", "120000"))
MIN_BYTES = int(os.environ.get("IMOVEIS_MIN_BYTES_CAIXA", "100000"))
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")


def _texto_contagem(page) -> str:
    try:
        return page.locator("body").inner_text(timeout=5000)[:400]
    except Exception:
        return ""


def _selecionar_todos(page) -> str | None:
    """Marca a opção "Todos" no select de estados.  Devolve o rótulo usado."""
    selects = page.locator("select")
    total = selects.count()
    for indice in range(total):
        select = selects.nth(indice)
        try:
            opcoes = select.locator("option")
            rotulos = [
                opcoes.nth(i).inner_text().strip()
                for i in range(min(opcoes.count(), 60))
            ]
        except Exception:
            continue
        for rotulo in rotulos:
            if re.fullmatch(r"todos?( os estados)?", rotulo, re.I):
                try:
                    select.select_option(label=rotulo)
                    logging.info("Estado selecionado: %s", rotulo)
                    return rotulo
                except Exception as erro:
                    logging.warning("Não consegui selecionar %r: %s", rotulo, erro)
    return None


def _clicar_proxima(page) -> bool:
    candidatos = [
        page.get_by_role("button", name=re.compile(r"pr[óo]xima", re.I)),
        page.get_by_role("link", name=re.compile(r"pr[óo]xima", re.I)),
        page.locator("input[type=submit][value*='róxima' i]"),
        page.locator("input[type=button][value*='róxima' i]"),
    ]
    for candidato in candidatos:
        try:
            if candidato.count():
                candidato.first.click(timeout=20000)
                logging.info("Clique em Próxima realizado.")
                return True
        except Exception as erro:
            logging.warning("Falha ao clicar em Próxima: %s", erro)
    return False


def _validar(caminho: Path) -> None:
    if not caminho.exists():
        raise RuntimeError(f"download não gerou {caminho}")
    tamanho = caminho.stat().st_size
    if tamanho < MIN_BYTES:
        raise RuntimeError(f"arquivo pequeno demais ({tamanho} bytes)")
    cabecalho = caminho.read_bytes()[:4096].decode("latin1", errors="ignore").lower()
    if "<html" in cabecalho or "captcha" in cabecalho or "radware" in cabecalho:
        raise RuntimeError("a Caixa devolveu HTML/CAPTCHA em vez do CSV")
    if "imóvel" not in cabecalho and "imovel" not in cabecalho:
        raise RuntimeError("CSV sem o cabeçalho esperado")


def geracao(caminho: Path) -> str | None:
    """Lê a ``Data de geração`` do CSV (YYYY-MM-DD) ou devolve None."""
    try:
        cabecalho = caminho.read_bytes()[:2048].decode("latin1", errors="ignore")
    except OSError:
        return None
    achado = re.search(r"Data de gera[cç][ãa]o[;:\s]*([0-9]{2}/[0-9]{2}/[0-9]{4})", cabecalho, re.I)
    if not achado:
        return None
    dia, mes, ano = achado.group(1).split("/")
    return f"{ano}-{mes}-{dia}"


def _manter_mais_novo(candidato: Path) -> bool:
    """True quando o candidato é mais antigo que o arquivo já salvo."""
    if not SAIDA.exists():
        return False
    atual, novo = geracao(SAIDA), geracao(candidato)
    if atual and novo and novo < atual:
        logging.warning(
            "Download de %s é mais antigo que o arquivo local (%s); mantendo o local.",
            novo,
            atual,
        )
        return True
    return False


def _salvar(resposta_bytes: bytes, destino: Path) -> None:
    temporario = destino.with_suffix(".tmp")
    temporario.write_bytes(resposta_bytes)
    os.replace(temporario, destino)


def baixar_uma_vez() -> Path:
    # Import tardio: o módulo precisa ser importável sem o Playwright (testes/CI).
    from playwright.sync_api import TimeoutError as PlaywrightTimeout
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        contexto = browser.new_context(
            locale="pt-BR",
            user_agent=USER_AGENT,
            viewport={"width": 1366, "height": 900},
        )
        page = contexto.new_page()
        respostas_csv: list[bytes] = []

        def guardar_resposta(response):
            try:
                tipo = (response.headers or {}).get("content-type", "")
                if "csv" in tipo.lower() or "octet-stream" in tipo.lower():
                    respostas_csv.append(response.body())
            except Exception:
                pass

        page.on("response", guardar_resposta)
        try:
            logging.info("Abrindo %s…", PAGINA)
            page.goto(PAGINA, wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(4000)

            corpo = _texto_contagem(page)
            if "captcha" in corpo.lower() or "bot manager" in corpo.lower():
                raise RuntimeError("Radware Bot Manager bloqueou o acesso (CAPTCHA)")

            page.wait_for_selector("select", timeout=60000)
            if not _selecionar_todos(page):
                logging.warning("Select de estado não encontrado; tentando sem selecionar.")

            try:
                with page.expect_download(timeout=TEMPO_DOWNLOAD_MS) as info:
                    if not _clicar_proxima(page):
                        raise RuntimeError("botão Próxima não encontrado")
                download = info.value
                temporario = SAIDA.with_suffix(".download")
                download.save_as(str(temporario))
                _validar(temporario)
                if _manter_mais_novo(temporario):
                    return SAIDA
                os.replace(temporario, SAIDA)
                logging.info("CSV salvo por download: %s", SAIDA)
                return SAIDA
            except PlaywrightTimeout:
                logging.warning("Nenhum download disparado; procurando link/CSV na página.")

            if respostas_csv:
                _salvar(max(respostas_csv, key=len), SAIDA)
                _validar(SAIDA)
                logging.info("CSV salvo pela resposta HTTP: %s", SAIDA)
                return SAIDA

            link = page.locator("a[href$='.csv'], a[href*='.csv?']")
            if link.count():
                url = link.first.get_attribute("href")
                logging.info("Baixando pelo link %s", url)
                resposta = contexto.request.get(url, timeout=TEMPO_DOWNLOAD_MS)
                if resposta.ok:
                    _salvar(resposta.body(), SAIDA)
                    _validar(SAIDA)
                    return SAIDA

            raise RuntimeError("não foi possível obter o CSV pela tela de download")
        finally:
            contexto.close()
            browser.close()


def main() -> int:
    SAIDA_DIR.mkdir(parents=True, exist_ok=True)
    ultimo_erro = None
    for tentativa in range(1, TENTATIVAS + 1):
        try:
            logging.info("Tentativa %s/%s de baixar a lista da Caixa…", tentativa, TENTATIVAS)
            caminho = baixar_uma_vez()
            logging.info("Lista da Caixa pronta: %s (%s bytes)", caminho, caminho.stat().st_size)
            return 0
        except Exception as erro:  # noqa: BLE001 - relatório, não exceção
            ultimo_erro = erro
            logging.error("Tentativa %s falhou: %s", tentativa, erro)
            if tentativa < TENTATIVAS:
                time.sleep(45 * tentativa)
    print(f"Falha ao baixar a lista da Caixa: {ultimo_erro}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
