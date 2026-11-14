#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Coletor Santander Imóveis (API pública usada pelo portal).

Derivado do coletor original do projeto Imóveis Radar, sem as etapas de
filtragem/Excel.  A saída é o CSV estável consumido pelo atualizador.
"""
from __future__ import annotations

import asyncio
import csv
import logging
import os
import re
import tempfile
from datetime import datetime

from playwright.async_api import async_playwright

BASE = "https://www.santanderimoveis.com.br"
BUSCA_URL = BASE + "/buscar-imoveis?aba=1"
IMOVEL_URL = BASE + "/details/{id}"
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/158.0.0.0 Safari/537.36"
)

API_PROPS = "https://api.shi.santander.com.br/v1/real_estate_auctions/real_estate_properties"
# Chave pública usada pelo front-end do portal (não é um segredo do usuário).
# Pode ser sobrescrita por SANTANDER_API_KEY sem editar o código.
API_KEY = os.environ.get(
    "SANTANDER_API_KEY", "d9ffca1a-71af-48e4-bece-8bc852455cd7"
)
API_PAGE_SIZE = 1000

DATE_PREFIX = os.environ.get("SOURCE_DATE_PREFIX", datetime.now().strftime("%Y.%m.%d_"))
REPORTS_DIR = os.environ.get("SOURCE_OUTPUT_DIR", "reports")
ARQUIVO_CSV = os.path.join(REPORTS_DIR, f"{DATE_PREFIX}santander_imoveis_geral.csv")

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

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

FETCH_JS = """
async ({ api, key, offset, limit }) => {
    const url = `${api}?_offset=${offset}&_limit=${limit}`;
    const resposta = await fetch(url, {
        headers: { 'x-api-key': key, 'Accept': 'application/json' }
    });
    if (!resposta.ok) {
        return { status: resposta.status, content: [], total: 0 };
    }
    const json = await resposta.json();
    return {
        status: resposta.status,
        content: json.content || [],
        total: json.pagination ? json.pagination.totalElements : (json.content || []).length,
    };
}
"""


async def coletar_imoveis():
    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(
                headless=True,
                channel="chromium",
                args=["--disable-blink-features=AutomationControlled"],
            )
        except Exception:
            browser = await p.chromium.launch(headless=True)

        context = await browser.new_context(
            locale="pt-BR", user_agent=UA, viewport={"width": 1366, "height": 900}
        )
        try:
            page = await context.new_page()
            logging.info("Abrindo %s ...", BUSCA_URL)
            await page.goto(BUSCA_URL, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(6000)

            imoveis = []
            pagina = 0
            total = None
            while True:
                lote = await page.evaluate(
                    FETCH_JS,
                    {
                        "api": API_PROPS,
                        "key": API_KEY,
                        "offset": pagina,
                        "limit": API_PAGE_SIZE,
                    },
                )
                conteudo = lote.get("content") or []
                total = lote.get("total") or len(conteudo)
                if lote.get("status") != 200:
                    logging.error("API respondeu %s.", lote.get("status"))
                    break
                if not conteudo:
                    break
                imoveis.extend(conteudo)
                logging.info("API: %s/%s imóveis coletados.", len(imoveis), total)
                if len(imoveis) >= total:
                    break
                pagina += 1
                if pagina > 100:
                    logging.warning("Limite de segurança de páginas atingido.")
                    break
            return imoveis
        finally:
            await browser.close()


def limpar(texto):
    return re.sub(r"\s+", " ", str(texto or "")).strip()


def moeda_br(valor):
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return ""
    if numero <= 0:
        return ""
    return f"{numero:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def primeira_imagem(item):
    imagens = [
        image
        for image in (item.get("images") or [])
        if image.get("isPublished", True) and image.get("imageUrl")
    ]
    if not imagens:
        return ""
    capa = [image for image in imagens if image.get("isCoverImage")]
    escolhidas = sorted(capa or imagens, key=lambda image: image.get("displayOrder") or 9999)
    return escolhidas[0]["imageUrl"]


def mapear_imoveis(itens):
    resultados = []
    for item in itens:
        endereco = item.get("postalAddress") or {}
        estado = endereco.get("state") or {}
        cidade = endereco.get("city") or {}
        venda = item.get("saleInformation") or {}
        tipo_venda = venda.get("saleType") or {}
        financas = item.get("financialInformation") or {}

        preco = (venda.get("minimumSalePrice") or {}).get("amount")
        if not preco:
            preco = (venda.get("salePrice") or {}).get("amount")
        if not preco:
            preco = (venda.get("initialSalePrice") or {}).get("amount")

        valor = (financas.get("marketValue") or {}).get("amount")
        if not valor:
            valor = (financas.get("liquidityValue") or {}).get("amount")
        if not valor:
            valor = (financas.get("assessedValue") or {}).get("amount")

        desconto = financas.get("discountRate")
        rua = limpar(endereco.get("streetName"))
        numero = limpar(endereco.get("streetBuildingIdentification"))
        complemento = limpar(endereco.get("mailDeliverySubLocation"))
        partes_endereco = [
            p
            for p in (rua, numero, complemento)
            if p and p.upper() not in ("S/N", "0", "SN")
        ]
        endereco_completo = " ".join(partes_endereco) if partes_endereco else rua

        descricao = limpar(item.get("description"))
        detalhada = limpar(item.get("detailedDescription"))
        if detalhada:
            descricao = f"{descricao} {detalhada}".strip()

        imovel_id = item.get("realEstatePropertyId")
        resultados.append(
            {
                "Nº do imóvel": limpar(item.get("dossierNumber")) or str(imovel_id or ""),
                "UF": limpar(estado.get("stateCode")),
                "Cidade": limpar(cidade.get("cityName") or endereco.get("townName")),
                "Bairro": limpar(endereco.get("districtName")),
                "Endereço": endereco_completo,
                "Preço": moeda_br(preco),
                "Valor de avaliação": moeda_br(valor),
                "Desconto": f"{desconto}%" if desconto not in (None, "") else "",
                "Financiamento": "",
                "Descrição": descricao,
                "Modalidade de venda": limpar(tipo_venda.get("saleTypeDescription")),
                "Link de acesso": IMOVEL_URL.format(id=imovel_id) if imovel_id else "",
                "Imagem": primeira_imagem(item),
            }
        )
    logging.info("Dados convertidos: %s imóveis.", len(resultados))
    return resultados


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


def main():
    os.makedirs(REPORTS_DIR, exist_ok=True)
    itens = asyncio.run(coletar_imoveis())
    if not itens:
        raise RuntimeError("nenhum imóvel do Santander foi coletado")
    resultados = mapear_imoveis(itens)
    salvar_csv(resultados)


if __name__ == "__main__":
    main()
