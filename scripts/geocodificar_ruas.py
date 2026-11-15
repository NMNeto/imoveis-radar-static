#!/usr/bin/env python3
"""Geocodifica ruas e bairros dos imóveis publicados, com orçamento de tempo.

A fila é montada a partir dos imóveis já publicados. A prioridade é:

1. ruas novas (sem entrada no cache);
2. ruas cuja retentativa já venceu;
3. maior número de imóveis e, dentro disso, imóveis ainda sem coordenada.

Só resultados ``endereco``/``rua`` viram coordenada de rua. Quando o
Nominatim encontra o bairro, o centroide também é gravado no cache de
localidades (``points``) para melhorar o fallback de cidade para bairro.

O cache é salvo periodicamente e em ``finally``; uma execução interrompida
pode ser retomada sem repetir ruas terminais. Para respeitar a política do
Nominatim, scripts recorrentes devem usar ``--intervalo 16`` (4 req/min).
"""
from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from imoveis_radar import geocode_client, publish  # noqa: E402
from imoveis_radar.address_geocoder import geocode_endereco  # noqa: E402
from imoveis_radar.addresses import split_address  # noqa: E402
from imoveis_radar.config import Paths  # noqa: E402
from imoveis_radar.geo import (  # noqa: E402
    STREET_RETRY_DAYS,
    geocode_key,
    item_street_key,
    load_geocode_cache,
    save_geocode_cache,
    set_bairro_point,
)

TERMINAL_PRECISIONS = {"endereco", "rua"}


def _today() -> date:
    return date.today()


def _parse_date(value) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)).date()
    except ValueError:
        return None


def street_is_terminal(entry: dict) -> bool:
    """Entrada terminal: rua/endereço com coordenada válida."""
    if not isinstance(entry, dict):
        return False
    return bool(
        entry.get("status") == "ok"
        and entry.get("precisao") in TERMINAL_PRECISIONS
        and entry.get("lat") is not None
        and entry.get("lng") is not None
    )


def street_needs_retry(entry: dict, today: date | None = None) -> bool:
    """Diz se uma entrada não terminal já pode ser tentada de novo."""
    if not entry:
        return True
    if street_is_terminal(entry):
        return False
    today = today or _today()
    due = _parse_date(entry.get("proxima_tentativa"))
    if due is None:
        updated = _parse_date(entry.get("atualizado_em"))
        if updated is None:
            return True
        due = updated + timedelta(days=STREET_RETRY_DAYS)
    return due <= today


def collect_streets(items: list[dict]) -> list[dict]:
    """Agrupa os imóveis ativos por logradouro."""
    streets: dict[str, dict] = {}
    for item in items:
        if item.get("excluido"):
            continue
        key = item_street_key(item)
        if not key:
            continue
        parts = split_address(item.get("endereco", ""))
        street = streets.setdefault(
            key,
            {
                "key": key,
                "uf": item.get("uf", ""),
                "cidade": item.get("cidade", ""),
                "logradouro": parts.logradouro,
                "bairros": Counter(),
                "imoveis": 0,
                "criticos": 0,
            },
        )
        street["imoveis"] += 1
        if item.get("geo_precisao") in (None, "estado"):
            street["criticos"] += 1
        if item.get("bairro"):
            street["bairros"][item["bairro"]] += 1

    result = []
    for street in streets.values():
        bairros = street.pop("bairros")
        street["bairro"] = bairros.most_common(1)[0][0] if bairros else ""
        result.append(street)
    return result


def build_queue(
    items: list[dict], cache: dict, today: date | None = None
) -> list[dict]:
    """Monta a fila ordenada de ruas a consultar."""
    today = today or _today()
    ruas = cache.get("ruas", {})
    queue = []
    for street in collect_streets(items):
        entry = ruas.get(street["key"])
        if street_is_terminal(entry):
            continue
        if entry and not street_needs_retry(entry, today):
            continue
        street["nova"] = entry is None
        street["atualizado_em"] = (entry or {}).get("atualizado_em") or ""
        queue.append(street)

    queue.sort(
        key=lambda street: (
            0 if street["nova"] else 1,
            -street["criticos"],
            -street["imoveis"],
            street["atualizado_em"],
            street["key"],
        )
    )
    return queue


