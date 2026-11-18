"""Geração estática das páginas de SEO por estado, cidade e banco.

Cada página é HTML completo, com H1 textual, texto único baseado nos números da
própria seleção, cards pré-renderizados, links internos, canonical autorreferente
e JSON-LD (BreadcrumbList + CollectionPage/ItemList).  Não usa JavaScript, então
o conteúdo é indexável sem renderização.

A seleção de imóveis reaproveita ``filter_items``/``sort_items`` do modelo, para
os números das páginas serem idênticos aos do site.
"""
from __future__ import annotations

import html
import json
import logging
import re
import statistics
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from .model import filter_items, sort_items
from .safety import atomic_write_bytes

logger = logging.getLogger(__name__)

SITE_URL = "https://imovanta.com.br"
MIN_CITY_ITEMS = 10
CARDS_PAGE = 12
CARDS_HOME = 24
IMAGE_PLACEHOLDER = "/static/placeholder.svg"

SOURCE_LABELS = {
    "caixa": "Caixa",
    "bb": "Banco do Brasil",
    "santander": "Santander",
    "itau": "Itaú",
}
SOURCE_LABELS_PLURAL = {
    "caixa": "Caixa",
    "bb": "Banco do Brasil",
    "santander": "Santander",
    "itau": "Itaú",
}
UF_NAMES = {
    "AC": "Acre", "AL": "Alagoas", "AP": "Amapá", "AM": "Amazonas",
    "BA": "Bahia", "CE": "Ceará", "DF": "Distrito Federal",
    "ES": "Espírito Santo", "GO": "Goiás", "MA": "Maranhão",
    "MT": "Mato Grosso", "MS": "Mato Grosso do Sul", "MG": "Minas Gerais",
    "PA": "Pará", "PB": "Paraíba", "PR": "Paraná", "PE": "Pernambuco",
    "PI": "Piauí", "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte",
    "RS": "Rio Grande do Sul", "RO": "Rondônia", "RR": "Roraima",
    "SC": "Santa Catarina", "SP": "São Paulo", "SE": "Sergipe",
    "TO": "Tocantins",
}

SMALL_WORDS = {"de", "da", "do", "das", "dos", "e", "em", "na", "no", "nas", "nos"}
UPPER_WORDS = {"N", "Nº", "N°", "S/N", "S/Nº", "SN", "BL", "CJ", "QD", "LT", "KM", "CEP", "R"}


# ---------------------------------------------------------------------------
# Formatação e texto
# ---------------------------------------------------------------------------
def esc(value) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def brl(value) -> str:
    number = float(value or 0)
    sign = "-" if number < 0 else ""
    text = f"{abs(number):,.0f}".replace(",", ".")
    return f"{sign}R$ {text}"


def pct(value) -> str:
    return f"{float(value or 0):.1f}%".replace(".", ",")


def num(value) -> str:
    return f"{int(value):,}".replace(",", ".")


