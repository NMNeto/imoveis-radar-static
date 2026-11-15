"""Normalização de endereços para reduzir consultas de geocodificação.

A mesma rua aparece escrita de várias formas na planilha:

    RUA DO PURUS, N. S/N, QUARTEIRÃO 272 LOTE 11
    RUA DO PURUS, N. S/N, QUARTEIRÃO 272 LOTE 12
    RUA DO PURUS, N. S/N, QUARTEIRÃO 272, LOTE 10

Quadra, lote, apartamento e bloco identificam o imóvel, não o logradouro.
Para geocodificar, os três exemplos são exatamente a mesma consulta:
"RUA DO PURUS".  Este módulo separa o endereço em logradouro, número e
complemento, padroniza abreviações e monta uma chave estável por
UF + cidade + logradouro (+ número).

A normalização é determinística: o mesmo texto de entrada sempre gera a
mesma chave, o que permite deduplicar a planilha antes de consultar o
serviço de geocodificação.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .text import norm

# Tipos de logradouro: abreviações e erros de digitação comuns.
STREET_TYPES = {
    "R": "RUA",
    "RUA": "RUA",
    "AV": "AVENIDA",
    "AVEN": "AVENIDA",
    "AVENIDA": "AVENIDA",
    "AVENDA": "AVENIDA",
    "TV": "TRAVESSA",
    "TAV": "TRAVESSA",
    "TAVESSA": "TRAVESSA",
    "TRAV": "TRAVESSA",
    "TRAVESSA": "TRAVESSA",
    "AL": "ALAMEDA",
    "ALAMEDA": "ALAMEDA",
    "ALAMAEDA": "ALAMEDA",
    "ROD": "RODOVIA",
    "RODVIA": "RODOVIA",
    "RODOVIA": "RODOVIA",
    "EST": "ESTRADA",
    "ESTR": "ESTRADA",
    "ESTRDA": "ESTRADA",
    "ESTRADA": "ESTRADA",
    "PC": "PRACA",
    "PRACA": "PRACA",
    "PRASA": "PRACA",
    "PRASSA": "PRACA",
    "LGO": "LARGO",
    "LARGO": "LARGO",
    "VIA": "VIA",
    "VIELA": "VIELA",
    "BECO": "BECO",
    "CAMINHO": "CAMINHO",
    "PASSAGEM": "PASSAGEM",
    "PSG": "PASSAGEM",
    "MARGINAL": "MARGINAL",
    "ACESSO": "ACESSO",
    "VARIANTE": "VARIANTE",
    "CONJ": "CONJUNTO",
    "CONJUNTO": "CONJUNTO",
    "CONDOMINIO": "CONDOMINIO",
    "COND": "CONDOMINIO",
    "LOT": "LOTEAMENTO",
    "LOTEA": "LOTEAMENTO",
    "LOTEAMENTO": "LOTEAMENTO",
    "QUADRA": "QUADRA",
    "QD": "QUADRA",
    "SETOR": "SETOR",
    "SITIO": "SITIO",
    "FAZENDA": "FAZENDA",
    "CHACARA": "CHACARA",
    "GLEBA": "GLEBA",
    "AREA": "AREA",
    "NUCLEO": "NUCLEO",
    "VILA": "VILA",
}

# Abreviações de títulos usadas nos nomes das ruas.
NAME_ABBREVIATIONS = {
    "DR": "DOUTOR",
    "DRA": "DOUTORA",
    "PROF": "PROFESSOR",
    "PROFA": "PROFESSORA",
    "ENG": "ENGENHEIRO",
    "ENGA": "ENGENHEIRA",
    "PE": "PADRE",
    "CEL": "CORONEL",
    "MAL": "MARECHAL",
    "GEN": "GENERAL",
    "CAP": "CAPITAO",
    "TEN": "TENENTE",
    "DEL": "DELEGADO",
    "DES": "DESEMBARGADOR",
    "MIN": "MINISTRO",
    "SEN": "SENADOR",
    "DEP": "DEPUTADO",
    "PRES": "PRESIDENTE",
    "GOV": "GOVERNADOR",
    "STA": "SANTA",
    "STO": "SANTO",
}

# Palavras que iniciam o complemento do imóvel (não fazem parte do logradouro).
COMPLEMENT_WORDS = {
    "APTO",
    "APT",
    "APARTAMENTO",
    "AP",
    "CASA",
    "CS",
    "LOTE",
    "LOT",
    "LT",
    "QD",
    "QUADRA",
    "BL",
    "BLOCO",
    "TORRE",
    "COND",
    "CONDOMINIO",
    "CONJUNTO",
    "RESIDENCIAL",
    "RES",
    "EDIFICIO",
    "ED",
    "SALA",
    "SL",
    "LOJA",
    "LJ",
    "SETOR",
    "PAV",
    "PAVIMENTO",
    "UNIDADE",
    "UN",
    "FUNDOS",
    "TERRENO",
    "AREA",
    "GLEBA",
    "LOTEAMENTO",
    "KITINET",
    "COBERTURA",
    "BARRACAO",
    "GALPAO",
    "VAGA",
    "BOX",
    "CHACARA",
    "SITIO",
    "FAZENDA",
    "SOBRADO",
    "ANDAR",
    "ENTRADA",
    "MODULO",
    "PROLONGAMENTO",
    # "Nºs 532 e 540" (vários números de porta) fecha o logradouro.
    "NOS",
}

# Marcadores de número: "N. 10", "Nº 10", "N° 10", "NR 10", "NUMERO 10".
_NUMBER_MARKER = re.compile(
    r"^\s*(?:N\s*[.\u00ba\u00b0]|NRO\.?|NR\.?|NUMERO|NUM\.?)\s*(?P<value>.*)$",
    re.IGNORECASE,
)
_SN_RE = re.compile(r"^(?:S\s*/?\s*N[.\u00ba\u00b0]?|SN\.?|SEM\s+NUMERO|S/?N\s*[.\u00ba\u00b0]?)$")
_KM_RE = re.compile(r"^KM\s*(\d{1,4})\b(.*)$")
# Marcadores repetidos: "N. Nº 47" vira "47".
_REPEATED_MARKER = re.compile(
    r"^(?:(?:N\s*[.\u00ba\u00b0]?|NRO\.?|NR\.?|NUMERO|NUM|NO)\s*(?=\d))+"
)
# Número de porta: 123, 123A, 45-A, 415/445, 8-80, 540A2, 22-A3.
_NUMBER_TOKEN_RE = re.compile(r"^(\d[\dA-Z/\-]*)(.*)$")


@dataclass
class AddressParts:
    """Endereço decomposto e normalizado."""

    logradouro: str = ""
    numero: str = ""
    complemento: str = ""
    original: str = ""

    @property
    def normalizado(self) -> str:
        if self.logradouro and self.numero:
            return f"{self.logradouro}, {self.numero}"
        return self.logradouro


def _strip_zeros(value: str) -> str:
    if value.isdigit():
        return str(int(value))
    return value


def _clean_number_match(match: re.Match) -> tuple[str, str]:
    token, rest = match.group(1), match.group(2).strip(" .,;-")
    token = _normalize_number_token(token)
    if not token:
        return "", rest
    if re.fullmatch(r"[A-Z]", rest):
        return token + rest, ""
    return token, rest


def _normalize_number_token(token: str) -> str:
    """123, 045, 8-80, 540A2, 22-A3, 0 (vazio)."""
    if re.fullmatch(r"0+", token):
        return ""
    if re.fullmatch(r"0+SN", token):
        return ""
    match = re.fullmatch(r"(\d+)(?:([-/])(\d+))?([A-Z].*)?", token)
    if not match:
        return token
    first, separator, second, suffix = match.groups()
    result = _strip_zeros(first)
    if second:
        result += f"{separator}{_strip_zeros(second)}"
    if suffix:
        result += suffix
    return result


def extract_number(value: str) -> tuple[str, str]:
    """Separa o número de porta do restante de um trecho.

    Retorna ``(numero, resto)``.  Quando o trecho não começa com um número,
    o número fica vazio e todo o texto volta em ``resto``.
    """
    text = norm(value).strip(" .,;-")
    if not text:
        return "", ""
    text = _REPEATED_MARKER.sub("", text)
    if _SN_RE.match(text):
        return "", ""
    km = _KM_RE.match(text)
    if km:
        return f"KM {_strip_zeros(km.group(1))}", km.group(2).strip(" .,;-")
    match = _NUMBER_TOKEN_RE.match(text)
    if not match:
        return "", text
    return _clean_number_match(match)


def normalize_street(value: str) -> str:
    """Padroniza o logradouro: sem acento, sem pontuação e sem abreviações."""
    text = norm(value)
    if not text:
        return ""
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"[^A-Z0-9 ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    tokens = text.split()

    # "PROLONGAMENTO DA RUA X" é a mesma via que "RUA X" para o geocodificador.
    while tokens and tokens[0] in {"PROLONGAMENTO", "PROL", "PLG", "ANTIGA", "ANTIGO", "EXTENSAO"}:
        tokens.pop(0)
        if tokens and tokens[0] in {"DE", "DA", "DO", "DAS", "DOS"}:
            tokens.pop(0)

    # O tipo de logradouro aparece no começo ("1A TRAVESSA ..." inclusive).
    for index, token in enumerate(tokens[:3]):
        if token in STREET_TYPES:
            tokens[index] = STREET_TYPES[token]
            break

    tokens = [NAME_ABBREVIATIONS.get(token, token) for token in tokens]
    return " ".join(tokens).strip()


def normalize_complement(value: str) -> str:
    """Mantém o complemento apenas para referência (não entra na chave)."""
    text = norm(value)
    text = re.sub(r"[^A-Z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _looks_like_number(part: str) -> bool:
    text = norm(part).strip()
    return bool(
        re.match(r"^\d", text)
        or _SN_RE.match(text)
        or re.match(r"^KM\b", text)
    )


def _street_is_valid(prefix: str) -> bool:
    """Evita confundir o nome da via com o número de porta."""
    tokens = prefix.split()
    if not tokens:
        return False
    if tokens[-1] in {"DE", "DA", "DO", "DAS", "DOS", "NO", "NA"}:
        return False
    if len(tokens) >= 2:
        return any(len(token) >= 3 and token.isalpha() for token in tokens)
    # Rua com nome de uma palavra só ("MONDAI 867").
    return len(tokens[0]) >= 4 and tokens[0] not in STREET_TYPES


def _split_inline(text: str) -> tuple[str, str, str]:
    """Separa logradouro/número/complemento em endereços sem vírgula."""
    upper = norm(text)
    cut = None
    for match in re.finditer(r"[A-Z0-9]+", upper):
        if match.group(0) in COMPLEMENT_WORDS:
            before = upper[: match.start()]
            if re.search(r"\d[\s.,;:-]*$", before):
                cut = match.start()
                break
    segment = upper[:cut].rstrip(" .,;-") if cut is not None else upper
    complement = upper[cut:] if cut is not None else ""

    match = re.search(r"^(.*?)[\s\-]+(\d{1,5}[A-Z]?)\s*$", segment)
    if match and _street_is_valid(match.group(1)):
        return match.group(1), match.group(2), complement
    return segment, "", complement


def split_address(raw: str | None) -> AddressParts:
    """Decompõe um endereço bruto em logradouro, número e complemento."""
    text = re.sub(r"\s+", " ", str(raw or "")).strip()
    if not text:
        return AddressParts(original="")

    parts = [part.strip(" ,;") for part in text.split(",")]
    parts = [part for part in parts if part]
    if not parts:
        return AddressParts(original=text)

    street_raw = parts[0]
    number = ""
    complement: list[str] = []

    # O número pode estar embutido no primeiro trecho mesmo quando há
    # complementos separados por vírgula:
    # "Avenida Pio XII 150 apartamento 306, Edifício Planalto".
    street_raw, number, inline_complement = _split_inline(street_raw)
    if inline_complement:
        complement.append(inline_complement)
    for part in parts[1:]:
        marker = _NUMBER_MARKER.match(part)
        if not number and marker:
            number, rest = extract_number(marker.group("value"))
            if rest:
                complement.append(rest)
            continue
        if not number and _looks_like_number(part):
            number, rest = extract_number(part)
            if rest:
                complement.append(rest)
            continue
        complement.append(part)

    logradouro = normalize_street(street_raw)
    if not logradouro:
        logradouro = normalize_street(text)
    return AddressParts(
        logradouro=logradouro,
        numero=number,
        complemento=normalize_complement(" ".join(complement)),
        original=text,
    )


def normalize_address(raw: str | None, include_number: bool = True) -> str:
    """Endereço pronto para busca (logradouro + número opcional)."""
    parts = split_address(raw)
    if include_number and parts.numero:
        return f"{parts.logradouro}, {parts.numero}"
    return parts.logradouro


def geocode_key(uf: str, cidade: str, endereco: str) -> str:
    """Chave estável usada para deduplicar consultas de geocodificação."""
    return f"{norm(uf)}|{norm(cidade)}|{norm(endereco)}"


def geocode_query(
    uf: str,
    cidade: str,
    endereco: str,
    bairro: str = "",
    include_bairro: bool = False,
) -> str:
    """Consulta legível para Nominatim/Photon."""
    pieces = [endereco] if endereco else []
    if include_bairro and bairro:
        pieces.append(bairro)
    if cidade:
        pieces.append(f"{cidade} - {uf}" if uf else cidade)
    elif uf:
        pieces.append(uf)
    pieces.append("Brasil")
    return ", ".join(pieces)