def build_entry(
    result: dict, today: date, attempts: int
) -> tuple[dict, str]:
    """Converte o resultado do geocodificador em entrada de cache."""
    status = result.get("status")
    precision = result.get("precisao") or ""
    if status == "ok" and precision in TERMINAL_PRECISIONS:
        return (
            {
                "status": "ok",
                "lat": result.get("lat"),
                "lng": result.get("lng"),
                "precisao": precision,
                "fonte": result.get("fonte") or "nominatim",
                "endereco_retornado": result.get("endereco_retornado", ""),
                "consulta": result.get("consulta", ""),
                "tentativas": attempts,
                "atualizado_em": datetime.now().isoformat(timespec="seconds"),
                "proxima_tentativa": None,
            },
            "terminal",
        )

    entry = {
        "status": "baixa_precisao" if status == "ok" else (status or "nao_encontrado"),
        "precisao": precision,
        "tentativas": attempts,
        "atualizado_em": datetime.now().isoformat(timespec="seconds"),
        "proxima_tentativa": (
            today + timedelta(days=STREET_RETRY_DAYS)
        ).isoformat(),
    }
    return entry, "baixa_precisao" if status == "ok" else (status or "nao_encontrado")


def apply_result(
    cache: dict, target: dict, result: dict, today: date
) -> tuple[dict, str, bool]:
    """Grava o resultado no cache e, se for o caso, o centroide do bairro."""
    ruas = cache.setdefault("ruas", {})
    previous = ruas.get(target["key"]) or {}
    attempts = int(previous.get("tentativas") or 0) + 1
    entry, kind = build_entry(result, today, attempts)
    ruas[target["key"]] = entry

    bairro_added = False
    if result.get("status") == "ok" and result.get("precisao") == "bairro":
        bairro_added = set_bairro_point(
            cache,
            target.get("uf", ""),
            target.get("cidade", ""),
            target.get("bairro", ""),
            result.get("lat"),
            result.get("lng"),
            result.get("fonte") or "nominatim",
        )
    return entry, kind, bairro_added


def run_queue(
    targets: list[dict],
    cache: dict,
    *,
    max_seconds: float,
    interval: float = 16.0,
    limit: int = 0,
    searcher=None,
    clock=time.monotonic,
    today: date | None = None,
    save=None,
    save_every: int = 25,
    save_interval: float = 60.0,
) -> dict:
    """Consulta a fila até o orçamento acabar e devolve estatísticas."""
    today = today or _today()
    if limit and limit > 0:
        targets = targets[:limit]

    geocode_client.MIN_INTERVAL = interval
    stats = {
        "consultadas": 0,
        "terminal": 0,
        "rua": 0,
        "endereco": 0,
        "bairro": 0,
        "baixa_precisao": 0,
        "nao_encontrado": 0,
        "erros": 0,
        "limite_api": False,
        "orcamento_esgotado": False,
        "bairros_adicionados": 0,
        "restantes": len(targets),
        "segundos": 0.0,
    }
    precisions: Counter = Counter()
    started = clock()
    deadline = started + max(0.0, max_seconds)
    last_save = started
    interrupted = False

    try:
        for index, target in enumerate(targets, start=1):
            if clock() >= deadline:
                stats["orcamento_esgotado"] = True
                break
            try:
                result = geocode_endereco(
                    target.get("uf", ""),
                    target.get("cidade", ""),
                    target.get("logradouro", ""),
                    numero="",
                    bairro=target.get("bairro", ""),
                    include_number=False,
                    searcher=searcher,
                )
            except geocode_client.RateLimitError:
                stats["limite_api"] = True
                break
            except KeyboardInterrupt:
                interrupted = True
                break
            except Exception:  # rede instável não vira "não encontrado"
                stats["erros"] += 1
                continue

            stats["consultadas"] += 1
            _, kind, bairro_added = apply_result(cache, target, result, today)
            stats["bairros_adicionados"] += int(bairro_added)
            if kind == "terminal":
                stats["terminal"] += 1
                precisions[result.get("precisao")] += 1
                stats[result.get("precisao")] += 1
            elif kind == "baixa_precisao":
                stats["baixa_precisao"] += 1
                if result.get("precisao") == "bairro":
                    stats["bairro"] += 1
            else:
                stats["nao_encontrado"] += 1

            now = clock()
            if save and (
                index % max(1, save_every) == 0
                or now - last_save >= save_interval
            ):
                save()
                last_save = now
    finally:
        if save:
            save()
        stats["segundos"] = round(clock() - started, 1)
        stats["restantes"] = max(0, len(targets) - stats["consultadas"])
    if interrupted:
        raise KeyboardInterrupt
    return stats