def clip(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut + "…"


def short_text(value, limit: int = 160) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def clean_address(value, limit: int = 160) -> str:
    text = short_text(value, limit)
    text = re.sub(r"\s*,\s*", ", ", text)
    text = re.sub(r"\s*;\s*", ", ", text)
    text = re.sub(r"\s*-\s*", " - ", text)
    return re.sub(r",+$", "", text).strip()


def title_case(value) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return ""
    words = []
    for index, word in enumerate(text.split(" ")):
        bare = re.sub(r'^[("\[\]]+|[)"\].,;:]+$', "", word)
        if not bare:
            words.append(word)
            continue
        if bare.upper() in UPPER_WORDS:
            words.append(word)
            continue
        if index > 0 and bare.lower() in SMALL_WORDS:
            words.append(word.lower())
            continue
        lowered = word.lower()
        words.append(
            re.sub(
                r'(^|[("\[\]])(\w)',
                lambda match: match.group(1) + match.group(2).upper(),
                lowered,
            )
        )
    return " ".join(words)


def norm_text(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().upper()


def build_address(item: dict) -> dict:
    street = title_case(clean_address(item.get("endereco"), 160))
    bairro = title_case(item.get("bairro") or "")
    cidade = title_case(item.get("cidade") or "")
    uf = str(item.get("uf") or "").upper()
    city_uf = f"{cidade}/{uf}" if cidade and uf else (cidade or uf)
    include_bairro = bool(bairro) and not norm_text(street).endswith(norm_text(bairro))
    place = " - ".join(part for part in ([bairro if include_bairro else "", city_uf]) if part)
    full = ", ".join(part for part in (street, place) if part)
    google_url = (
        f"https://www.google.com/search?q={quote(full, safe='')}" if street and full else ""
    )
    return {"street": street, "place": place, "full": full, "google_url": google_url}


def slugify(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text or "cidade"


# ---------------------------------------------------------------------------
# Card (mesmo markup do app, sem os botões locais nas páginas estáticas)
# ---------------------------------------------------------------------------
def image_src(item: dict, proxy: str = "/api/image") -> str:
    url = str(item.get("imagem") or "").strip()
    if not url.startswith("https://"):
        return ""
    if item.get("fonte") and item.get("fonte") != "caixa" and proxy:
        return f"{proxy}?url={quote(url, safe='')}"
    return url


def discount_label(item: dict) -> str:
    if item.get("desconto") is None:
        return "s/ avaliação"
    value = float(item.get("desconto") or 0)
    return f"{'-' if value >= 0 else '+'}{pct(abs(value))}"


def price_label(item: dict) -> str:
    if item.get("preco_label"):
        return str(item["preco_label"])
    if item.get("sem_preco"):
        return "Faça sua oferta"
    return brl(item.get("preco"))


def source_label(item: dict) -> str:
    return str(item.get("fonte_nome") or SOURCE_LABELS.get(item.get("fonte"), "Caixa"))


def priority_index(items: list[dict], limit: int) -> int:
    """Índice do card que deve carregar a imagem primeiro.

    Preferimos imagens servidas direto (Caixa), que respondem mais rápido que
    as que passam pelo proxy /api/image. Assim o maior elemento da primeira
    dobra pinta cedo e o LCP não fica preso a uma imagem lenta do proxy.
    """
    for index, item in enumerate(items[:limit]):
        if image_src(item).startswith("https://"):
            return index
    return 0


def card_html(item: dict, *, interactive: bool = False, eager: bool = False) -> str:
    link = esc(item.get("link") or "")
    image = image_src(item)
    address = build_address(item)
    valuation = (
        f'<span class="muted valuation">Avaliação {esc(source_label(item))}: sem avaliação</span>'
        if item.get("valor_avaliacao") is None
        else (
            '<span class="muted valuation" title="Valor de avaliação da fonte">'
            f'Avaliação {esc(source_label(item))}: {brl(item.get("valor_avaliacao"))}</span>'
        )
    )
    profit_class = "negative" if item.get("lucro") is not None and item["lucro"] < 0 else ""
    if item.get("lucro") is None:
        profit = (
            '<div class="profit" title="Lucro não calculado por falta de valor de avaliação">'
            "Lucro não calculado (sem avaliação)</div>"
        )
    else:
        profit = (
            f'<div class="profit {profit_class}" title="Lucro estimado {brl(item.get("lucro"))} '
            f'({pct(item.get("lucro_pct"))})">Lucro est. {brl(item.get("lucro"))} '
            f'({pct(item.get("lucro_pct"))})</div>'
        )
    if address["google_url"]:
        addr = (
            f'<a class="addr-link" href="{esc(address["google_url"])}" target="_blank" '
            f'rel="noopener noreferrer" title="Buscar no Google: {esc(address["full"])}" '
            f'aria-label="Buscar no Google: {esc(address["full"])}">'
            f'<span class="addr-line" title="{esc(address["full"])}">{esc(address["full"])}</span></a>'
        )
    elif address["full"]:
        addr = f'<span class="addr-line" title="{esc(address["full"])}">{esc(address["full"])}</span>'
    else:
        addr = '<span class="addr-line muted">Endereço não informado</span>'

    financing = (
        '<span class="status-badge fin">🟢 Financiável</span>'
        if re.match(r"^sim$", str(item.get("financiamento") or ""), re.IGNORECASE)
        else '<span class="status-badge no-fin">🔴 Sem financiamento</span>'
    )
    needs_value = (
        '<span class="status-badge needs-value">🟡 Requer ajuste de valor</span>'
        if item.get("sem_preco")
        else ""
    )
    adjusted = (
        '<span class="status-badge custom-value">✏️ Valor personalizado</span>'
        if item.get("ajustado")
        else ""
    )
    priority = 'loading="eager" fetchpriority="high"' if eager else 'loading="lazy"'
    thumb = (
        f'<img src="{esc(image)}" alt="Imóvel {esc(item.get("id_fonte") or item.get("id"))}" '
        f'{priority} referrerpolicy="no-referrer" data-fallback="{IMAGE_PLACEHOLDER}">'
        if image
        else f'<img src="{IMAGE_PLACEHOLDER}" alt="" width="4" height="3">'
    )
    actions = (
        '<a class="btn small" href="' + link + '" target="_blank" rel="noopener noreferrer">Ver oferta</a>'
        '<button class="btn small" type="button" data-action="adjust" '
        f'data-id="{esc(item.get("id"))}">Ajustar valor</button>'
        '<button class="btn small danger" type="button" data-action="exclude" '
        f'data-id="{esc(item.get("id"))}">Excluir</button>'
        if interactive
        else '<a class="btn small primary" href="'
        + link
        + '" target="_blank" rel="noopener noreferrer">Ver oferta</a>'
    )
    return (
        f'<article class="card" data-id="{esc(item.get("id"))}">'
        f'<a class="thumb" href="{link}" target="_blank" rel="noopener noreferrer">'
        f"{thumb}"
        f'<span class="badge">{esc(discount_label(item))}</span>'
        "</a>"
        '<div class="card-body">'
        f'<div class="price-row"><strong>{esc(price_label(item))}</strong>{valuation}</div>'
        f"{profit}"
        f'<div class="addr">{addr}</div>'
        '<div class="tags">'
        f'<span class="tag source source-{esc(item.get("fonte") or "caixa")}">{esc(source_label(item))}</span>'
        f'<span class="tag">{esc(item.get("modalidade") or "—")}</span>'
        f"{financing}{needs_value}{adjusted}"
        f'<span class="tag">ID {esc(item.get("id_fonte") or item.get("id"))}</span>'
        "</div>"
        f'<div class="card-actions">{actions}</div>'
        "</div></article>"
    )


# ---------------------------------------------------------------------------
# Estatísticas e páginas
# ---------------------------------------------------------------------------
def _stats(items: list[dict]) -> dict:
    discounts = [float(i["desconto"]) for i in items if i.get("desconto") is not None]
    prices = [float(i["preco"]) for i in items if float(i.get("preco") or 0) > 0]
    valuations = [float(i["valor_avaliacao"]) for i in items if i.get("valor_avaliacao")]
    financing = [
        i for i in items if re.match(r"^sim$", str(i.get("financiamento") or ""), re.IGNORECASE)
    ]
    bairros: dict[str, int] = {}
    for item in items:
        bairro = title_case(item.get("bairro") or "")
        if bairro:
            bairros[bairro] = bairros.get(bairro, 0) + 1
    fontes: dict[str, int] = {}
    for item in items:
        label = source_label(item)
        fontes[label] = fontes.get(label, 0) + 1
    return {
        "total": len(items),
        "desconto_medio": round(statistics.fmean(discounts), 1) if discounts else 0.0,
        "preco_mediano": statistics.median(prices) if prices else 0,
        "preco_min": min(prices) if prices else 0,
        "preco_max": max(prices) if prices else 0,
        "avaliacao_mediana": statistics.median(valuations) if valuations else 0,
        "financiavel_pct": round(100 * len(financing) / len(items), 0) if items else 0,
        "bairros": sorted(bairros.items(), key=lambda pair: (-pair[1], pair[0]))[:6],
        "fontes": sorted(fontes.items(), key=lambda pair: (-pair[1], pair[0])),
    }


@dataclass
class PageSpec:
    kind: str
    path: str
    title: str
    description: str
    h1: str
    place: str
    params: dict
    crumbs: list[tuple[str, str]]
    app_url: str
    links_title: str = ""
    links: list[tuple[str, str]] = field(default_factory=list)


def build_specs(items: list[dict], *, min_city_items: int = MIN_CITY_ITEMS) -> list[PageSpec]:
    # Mesma seleção do app na visão padrão: sem excluídos e sem lucro negativo.
    items = filter_items(items, {}, True)
    specs: list[PageSpec] = []
    by_uf: dict[str, list[dict]] = {}
    by_city: dict[tuple[str, str], list[dict]] = {}
    display_city: dict[tuple[str, str], dict[str, int]] = {}
    for item in items:
        uf = str(item.get("uf") or "").upper()
        if not uf:
            continue
        by_uf.setdefault(uf, []).append(item)
        cidade = title_case(item.get("cidade") or "")
        if not cidade:
            continue
        key = (uf, cidade)
        by_city.setdefault(key, []).append(item)
        display_city.setdefault(key, {})
        display_city[key][cidade] = display_city[key].get(cidade, 0) + 1

    city_slugs: dict[tuple[str, str], str] = {}
    used: set[str] = set()
    for key in sorted(by_city):
        base = slugify(key[1])
        slug = base
        counter = 2
        while slug in used:
            slug = f"{base}-{counter}"
            counter += 1
        used.add(slug)
        city_slugs[key] = slug

    # Hub nacional
    hub_links = [(f"/imoveis/{uf.lower()}/", f"{UF_NAMES.get(uf, uf)} ({num(len(group))})")
                 for uf, group in sorted(by_uf.items(), key=lambda pair: -len(pair[1]))]
    specs.append(
        PageSpec(
            kind="hub",
            path="/imoveis/",
            title="Imóveis de leilão por estado e cidade | Imovanta",
            description=(
                f"Navegue por {num(len(items))} imóveis de leilão e retomados em "
                f"{len(by_uf)} estados e {num(len(by_city))} cidades. Caixa, Banco do Brasil, "
                "Santander e Itaú, com desconto e financiamento."
            ),
            h1="Imóveis de leilão por estado e cidade",
            place="todo o Brasil",
            params={},
            crumbs=[("Início", "/"), ("Imóveis", "/imoveis/")],
            app_url="/",
            links_title="Estados com mais imóveis",
            links=hub_links,
        )
    )

    # Estados
    for uf, group in sorted(by_uf.items()):
        name = UF_NAMES.get(uf, uf)
        cities = [(key, len(value)) for key, value in by_city.items() if key[0] == uf]
        cities.sort(key=lambda pair: -pair[1])
        stats = _stats(group)
        specs.append(
            PageSpec(
                kind="uf",
                path=f"/imoveis/{uf.lower()}/",
                title=f"Imóveis de leilão em {name} — {num(len(group))} oportunidades",
                description=(
                    f"{num(len(group))} imóveis de leilão e retomados em {name}: "
                    f"{', '.join(label for label, _ in stats['fontes'][:3])}. "
                    f"Desconto médio de {pct(stats['desconto_medio'])} sobre a avaliação."
                ),
                h1=f"Imóveis de leilão em {name}",
                place=name,
                params={"uf": uf},
                crumbs=[("Início", "/"), ("Imóveis", "/imoveis/"), (name, f"/imoveis/{uf.lower()}/")],
                app_url=f"/?uf={uf}",
                links_title=f"Cidades em {name}",
                links=[
                    (f"/imoveis/{uf.lower()}/{city_slugs[key]}/", f"{key[1]} ({num(count)})")
                    for key, count in cities
                ],
            )
        )

    # Cidades
    for key, group in sorted(by_city.items()):
        uf, cidade = key
        if len(group) < min_city_items:
            continue
        name = UF_NAMES.get(uf, uf)
        stats = _stats(group)
        siblings = [
            (other_key, len(other))
            for other_key, other in by_city.items()
            if other_key[0] == uf and other_key != key and len(other) >= min_city_items
        ]
        siblings.sort(key=lambda pair: -pair[1])
        specs.append(
            PageSpec(
                kind="cidade",
                path=f"/imoveis/{uf.lower()}/{city_slugs[key]}/",
                title=f"Imóveis de leilão em {cidade}/{uf} — {num(len(group))} ofertas",
                description=(
                    f"{num(len(group))} imóveis de leilão e retomados em {cidade}/{uf}. "
                    f"Desconto médio de {pct(stats['desconto_medio'])}; "
                    f"{stats['financiavel_pct']:.0f}% aceitam financiamento. "
                    f"Compare preço, avaliação e dívidas."
                ),
                h1=f"Imóveis de leilão em {cidade}/{uf}",
                place=f"{cidade}/{uf}",
                params={"uf": uf, "cidade": cidade},
                crumbs=[
                    ("Início", "/"),
                    ("Imóveis", "/imoveis/"),
                    (name, f"/imoveis/{uf.lower()}/"),
                    (cidade, f"/imoveis/{uf.lower()}/{city_slugs[key]}/"),
                ],
                app_url=f"/?uf={uf}&cidade={quote(cidade, safe='')}",
                links_title=f"Outras cidades em {name}",
                links=[
                    (f"/imoveis/{uf.lower()}/{city_slugs[other_key]}/", f"{other_key[1]} ({count})")
                    for other_key, count in siblings[:12]
                ],
            )
        )

    # Bancos
    for fonte, label in SOURCE_LABELS.items():
        group = [item for item in items if item.get("fonte") == fonte]
        if not group:
            continue
        stats = _stats(group)
        top_cities = [
            (key, count)
            for key, count in (
                (key, len([i for i in value if i.get("fonte") == fonte]))
                for key, value in by_city.items()
            )
            if count >= 5
        ]
        top_cities.sort(key=lambda pair: -pair[1])
        specs.append(
            PageSpec(
                kind="banco",
                path=f"/imoveis/banco/{fonte}/",
                title=f"Imóveis {label}: leilão e venda direta — {num(len(group))} ofertas",
                description=(
                    f"{num(len(group))} imóveis do {label} para venda direta e leilão. "
                    f"Desconto médio de {pct(stats['desconto_medio'])} sobre a avaliação. "
                    "Veja por estado e cidade."
                ),
                h1=f"Imóveis {label}: leilão e venda direta",
                place=label,
                params={"fonte": fonte},
                crumbs=[
                    ("Início", "/"),
                    ("Imóveis", "/imoveis/"),
                    (label, f"/imoveis/banco/{fonte}/"),
                ],
                app_url=f"/?fonte={fonte}",
                links_title=f"Cidades com imóveis {label}",
                links=[
                    (
                        f"/imoveis/{key[0].lower()}/{city_slugs[key]}/",
                        f"{key[1]}/{key[0]} ({num(count)})",
                    )
                    for key, count in top_cities[:18]
                ],
            )
        )

    return specs


def _page_items(items: list[dict], spec: PageSpec) -> list[dict]:
    filtered = filter_items(items, spec.params or {}, True)
    return sort_items(filtered, "desconto_desc")


def _layout(*, title: str, description: str, canonical: str, body: str, json_ld: dict,
            preload_image: str = "") -> str:
    return (
        "<!doctype html>\n"
        '<html lang="pt-BR">\n<head>\n'
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"  <title>{esc(title)}</title>\n"
        f'  <meta name="description" content="{esc(description)}">\n'
        '  <meta name="robots" content="index, follow, max-image-preview:large">\n'
        '  <meta name="theme-color" content="#0b2f6f">\n'
        f'  <link rel="canonical" href="{esc(canonical)}">\n'
        '  <meta property="og:site_name" content="Imovanta">\n'
        '  <meta property="og:locale" content="pt_BR">\n'
        '  <meta property="og:type" content="website">\n'
        f'  <meta property="og:title" content="{esc(title)}">\n'
        f'  <meta property="og:description" content="{esc(description)}">\n'
        f'  <meta property="og:url" content="{esc(canonical)}">\n'
        '  <meta property="og:image" content="https://imovanta.com.br/static/og-image.png">\n'
        '  <meta property="og:image:width" content="1200">\n'
        '  <meta property="og:image:height" content="630">\n'
        '  <meta name="twitter:card" content="summary_large_image">\n'
        '  <link rel="icon" type="image/png" href="/static/favicon.png">\n'
        '  <link rel="apple-touch-icon" href="/static/apple-touch-icon.png">\n'
        '  <link rel="manifest" href="/static/site.webmanifest">\n'
        '  <script src="/static/theme.js"></script>\n'
        '  <link rel="stylesheet" href="/static/style.css">\n'
        + (
            f'  <link rel="preload" as="image" href="{esc(preload_image)}" fetchpriority="high">\n'
            if preload_image
            else ""
        )
        +
        '  <script type="application/ld+json">\n'
        f"{json.dumps(json_ld, ensure_ascii=False, indent=2)}\n"
        "  </script>\n"
        "</head>\n"
        f'<body class="lp-body">\n{body}\n</body>\n</html>\n'
    )


def _crumbs_html(crumbs: list[tuple[str, str]]) -> str:
    parts = []
    for index, (label, href) in enumerate(crumbs):
        last = index == len(crumbs) - 1
        if last:
            parts.append(f'<li aria-current="page">{esc(label)}</li>')
        else:
            parts.append(f'<li><a href="{esc(href)}">{esc(label)}</a></li>')
    return (
        '<nav class="lp-crumbs" aria-label="Trilha de navegação"><ol>'
        + "".join(parts)
        + "</ol></nav>"
    )


def _links_html(title: str, links: list[tuple[str, str]]) -> str:
    if not links:
        return ""
    items = "".join(
        f'<a class="chip" href="{esc(href)}">{esc(label)}</a>' for href, label in links
    )
    return (
        f'<nav class="lp-links" aria-label="{esc(title)}">'
        f'<h2 class="lp-links-title">{esc(title)}</h2>'
        f'<div class="lp-chips">{items}</div></nav>'
    )


def _intro(spec: PageSpec, stats: dict) -> str:
    total = stats["total"]
    fontes = ", ".join(label for label, _ in stats["fontes"][:4])
    bairros = stats["bairros"]
    bairro_text = ""
    if bairros and spec.kind != "hub":
        listed = ", ".join(f"{name} ({count})" for name, count in bairros[:4])
        bairro_text = (
            f" As ofertas se concentram em {listed}, entre outros bairros."
        )
    faixa = ""
    if stats["preco_min"] and stats["preco_max"]:
        faixa = (
            f" Os preços pedidos vão de {brl(stats['preco_min'])} a "
            f"{brl(stats['preco_max'])}."
        )
    return (
        f"<p>Esta página reúne <strong>{num(total)} imóveis</strong> de leilão e retomados em "
        f"{esc(spec.place)}, "
        f"anunciados por {esc(fontes)}. O desconto médio em relação ao valor de avaliação "
        f"é de <strong>{pct(stats['desconto_medio'])}</strong> e "
        f"{stats['financiavel_pct']:.0f}% das ofertas aceitam financiamento."
        f"{faixa}{bairro_text}</p>"
        "<p>Os valores de desconto e lucro são estimativas para triagem: o site aplica "
        "6% de corretagem, a taxa do leiloeiro quando a modalidade não é venda online e "
        "uma estimativa de 30% para dívidas de condomínio, IPTU e ITBI. Confirme sempre "
        "o preço, a ocupação e as dívidas no edital e no portal do banco.</p>"
    )


def _json_ld(spec: PageSpec, stats: dict, cards: list[dict], canonical: str) -> dict:
    crumbs = []
    for index, (label, href) in enumerate(spec.crumbs):
        entry = {"@type": "ListItem", "position": index + 1, "name": label}
        if index < len(spec.crumbs) - 1:
            entry["item"] = SITE_URL.rstrip("/") + href
        crumbs.append(entry)
    graph = [
        {"@type": "BreadcrumbList", "itemListElement": crumbs},
        {
            "@type": "CollectionPage",
            "@id": canonical + "#page",
            "url": canonical,
            "name": spec.title,
            "description": spec.description,
            "inLanguage": "pt-BR",
            "isPartOf": {"@id": SITE_URL + "/#website"},
            "mainEntity": {
                "@type": "ItemList",
                "numberOfItems": stats["total"],
                "itemListElement": [
                    {
                        "@type": "ListItem",
                        "position": index + 1,
                        "url": item.get("link") or canonical,
                        "name": price_label(item) + " — " + (build_address(item)["full"] or spec.h1),
                    }
                    for index, item in enumerate(cards)
                ],
            },
        },
    ]
    return {"@context": "https://schema.org", "@graph": graph}


def render_page(spec: PageSpec, items: list[dict], *, site_url: str = SITE_URL) -> str:
    selected = _page_items(items, spec)
    stats = _stats(selected)
    cards = selected[:CARDS_PAGE]
    canonical = site_url.rstrip("/") + spec.path
    body = (
        '<header class="lp-top">'
        '<a class="lp-brand" href="/" aria-label="Imovanta — início">'
        '<img src="/static/logo-imovanta.png" alt="Imovanta" width="900" height="268"></a>'
        '<div class="lp-top-actions">'
        '<button class="btn small" type="button" data-theme-toggle aria-pressed="false" '
        'title="Ativar tema escuro">Tema</button>'
        f'<a class="btn small primary" href="{esc(spec.app_url)}">Busca com filtros</a>'
        "</div>"
        "</header>"
        '<div class="lp-wrap">'
        + _crumbs_html(spec.crumbs)
        + f'<h1 class="lp-title">{esc(spec.h1)}</h1>'
        + '<div class="lp-intro">'
        + _intro(spec, stats)
        + "</div>"
        + '<section class="lp-stats" aria-label="Resumo das ofertas">'
        + (
            f'<div><span class="lp-stat-value">{num(stats["total"])}</span>'
            '<span class="lp-stat-label">imóveis</span></div>'
            f'<div><span class="lp-stat-value">{pct(stats["desconto_medio"])}</span>'
            '<span class="lp-stat-label">desconto médio</span></div>'
            f'<div><span class="lp-stat-value">{brl(stats["preco_mediano"])}</span>'
            '<span class="lp-stat-label">preço mediano</span></div>'
            f'<div><span class="lp-stat-value">{stats["financiavel_pct"]:.0f}%</span>'
            '<span class="lp-stat-label">financiáveis</span></div>'
        )
        + "</section>"
        + f'<section class="lp-list"><h2>Ofertas em destaque ({len(cards)} de {num(stats["total"])})</h2>'
        + '<div class="cards">'
        + "\n        ".join(
            card_html(item, eager=index == priority_index(cards, len(cards)))
            for index, item in enumerate(cards)
        )
        + "</div>"
        + f'<p class="lp-cta"><a class="btn primary" href="{esc(spec.app_url)}">'
        "Ver todos com filtros e mapa</a></p></section>"
        + _links_html(spec.links_title, spec.links)
        + '<footer class="lp-foot">'
        '<p><a href="/">Imovanta</a> — imóveis de leilão e retomados da Caixa, '
        "Banco do Brasil, Santander e Itaú.</p>"
        '<p class="muted">Preços, disponibilidade e condições mudam a qualquer momento. '
        "Confirme na fonte original antes de decidir. O site não vende imóveis.</p>"
        "</footer>"
        "</div>"
    )
    return _layout(
        title=clip(spec.title, 65),
        description=clip(spec.description, 160),
        canonical=canonical,
        body=body,
        json_ld=_json_ld(spec, stats, cards, canonical),
        preload_image=image_src(cards[priority_index(cards, len(cards))]) if cards else "",
    )


def _write(public: Path, relative: str, text: str) -> bool:
    target = public / relative
    return atomic_write_bytes(target, text.encode("utf-8"), public)


def _cleanup(public: Path, keep: set[str]) -> int:
    removed = 0
    root = public / "imoveis"
    if not root.exists():
        return 0
    for path in root.rglob("index.html"):
        relative = "/" + str(path.relative_to(public)).replace("\\", "/")
        if relative in keep:
            continue
        try:
            path.unlink()
            removed += 1
        except OSError:
            continue
        for parent in path.parents:
            if parent == public or parent == public.parent:
                break
            try:
                parent.rmdir()
            except OSError:
                break
    return removed


def inject_home_cards(public: Path, items: list[dict], *, count: int = CARDS_HOME) -> bool:
    path = public / "index.html"
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    start = "<!-- cards:inicio -->"
    end = "<!-- cards:fim -->"
    if start not in text or end not in text:
        logger.warning("Marcadores de cards ausentes em index.html")
        return False
    filtered = sort_items(filter_items(items, {}, True), "desconto_desc")
    selected = filtered[:count]
    fast = priority_index(selected, count)
    cards = "\n        ".join(
        card_html(item, interactive=True, eager=index == fast)
        for index, item in enumerate(selected)
    )
    before, rest = text.split(start, 1)
    _, after = rest.split(end, 1)
    updated = f"{before}{start}\n{cards}\n        {end}{after}"
    preload_start, preload_end = "<!-- preload:inicio -->", "<!-- preload:fim -->"
    if preload_start in updated and preload_end in updated and selected:
        image = image_src(selected[fast])
        link = (
            f'<link rel="preload" as="image" href="{esc(image)}" fetchpriority="high">'
            if image
            else ""
        )
        head, rest = updated.split(preload_start, 1)
        _, tail = rest.split(preload_end, 1)
        updated = f"{head}{preload_start}{link}{preload_end}{tail}"
    return atomic_write_bytes(path, updated.encode("utf-8"), public)


def generate(
    public: Path,
    items: list[dict],
    *,
    site_url: str = SITE_URL,
    min_city_items: int = MIN_CITY_ITEMS,
) -> dict:
    """Gera todas as páginas e retorna um resumo."""
    public = Path(public)
    started = datetime.now()
    specs = build_specs(items, min_city_items=min_city_items)
    written = 0
    changed = 0
    keep: set[str] = set()
    for spec in specs:
        relative = spec.path.strip("/") + "/index.html"
        keep.add("/" + relative)
        if _write(public, relative, render_page(spec, items, site_url=site_url)):
            changed += 1
            written += 1
    removed = _cleanup(public, keep)
    home_changed = inject_home_cards(public, items)
    summary = {
        "paginas": len(specs),
        "gravadas": written,
        "alteradas": changed,
        "removidas": removed,
        "home_cards_alterados": home_changed,
        "segundos": round((datetime.now() - started).total_seconds(), 1),
        "tipos": {
            kind: sum(1 for spec in specs if spec.kind == kind)
            for kind in ("hub", "uf", "cidade", "banco")
        },
    }
    logger.info(
        "Páginas SEO: %s geradas (%s cidades, %s UFs, %s bancos), %s alteradas",
        len(specs),
        summary["tipos"]["cidade"],
        summary["tipos"]["uf"],
        summary["tipos"]["banco"],
        changed,
    )
    return summary
