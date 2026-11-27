#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Coletor de imóveis urbanos do Seu Imóvel BB.

Derivado do coletor original do projeto Imóveis Radar, sem as etapas de
filtragem/Excel: aqui só coletamos e gravamos o CSV estável consumido pelo
atualizador.  O diretório de saída vem de ``SOURCE_OUTPUT_DIR``.
"""
from __future__ import annotations

import asyncio
import csv
import logging
import os
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.seuimovelbb.com.br"
CATALOGO = BASE_URL + "/catalogo/categoria/urbanos"

DATE_PREFIX = os.environ.get("SOURCE_DATE_PREFIX", datetime.now().strftime("%Y.%m.%d_"))
REPORTS_DIR = os.environ.get("SOURCE_OUTPUT_DIR", "reports")
ARQUIVO_CSV = os.path.join(REPORTS_DIR, f"{DATE_PREFIX}imoveis_bb_geral.csv")
#: CSV da coleta anterior, para reaproveitar detalhes de imóveis inalterados.
ANTERIOR_CSV = os.environ.get("SOURCE_PREVIOUS_CSV", "")
MAX_IMOVEIS = int(os.environ["MAX_IMOVEIS"]) if os.environ.get("MAX_IMOVEIS") else None
DETALHE_WORKERS = 2

CAMPOS = [
    "Nº do imóvel",
    "UF",
    "Cidade",
    "Bairro",
    "Endereço",
    "Preço",
    "Valor de avaliação",
    "Desconto",
    "Financiamento",
    "Descrição",
    "Modalidade de venda",
    "Link de acesso",
    "Imagem",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/158.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")


def limpar(texto):
    return re.sub(r"\s+", " ", texto or "").strip()


def capturar(regex, texto, grupo=1):
    resultado = re.search(regex, texto, re.I | re.S)
    return limpar(resultado.group(grupo)) if resultado else ""


async def configurar_paginacao(page):
    try:
        await page.locator(".por-pagina a.dropdown-toggle").first.click()
        await page.wait_for_timeout(400)
        await page.get_by_role("link", name="200", exact=True).click()
        await page.wait_for_timeout(3500)
        await page.wait_for_selector(".card.carta", timeout=45000)
        logging.info("Paginação configurada para 200 imóveis por página.")
    except Exception as erro:
        logging.warning("Não foi possível configurar 200 por página: %s", erro)


async def abrir_catalogo(page, tentativas=6):
    """Abre a listagem e espera o filtro assíncrono popular os cartões."""
    for tentativa in range(1, tentativas + 1):
        await page.goto(CATALOGO, wait_until="domcontentloaded", timeout=60000)
        try:
            await page.wait_for_function(
                "() => { const el = document.querySelector('#contagem');"
                " return el && /Encontramos|Nenhum/i.test(el.innerText); }",
                timeout=45000,
            )
        except Exception as erro:
            logging.warning("Contagem não apareceu (tentativa %s): %s", tentativa, erro)
        try:
            texto = (await page.locator("#contagem").inner_text()).strip()
        except Exception:
            texto = ""
        if "Encontramos" in texto:
            logging.info("Catálogo aberto: %s", texto)
            return True
        logging.warning(
            "Catálogo sem imóveis (tentativa %s/%s): %s",
            tentativa,
            tentativas,
            texto or "sem contagem",
        )
        # O portal responde "Nenhum Imóvel" por 1-4 min quando limita o IP
        # (medido em 27/11). As esperas crescem para atravessar o bloqueio.
        if tentativa >= tentativas:
            break
        espera = {1: 3, 2: 10, 3: 30, 4: 90, 5: 180}.get(tentativa, 180)
        logging.warning("Aguardando %ss antes de tentar de novo…", espera)
        await page.wait_for_timeout(espera * 1000)
    return False


async def coletar_cards(page):
    cards = await page.locator(".card.carta").evaluate_all(
        """
        els => els.map(c => {
            const link = c.querySelector('a[href*="/imovel/id/"]');
            const visiveis = [...c.querySelectorAll('.leilao')]
                .filter(x => !x.classList.contains('d-none'))
                .map(x => x.innerText.trim())
                .filter(Boolean);
            return {
                url: link ? link.href : '',
                valor: (c.querySelector('.valor') || {}).innerText || '',
                rotulo: (c.querySelector('.valor-rotulo') || {}).innerText || '',
                avaliacao: (c.querySelector('.avaliacao') || {}).innerText || '',
                localidade: (c.querySelector('.localidade') || {}).innerText || '',
                modalidade: visiveis.join(' | '),
                tipo: (c.querySelector('.tipo') || {}).innerText || '',
            };
        })
        """
    )
    encontrados = {}
    for card in cards:
        url = (card.get("url") or "").split("?")[0]
        if "/imovel/id/" in url:
            encontrados[url] = card
    return encontrados


async def proxima_pagina(page):
    try:
        botao = page.locator("#paginacao a.page-link-next").last
        if not await botao.count():
            return False
        classes = await botao.locator("xpath=..").get_attribute("class") or ""
        if "disabled" in classes:
            return False
        anterior = await page.locator(".card.carta a[href*='/imovel/id/']").first.get_attribute("href")
        await page.wait_for_timeout(1200)
        await botao.click()
        await page.wait_for_function(
            """(anterior) => {
                const link = document.querySelector(".card.carta a[href*='/imovel/id/']");
                return link && link.getAttribute('href') !== anterior;
            }""",
            arg=anterior,
            timeout=45000,
        )
        return True
    except Exception as erro:
        logging.warning("Não foi possível avançar de página: %s", erro)
        return False


async def coletar_catalogo(page):
    todos = {}
    if not await abrir_catalogo(page):
        return todos
    await configurar_paginacao(page)
    pagina = 1
    while True:
        cards = await coletar_cards(page)
        anteriores = len(todos)
        todos.update(cards)
        logging.info(
            "Página %s: %s cartões; total acumulado: %s",
            pagina,
            len(cards),
            len(todos),
        )
        if len(todos) == anteriores and pagina > 1:
            logging.warning("Nenhum imóvel novo nesta página.")
        if not await proxima_pagina(page):
            break
        pagina += 1
        if pagina > 100:
            logging.warning("Limite de segurança de páginas atingido.")
            break
    return todos


def extrair_imagem(soup, url):
    for link in soup.select("a[data-fancybox]"):
        href = link.get("href") or ""
        if "/imagem/imovel/" in href:
            return urljoin(BASE_URL, href)
    og_image = soup.find("meta", attrs={"property": "og:image"})
    if og_image and og_image.get("content"):
        return urljoin(BASE_URL, og_image["content"])
    for image in soup.find_all("img"):
        src = image.get("src") or image.get("data-src") or image.get("data-lazy-src") or ""
        classes = " ".join(image.get("class") or [])
        if "/imagem/imovel/" in src and "card-img-top" not in classes:
            return urljoin(BASE_URL, src)
    return ""


def baixar_detalhe_texto(session, url):
    try:
        resposta = session.get(url, headers=HEADERS, timeout=30)
        resposta.raise_for_status()
        soup = BeautifulSoup(resposta.text, "html.parser")
        imagem = extrair_imagem(soup, url)
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        return {"texto": soup.get_text("\n"), "imagem": imagem}
    except Exception as erro:
        logging.error("Falha ao baixar %s: %s", url, erro)
        return None


def baixar_detalhes(urls):
    textos = {}

    def tarefa(url):
        with requests.Session() as session:
            return url, baixar_detalhe_texto(session, url)

    with ThreadPoolExecutor(max_workers=DETALHE_WORKERS) as executor:
        futuros = {executor.submit(tarefa, url): url for url in urls}
        for indice, futuro in enumerate(as_completed(futuros), start=1):
            url, texto = futuro.result()
            textos[url] = texto
            if indice % 50 == 0 or indice == len(urls):
                logging.info("Detalhes baixados: %s/%s", indice, len(urls))
    return textos


def extrair_dados(texto, url, card=None, image_url=""):
    card = card or {}
    texto = texto or ""
    dados = {campo: "" for campo in CAMPOS}

    modalidade_card = card.get("modalidade", "")
    dados["Nº do imóvel"] = (
        capturar(r"\bID\s*:?\s*(\d+)", modalidade_card)
        or capturar(r"\bID\s*:?\s*(\d+)", texto)
        or capturar(r"/imovel/id/(\d+)", url)
    )

    preco_card = capturar(r"R\$\s*([\d.]+,\d{2})", card.get("valor", ""))
    preco_detalhe = capturar(
        r"R\$\s*([\d.]+,\d{2})\s*Valor\s+(?:para proposta|de lance inicial)",
        texto,
    )
    dados["Preço"] = preco_card or preco_detalhe or "0,00"

    modalidade = re.search(
        r"(Venda\s+direta|Leil[ãa]o|Licita[çc][ãa]o)", modalidade_card or texto, re.I
    )
    if modalidade:
        dados["Modalidade de venda"] = limpar(modalidade.group(1)).capitalize()

    localidade = limpar(card.get("localidade", ""))
    match = re.search(r"(.+?)\s*-\s*([A-Z]{2})\s*$", localidade)
    if match:
        dados["Cidade"] = limpar(match.group(1))
        dados["UF"] = match.group(2)

    endereco = capturar(
        r"(?:situad[oa]|localizad[oa])\s+(?:na|no|à|em)\s+(.+?)"
        r"(?=,\s*Munic[ií]pio|,\s*melhor descrito|\.\s*Melhor descrito|Descrição legal|$)",
        texto,
    )
    localizacao = capturar(
        r"Localiza[çc][ãa]o\s*:\s*(.+?)(?=,\s*CEP|\s*Obs\.|\s*Observações|$)", texto
    )
    if localizacao:
        partes = [p.strip() for p in localizacao.split(",") if p.strip()]
        if partes and re.search(r"-\s*[A-Z]{2}$", partes[-1]):
            partes = partes[:-1]
        if len(partes) >= 2:
            dados["Bairro"] = partes[-1]
            localizacao = ", ".join(partes[:-1])
        elif partes:
            localizacao = partes[0]

    dados["Endereço"] = endereco or localizacao

    if not dados["Bairro"]:
        dados["Bairro"] = capturar(
            r"\b(?:no\s+)?bairro\s*:?\s*([A-ZÀ-Ú][^,;\n]{1,60}?)"
            r"(?=[,;\n]|\.\s+(?=(?-i:[A-ZÀ-Ú])[a-zà-ú])|$)",
            texto,
        )

    dados["Endereço"] = re.sub(
        r"[,;]?\s*(?:no\s+)?bairro\s+[^,;]+", "", dados["Endereço"], flags=re.I
    )
    dados["Endereço"] = re.sub(r"\s{2,}", " ", dados["Endereço"]).strip(" ,;")

    dados["Valor de avaliação"] = (
        capturar(
            r"(?:valor\s+de\s+avalia[çc][ãa]o|avalia[çc][ãa]o)\s*:?\s*R?\$?\s*([\d.]+,\d{2})",
            texto,
        )
        or capturar(r"R\$\s*([\d.]+,\d{2})", card.get("avaliacao", ""))
    )
    dados["Desconto"] = (
        capturar(r"desconto\s*:?\s*([\d.,]+\s*%)", texto)
        or capturar(r"([\d.,]+\s*%)\s*de\s*desconto", texto)
    )

    if re.search(r"n[ãa]o\s+aceita\s+financiamento|sem\s+financiamento", texto, re.I):
        dados["Financiamento"] = "Não"
    elif re.search(r"aceita\s+financiamento|financiamento\s+imobiliário", texto, re.I):
        dados["Financiamento"] = "Sim"

    dados["Descrição"] = capturar(
        r"Descri[çc][ãa]o\s*:?\s*(.+?)(?=\s*Localiza[çc][ãa]o\s*:|\s*Obs\.|\s*Observações|$)",
        texto,
    )
    dados["Link de acesso"] = url
    dados["Imagem"] = image_url
    return dados


def id_do_link(url):
    return capturar(r"/imovel/id/(\d+)", url or "")


def carregar_anteriores(caminho):
    """Lê o CSV anterior e indexa por número do imóvel."""
    if not caminho or not os.path.exists(caminho):
        return {}
    anteriores = {}
    try:
        with open(caminho, encoding="utf-8-sig", newline="") as arquivo:
            for linha in csv.DictReader(arquivo, delimiter=";"):
                registro = {campo: (linha.get(campo) or "") for campo in CAMPOS}
                chave = (linha.get("Nº do imóvel") or "").strip()
                if chave:
                    anteriores[chave] = registro
                # O catálogo identifica o imóvel pelo ID da URL, que é diferente
                # do "Nº do imóvel" do Banco do Brasil.  Indexa os dois.
                chave_link = id_do_link(linha.get("Link de acesso") or "")
                if chave_link:
                    anteriores.setdefault(chave_link, registro)
    except OSError as erro:
        logging.warning("Não foi possível ler a coleta anterior: %s", erro)
    return anteriores


def pode_reaproveitar(anterior, card):
    """Reaproveita o detalhe quando preço e avaliação do cartão não mudaram."""
    if not anterior:
        return False
    if not anterior.get("Preço") or not anterior.get("Endereço"):
        return False
    preco = capturar(r"R\$\s*([\d.]+,\d{2})", (card or {}).get("valor", ""))
    if preco and preco != anterior.get("Preço"):
        return False
    avaliacao = capturar(r"R\$\s*([\d.]+,\d{2})", (card or {}).get("avaliacao", ""))
    if avaliacao and avaliacao != anterior.get("Valor de avaliação"):
        return False
    return True


def salvar_csv(dados):
    directory = os.path.dirname(ARQUIVO_CSV) or "."
    os.makedirs(directory, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", newline="", encoding="utf-8-sig", dir=directory, delete=False
    ) as arquivo:
        escritor = csv.DictWriter(
            arquivo, fieldnames=CAMPOS, delimiter=";", extrasaction="ignore"
        )
        escritor.writeheader()
        escritor.writerows(dados)
        temp_name = arquivo.name
    os.replace(temp_name, ARQUIVO_CSV)
    logging.info("CSV salvo: %s", ARQUIVO_CSV)


async def coletar():
    # Import tardio: os testes e o validador não precisam do Playwright instalado.
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(locale="pt-BR")
        try:
            logging.info("Coletando catálogo de imóveis urbanos do BB...")
            return await coletar_catalogo(page)
        finally:
            await browser.close()


def main():
    os.makedirs(REPORTS_DIR, exist_ok=True)
    cards = asyncio.run(coletar())
    logging.info("Total de imóveis no catálogo: %s", len(cards))
    if not cards:
        raise RuntimeError("nenhum imóvel do BB foi coletado")

    urls = list(cards.keys())
    if MAX_IMOVEIS:
        urls = urls[:MAX_IMOVEIS]
        logging.info("Limitando a coleta a %s imóveis (MAX_IMOVEIS).", MAX_IMOVEIS)

    anteriores = carregar_anteriores(ANTERIOR_CSV)
    resultados, a_baixar = [], []
    for url in urls:
        anterior = anteriores.get(id_do_link(url))
        if pode_reaproveitar(anterior, cards[url]):
            linha = dict(anterior)
            linha["Link de acesso"] = url
            resultados.append(linha)
        else:
            a_baixar.append(url)
    logging.info(
        "Detalhes reaproveitados: %s; para baixar: %s",
        len(resultados),
        len(a_baixar),
    )

    textos = baixar_detalhes(a_baixar)
    falhas = 0
    for indice, url in enumerate(a_baixar, start=1):
        detalhe = textos.get(url) or {}
        if not detalhe.get("texto"):
            anterior = anteriores.get(id_do_link(url))
            if anterior:
                linha = dict(anterior)
                linha["Link de acesso"] = url
                resultados.append(linha)
            else:
                falhas += 1
                logging.warning("Detalhe indisponível e sem versão anterior: %s", url)
            continue
        resultados.append(
            extrair_dados(
                detalhe.get("texto", ""),
                url,
                cards[url],
                detalhe.get("imagem", ""),
            )
        )
        if indice % 50 == 0 or indice == len(a_baixar):
            logging.info("Extraindo %s/%s", indice, len(a_baixar))
            salvar_csv(resultados)

    if falhas and falhas > max(2, len(a_baixar) * 0.2):
        raise RuntimeError(
            f"{falhas} de {len(a_baixar)} detalhes falharam; mantendo a coleta anterior"
        )

    unicos = {}
    for item in resultados:
        chave = item["Nº do imóvel"] or item["Link de acesso"]
        unicos[chave] = item
    resultados = list(unicos.values())
    salvar_csv(resultados)
    logging.info("Extração concluída: %s imóveis únicos.", len(resultados))


if __name__ == "__main__":
    main()