def _print_summary(stats: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(stats, ensure_ascii=False))
        return
    print(
        "Consultadas: {consultadas} · rua: {rua} · endereço: {endereco} · "
        "bairro: {bairro} · baixa precisão: {baixa_precisao} · "
        "não encontradas: {nao_encontrado} · erros: {erros} · "
        "restantes: {restantes} · {segundos}s".format(**stats)
    )
    if stats.get("bairros_adicionados"):
        print(f"Bairros adicionados ao cache: {stats['bairros_adicionados']}")
    if stats.get("limite_api"):
        print("Limite da API atingido; progresso salvo no cache.")
    if stats.get("orcamento_esgotado"):
        print("Orçamento de tempo esgotado; progresso salvo no cache.")


def _install_sigterm_handler() -> None:
    def _stop(signum, frame):  # pragma: no cover - sinal externo
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _stop)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--max-minutos",
        type=float,
        default=180.0,
        help="orçamento de consultas nesta execução (padrão: 180)",
    )
    parser.add_argument(
        "--intervalo",
        type=float,
        default=16.0,
        help="segundos entre requisições (4 req/min para scripts recorrentes)",
    )
    parser.add_argument(
        "--limite",
        type=int,
        default=0,
        help="máximo de ruas nesta execução (0 = todas)",
    )
    parser.add_argument(
        "--cache",
        type=Path,
        help="caminho do cache (padrão: data/geo/geocode_cache.json)",
    )
    parser.add_argument("--dry-run", action="store_true", help="só monta a fila")
    parser.add_argument("--json", action="store_true", help="resumo em JSON")
    args = parser.parse_args(argv)

    paths = Paths()
    cache_path = args.cache or paths.geocode_cache_file
    cache = load_geocode_cache(cache_path)

    items = publish.load_previous_items(paths)
    if not items:
        message = {"erro": "nenhum imóvel publicado"}
        if args.json:
            print(json.dumps(message, ensure_ascii=False))
        else:
            print("Nenhum imóvel publicado; nada a fazer.")
        return 0

    queue = build_queue(items, cache)
    if args.dry_run:
        summary = {
            "fila": len(queue),
            "novas": sum(1 for street in queue if street["nova"]),
            "retentativas": sum(1 for street in queue if not street["nova"]),
            "imoveis": sum(street["imoveis"] for street in queue),
        }
        if args.json:
            print(json.dumps(summary, ensure_ascii=False))
        else:
            print(
                f"Fila: {summary['fila']} ruas "
                f"({summary['novas']} novas, {summary['retentativas']} retentativas) "
                f"· {summary['imoveis']} imóveis"
            )
        return 0

    _install_sigterm_handler()
    try:
        stats = run_queue(
            queue,
            cache,
            max_seconds=args.max_minutos * 60,
            interval=args.intervalo,
            limit=args.limite,
            save=lambda: save_geocode_cache(cache_path, cache, paths.root),
        )
    except KeyboardInterrupt:
        print("Interrompido; progresso salvo no cache.", file=sys.stderr)
        return 0

    _print_summary(stats, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
