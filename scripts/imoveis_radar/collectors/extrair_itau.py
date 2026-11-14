#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Coletor Itaú Imóveis.

O portal é uma SPA Angular protegida por Akamai.  O coletor usa o Chromium
completo do Playwright e lê os cartões renderizados.  A saída é o CSV estável
consumido pelo atualizador.
"""
from __future__ import annotations

import csv
import logging
import os
import re
import tempfile
from datetime import datetime
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

BASE = "https://www.itau.com.br/imoveis-itau"
DATE_PREFIX = os.environ.get("SOURCE_DATE_PREFIX", datetime.now().strftime("%Y.%m.%d_"))
REPORTS_DIR = os.environ.get("SOURCE_OUTPUT_DIR", "reports")
ARQUIVO_CSV = os.path.join(REPORTS_DIR, f"{DATE_PREFIX}itau_imoveis_geral.csv")
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/158.0.0.0 Safari/537.36"
)

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

CARD_JS = """
els => els.map(card => {
    const code = ((card.querySelector('.tag') || {}).title || '').match(/\\d+/)?.[0] || '';
    const titles = [...card.querySelectorAll('p[title]')].map(p => p.title);
    const details = [...card.querySelectorAll('.at-card-ativo-content-body-details span')]
        .map(span => span.title)
        .filter(Boolean);
    const prices = [...card.querySelectorAll('h2[title]')].map(h => h.title).filter(Boolean);
    return {
        code,
        title: titles[0] || '',
        location: titles[1] || '',
        details,
        price: prices.join(' '),
        image: (card.querySelector('img.at-img') || {}).src || '',
    };
})
"""


def limpar(texto):
    return re.sub(r"\s+", " ", str(texto or "")).strip()


def parse_card(card):
    code = limpar(card.get("code"))
    if not code:
        return None
    title = limpar(card.get("title"))
    location = limpar(card.get("location"))
    details = [limpar(value) for value in card.get("details") or [] if limpar(value)]

    cidade = location
    uf = ""
    if " - " in location:
        cidade, _, uf = location.rpartition(" - ")
        cidade, uf = cidade.strip(), uf.strip()

    tipo = title
    parts = re.split(r"\s*[–-]\s*", title, maxsplit=1)
    if len(parts) > 1:
        tipo = parts[0].strip()
    if not tipo:
        tipo = "Imóvel"

    image = limpar(card.get("image"))
    image_path = urlparse(image).path.lower()
    if not image_path.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
        image = ""

    descricao = f"{tipo} em {cidade}/{uf}."
    if details:
        descricao += " " + "; ".join(details) + "."
    descricao += " Valor sob consulta."

    return {
        "Nº do imóvel": code,
        "UF": uf,
        "Cidade": cidade,
        "Bairro": "",
        "Endereço": "",
        "Preço": "0,00",
        "Valor de avaliação": "",
        "Desconto": "",
        "Financiamento": "",
        "Descrição": descricao,
        "Modalidade de venda": "Leilão",
        "Link de acesso": f"{BASE}/detalhes?id={code}",
        "Imagem": image,
    }


def salvar_csv(rows):
    directory = os.path.dirname(ARQUIVO_CSV) or "."
    os.makedirs(directory, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", newline="", encoding="utf-8-sig", dir=directory, delete=False
    ) as handle:
        writer = csv.DictWriter(
            handle, fieldnames=CAMPOS, delimiter=";", extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(rows)
        temp_name = handle.name
    os.replace(temp_name, ARQUIVO_CSV)
    try:
        os.chmod(ARQUIVO_CSV, 0o664)
    except OSError:
        pass
    logging.info("CSV salvo: %s (%s imóveis)", ARQUIVO_CSV, len(rows))


def coletar():
    max_pages = int(os.environ.get("MAX_ITAU_PAGES", "0") or 0)
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            channel="chromium",
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        context = browser.new_context(
            locale="pt-BR",
            user_agent=UA,
            viewport={"width": 1366, "height": 1200},
        )
        page = context.new_page()
        page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )
        try:
            logging.info("Abrindo %s ...", BASE)
            page.goto(BASE, wait_until="domcontentloaded", timeout=90000)
            page.wait_for_selector(".at-card-ativo", timeout=60000)
            page.wait_for_timeout(2500)
            texto = page.inner_text("body")
            match = re.search(r"Item\s+\d+\s+de\s+(\d+)", texto)
            total_pages = int(match.group(1)) if match else 1
            if max_pages:
                total_pages = min(total_pages, max_pages)
            logging.info("Páginas: %s", total_pages)

            found = {}
            for page_index in range(1, total_pages + 1):
                cards = page.eval_on_selector_all(".at-card-ativo", CARD_JS)
                for card in cards:
                    item = parse_card(card)
                    if item:
                        found[item["Nº do imóvel"]] = item
                logging.info(
                    "Página %s/%s: %s cards; total %s",
                    page_index,
                    total_pages,
                    len(cards),
                    len(found),
                )
                if page_index >= total_pages:
                    break
                codes = [
                    (card.get("code") or "")
                    for card in cards
                    if card.get("code")
                ]
                page.locator('button[aria-label="próximo item"]').click()
                try:
                    page.wait_for_function(
                        """codes => {
                            const current = [...document.querySelectorAll('.at-card-ativo .tag')]
                                .map(el => (el.title || '').match(/\\d+/)?.[0])
                                .filter(Boolean);
                            return current.length && !codes.includes(current[0]);
                        }""",
                        arg=codes,
                        timeout=20000,
                    )
                except Exception:
                    page.wait_for_timeout(2500)
            return list(found.values())
        finally:
            browser.close()


def main():
    os.makedirs(REPORTS_DIR, exist_ok=True)
    rows = coletar()
    if not rows:
        raise RuntimeError("nenhum imóvel do Itaú foi coletado")
    salvar_csv(rows)


if __name__ == "__main__":
    main()
