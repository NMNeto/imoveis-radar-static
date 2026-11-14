"""Normalização de texto, números e colunas (portado do projeto original)."""
from __future__ import annotations

import re
import unicodedata


def strip_accents(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value if value is not None else ""))
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def norm(value) -> str:
    """Normaliza para comparações: sem acentos, espaços simples, maiúsculas."""
    return " ".join(strip_accents(value).split()).upper()


def clean_control(value) -> str:
    text = "" if value is None else str(value)
    return "".join(ch for ch in text if ord(ch) >= 32 or ch in "\n\r\t").strip()


def parse_money(value):
    """Converte ``1.234,56`` / ``1234.56`` / ``R$ 1.234`` em float."""
    if value is None:
        return None
    text = str(value).strip().replace("R$", "").replace("\u00a0", "").replace(" ", "")
    if not text:
        return None
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    else:
        # "150.000" é separador de milhar; "150.00" é decimal.
        if text.count(".") == 1 and len(text.split(".")[1]) == 3:
            text = text.replace(".", "")
    try:
        number = float(text)
    except ValueError:
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def parse_float(value):
    if value is None:
        return None
    text = str(value).strip().replace("R$", "").replace("%", "").replace(" ", "")
    if not text:
        return None
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        number = float(text)
    except ValueError:
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def find_column(fieldnames, *patterns):
    for name in fieldnames or []:
        key = norm(name)
        if all(norm(pattern) in key for pattern in patterns):
            return name
    return None


def br_number(value, decimals: int = 2) -> str:
    """Formata um número no padrão brasileiro (usado no CSV exportado)."""
    if value is None or value == "":
        return ""
    try:
        text = f"{float(value):,.{decimals}f}"
    except (TypeError, ValueError):
        return str(value)
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def field_text(value) -> str:
    """Preserva o conteúdo original; apenas remove espaços nas pontas.

    O leitor do projeto original faz exatamente ``(value or "").strip()``.
    Caracteres de controle eventualmente presentes no CSV são mantidos para
    que os dados sejam idênticos aos do site em produção.
    """
    return "" if value is None else str(value).strip()


def safe_text(value, limit: int | None = None) -> str:
    """Versão para textos livres: colapsa espaços e opcionalmente limita."""
    text = re.sub(r"\s+", " ", clean_control(value))
    if limit is not None and len(text) > limit:
        return text[:limit].rstrip()
    return text
