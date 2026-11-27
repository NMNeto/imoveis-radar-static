"""Orquestra coleta, normalização, geocodificação, diff e publicação."""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from . import paginas as paginas_generator
from . import publish as publisher
from . import sitemap as sitemap_generator
from .collect import CollectionContext, collect_all
from .config import (
    DEFAULT_CHUNK_SIZE,
    DEFAULT_COLLECTOR_ATTEMPTS,
    DEFAULT_COLLECTOR_RETRY_DELAY,
    DEFAULT_COLLECTOR_TIMEOUT,
    DEFAULT_GEOCODE_INTERVAL,
    DEFAULT_GEOCODE_MAX,
    DEFAULT_HISTORY_DAYS,
    DEFAULT_HTTP_RETRIES,
    DEFAULT_HTTP_TIMEOUT,
    DEFAULT_MAX_STALE_DAYS,
    DEFAULT_MIN_ROWS_RATIO,
    PROJECT_ROOT,
    SOURCE_FILES,
    SOURCE_NAMES,
    SOURCE_ORDER,
    Paths,
    RunOptions,
)
from .csv_sources import read_generation_date, read_source_rows
from .geo import (
    attach_coordinates,
    geocode_missing,
    load_geocode_cache,
    seed_geo_points,
)
from .locations import canonicalize_locations
from .model import (
    apply_history_timestamps,
    build_item,
    build_meta,
    build_stats,
    config_public_payload,
    dedupe_items,
    find_removed,
    load_settings,
    normalize_market_values,
    recompute_item,
    sort_items_deterministic,
    validate_items,
)
from .safety import (
    LockBusyError,
    assert_isolated,
    atomic_write_json,
    run_lock,
)
from .csv_sources import load_exclusions, load_market_values

logger = logging.getLogger(__name__)


class ConfigBundle:
    def __init__(self, paths: Paths):
        self.settings = load_settings(paths.config_file)
        market_path = paths.market_values_file
        if not market_path.exists():
            # Compatibilidade com o nome legado usado pelo projeto original.
            legacy = paths.config / "market_values.csv"
            if legacy.exists():
                market_path = legacy
        self.market_values = normalize_market_values(load_market_values(market_path))
        exclude_ids, exclude_locations = load_exclusions(
            paths.exclude_ids_file, paths.exclude_locations_file
        )
        self.exclude_ids = exclude_ids
        self.exclude_locations = exclude_locations
        from .model import build_exclusion_index

        self.exclusion_index = build_exclusion_index(exclude_locations)

    def public_payload(self) -> dict:
        return config_public_payload(
            {
                "settings": self.settings,
                "market_values": self.market_values,
                "exclude_ids": self.exclude_ids,
                "exclude_locations": self.exclude_locations,
            }
        )


def _setup_logging(paths: Paths, options: RunOptions) -> None:
    level = logging.DEBUG if options.verbose else logging.INFO
    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root.addHandler(console)

    log_path = options.log_file or (
        paths.logs / f"atualizacao-{datetime.now():%Y%m%d-%H%M%S}.log"
    )
    try:
        paths.logs.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        root.addHandler(file_handler)
        logger.info("Log da execução: %s", log_path)
    except OSError as exc:
        logger.warning("Não foi possível criar o log em arquivo: %s", exc)


def _load_previous_meta(paths: Paths) -> dict:
    path = paths.public_data / publisher.META_FILE
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _generation_date(
    paths: Paths, statuses: dict, previous_meta: dict
) -> str | None:
    caixa = statuses.get("caixa")
    if caixa and caixa.path and caixa.path.exists():
        value = read_generation_date(caixa.path)
        if value:
            return value
    if previous_meta.get("generation_date"):
        return previous_meta["generation_date"]
    mtimes = []
    for source_id in SOURCE_ORDER:
        path = paths.raw_csv(source_id)
        if path.exists():
            try:
                mtimes.append(
                    datetime.fromtimestamp(path.stat().st_mtime).date().isoformat()
                )
            except OSError:
                pass
    return max(mtimes) if mtimes else None


def _source_items(
    source_id: str,
    path: Path,
    config: ConfigBundle,
    cache: dict,
) -> list[dict]:
    items = []
    for raw_id, row in read_source_rows(path):
        item = build_item(
            source_id,
            raw_id,
            row,
            path.name,
            config.settings,
            config.market_values,
            config.exclusion_index,
            config.exclude_ids,
        )
        attach_coordinates(item, cache)
        items.append(item)
    return items


def _retained_items(
    source_id: str,
    previous_items: list[dict],
    config: ConfigBundle,
    cache: dict,
) -> list[dict]:
    result = []
    for item in previous_items:
        if item.get("fonte") != source_id:
            continue
        result.append(
            recompute_item(
                item,
                config.settings,
                config.market_values,
                config.exclusion_index,
                config.exclude_ids,
                cache,
            )
        )
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Atualiza os dados estáticos do Imóveis Radar. "
            "Lê as quatro fontes, valida, geocodifica e publica JSON em public/data/."
        )
    )
    parser.add_argument("--dry-run", action="store_true", help="não grava nada")
    parser.add_argument(
        "--skip-collect",
        action="store_true",
        help="usa os CSVs já existentes em data/raw/ (sem rede)",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="apenas valida os JSONs publicados",
    )
    parser.add_argument(
        "--force-publish",
        action="store_true",
        help="regrava os arquivos mesmo sem mudança de conteúdo",
    )
    parser.add_argument(
        "--allow-source-drop",
        action="store_true",
        help="aceita queda brusca na quantidade de imóveis de uma fonte",
    )
    parser.add_argument(
        "--no-geocode",
        action="store_true",
        help="não consulta Nominatim/Photon nesta execução",
    )
    parser.add_argument(
        "--sources",
        default=",".join(SOURCE_ORDER),
        help="fontes separadas por vírgula (padrão: todas)",
    )
    parser.add_argument(
        "--min-rows-ratio",
        type=float,
        default=DEFAULT_MIN_ROWS_RATIO,
        help="fração mínima em relação à coleta anterior",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=DEFAULT_CHUNK_SIZE,
        help="imóveis por arquivo JSON",
    )
    parser.add_argument("--http-timeout", type=int, default=DEFAULT_HTTP_TIMEOUT)
    parser.add_argument("--http-retries", type=int, default=DEFAULT_HTTP_RETRIES)
    parser.add_argument(
        "--collector-timeout", type=int, default=DEFAULT_COLLECTOR_TIMEOUT
    )
    parser.add_argument(
        "--collector-attempts",
        type=int,
        default=DEFAULT_COLLECTOR_ATTEMPTS,
        help="quantas vezes cada coletor é executado antes de desistir",
    )
    parser.add_argument(
        "--collector-retry-delay",
        type=float,
        default=DEFAULT_COLLECTOR_RETRY_DELAY,
        help="segundos de espera entre tentativas do mesmo coletor",
    )
    parser.add_argument(
        "--max-stale-days",
        type=int,
        default=DEFAULT_MAX_STALE_DAYS,
        help="dias de atraso no CSV da fonte antes de sinalizar",
    )
    parser.add_argument("--geocode-max", type=int, default=DEFAULT_GEOCODE_MAX)
    parser.add_argument(
        "--geocode-interval", type=float, default=DEFAULT_GEOCODE_INTERVAL
    )
    parser.add_argument("--history-days", type=int, default=DEFAULT_HISTORY_DAYS)
    parser.add_argument("--log-file", type=Path, default=None)
    parser.add_argument("--project-root", type=Path, default=None)
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--public-dir", type=Path, default=None)
    parser.add_argument(
        "--original-dir",
        type=Path,
        default=None,
        help="diretório do projeto original, apenas para a trava de isolamento",
    )
    parser.add_argument("--max-imoveis", type=int, default=None)
    parser.add_argument("--max-itau-pages", type=int, default=None)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--json", action="store_true", help="imprime resumo em JSON")
    return parser


def _paths_from_args(args) -> Paths:
    root = Path(
        args.project_root or os.environ.get("IMOVEIS_PROJECT_ROOT", PROJECT_ROOT)
    ).resolve()
    data = Path(
        args.data_dir or os.environ.get("IMOVEIS_DATA_DIR", root / "data")
    ).resolve()
    public = Path(
        args.public_dir or os.environ.get("IMOVEIS_PUBLIC_DIR", root / "public")
    ).resolve()
    return Paths(root=root, data=data, public=public)


def _options_from_args(args) -> RunOptions:
    sources = tuple(
        source.strip().lower() for source in args.sources.split(",") if source.strip()
    )
    extra = {}
    if args.max_imoveis:
        extra["MAX_IMOVEIS"] = args.max_imoveis
    if args.max_itau_pages:
        extra["MAX_ITAU_PAGES"] = args.max_itau_pages
    return RunOptions(
        dry_run=args.dry_run,
        skip_collect=args.skip_collect,
        validate_only=args.validate_only,
        force_publish=args.force_publish,
        allow_source_drop=args.allow_source_drop,
        geocode=not args.no_geocode,
        sources=sources,
        min_rows_ratio=args.min_rows_ratio,
        chunk_size=args.chunk_size,
        http_timeout=args.http_timeout,
        http_retries=args.http_retries,
        collector_timeout=args.collector_timeout,
        collector_attempts=args.collector_attempts,
        collector_retry_delay=args.collector_retry_delay,
        max_stale_days=args.max_stale_days,
        geocode_max=args.geocode_max,
        geocode_interval=args.geocode_interval,
        history_days=args.history_days,
        log_file=args.log_file,
        verbose=args.verbose,
        json_output=args.json,
        extra=extra,
    )


def _print_summary(summary: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    print("")
    print("Resumo da atualização")
    print(f"  total publicado ....: {summary.get('total', 0):,}".replace(",", "."))
    print(f"  novos ..............: {summary.get('novos', 0):,}".replace(",", "."))
    print(f"  alterados ..........: {summary.get('alterados', 0):,}".replace(",", "."))
    print(f"  removidos ..........: {summary.get('removidos', 0):,}".replace(",", "."))
    print(f"  fontes .............: {summary.get('fontes_resumo', '-')}")
    print(f"  geocodificação .....: {summary.get('geocodificacao', '-')}")
    print(f"  arquivos ...........: {summary.get('arquivos', 0)}")
    print(f"  hash ...............: {summary.get('sha256', '')[:16]}…")
    print(f"  resultado ..........: {summary.get('mensagem', '')}")
    print("")


def run(args) -> int:
    paths = _paths_from_args(args)
    if args.original_dir:
        os.environ["IMOVEIS_ORIGINAL_DIR"] = str(args.original_dir.resolve())
    assert_isolated(paths)
    options = _options_from_args(args)
    paths.ensure_dirs()
    _setup_logging(paths, options)

    if options.validate_only:
        return publisher.validate_existing(paths)

    try:
        with run_lock(paths):
            return _run_locked(paths, options)
    except LockBusyError as exc:
        logger.error("%s", exc)
        return 4
    except Exception:
        logger.exception("Falha inesperada na atualização")
        return 1


def _run_locked(paths: Paths, options: RunOptions) -> int:
    context = CollectionContext()
    try:
        previous_items = publisher.load_previous_items(paths)
        previous_meta = _load_previous_meta(paths)
        config = ConfigBundle(paths)
        cache = load_geocode_cache(paths.geocode_cache_file)
        seed_geo_points(cache, paths.seeds)

        logger.info(
            "Iniciando atualização%s; fontes: %s; dados anteriores: %s imóveis",
            " (simulação)" if options.dry_run else "",
            ", ".join(options.sources),
            len(previous_items),
        )

        statuses, successful = collect_all(
            paths, options, context, persist=not options.dry_run
        )

        if not successful and not previous_items:
            logger.error("Nenhuma fonte coletada e não há dados anteriores. Nada a publicar.")
            return 2

        items: list[dict] = []
        for source_id in SOURCE_ORDER:
            if source_id in options.sources:
                status = statuses.get(source_id)
                if status and status.ok and status.path:
                    items.extend(_source_items(source_id, status.path, config, cache))
                    continue
                logger.warning(
                    "%s: usando os %s itens da versão anterior.",
                    source_id,
                    sum(1 for item in previous_items if item.get("fonte") == source_id),
                )
            items.extend(_retained_items(source_id, previous_items, config, cache))

        items, duplicates = dedupe_items(items)
        if duplicates:
            logger.warning("%s item(ns) duplicado(s) removido(s).", duplicates)

        items, location_stats = canonicalize_locations(items)
        logger.info(
            "Locais normalizados: %s cidade(s), %s bairro(s), %s variante(s) "
            "de cidade e %s de bairro unificadas.",
            location_stats["cidades"],
            location_stats["bairros"],
            location_stats["variantes_cidade"],
            location_stats["variantes_bairro"],
        )

        geocode_stats = geocode_missing(items, cache, paths, options)
        for item in items:
            attach_coordinates(item, cache)

        items = sort_items_deterministic(items)
        errors = validate_items(items)
        if errors:
            logger.error("Validação falhou com %s erro(s):", len(errors))
            for error in errors[:30]:
                logger.error("  - %s", error)
            return 3

        now = datetime.now().isoformat(timespec="seconds")
        items, new_ids, changed_ids = apply_history_timestamps(
            items, previous_items, now
        )
        current_ids = {item["id"] for item in items}
        removed = find_removed(previous_items, current_ids, successful)

        digest = publisher.data_hash(items)
        previous_manifest = publisher.read_manifest(paths.public_data)
        previous_data_hash = (previous_manifest or {}).get("data_sha256") or (
            previous_manifest or {}
        ).get("sha256")
        data_changed = options.force_publish or previous_data_hash != digest
        data_atualizacao = (
            now
            if data_changed
            else (previous_manifest or {}).get("gerado_em") or now
        )

        source_files = {
            source_id: SOURCE_FILES[source_id]
            for source_id in SOURCE_ORDER
            if any(item.get("fonte") == source_id for item in items)
        }
        generation_date = _generation_date(paths, statuses, previous_meta)
        meta = build_meta(
            items,
            source_files,
            generation_date,
            config.market_values,
            config.exclude_ids,
            config.exclude_locations,
            cache,
            config.settings,
        )

        source_status = {}
        for source_id in SOURCE_ORDER:
            status = statuses.get(source_id)
            if status:
                source_status[source_id] = status.as_dict()
            else:
                source_status[source_id] = {
                    "source": source_id,
                    "nome": SOURCE_NAMES[source_id],
                    "status": "retido",
                    "rows": sum(
                        1 for item in previous_items if item.get("fonte") == source_id
                    ),
                    "last_error": None,
                }

        stats = build_stats(
            items,
            previous_items,
            new_ids,
            changed_ids,
            removed,
            geocode_stats,
            source_status,
            digest,
            data_atualizacao,
        )
        stats["locais"] = location_stats
        last_update = {
            "data_atualizacao": data_atualizacao,
            "ultima_execucao": now,
            "total": len(items),
            "novos": len(new_ids),
            "alterados": len(changed_ids),
            "removidos": len(removed),
            "excluidos": meta.get("exclude_ids_count", 0),
            "sha256": digest,
            "fontes": source_status,
            "geocodificacao": geocode_stats,
            "locais": location_stats,
        }

        result = publisher.publish(
            paths,
            items,
            meta,
            stats,
            last_update,
            config.public_payload(),
            chunk_size=options.chunk_size,
            dry_run=options.dry_run,
            force=options.force_publish,
        )

        paginas_result = None
        sitemap_result = None
        if not options.dry_run and not result.validation_errors:
            # Páginas primeiro: o sitemap é derivado do que existe em public/.
            paginas_result = paginas_generator.generate(paths.public, items)
            sitemap_result = sitemap_generator.generate(paths.public)

        history_changed = False
        if result.changed and not result.validation_errors:
            history = publisher.load_history(paths.history_file)
            history_changed = publisher.update_history(
                history, removed, current_ids, now, options.history_days
            )
            if history_changed and not options.dry_run:
                atomic_write_json(paths.history_file, history, paths.data)
                logger.info("Histórico de removidos atualizado.")
            elif history_changed and options.dry_run:
                logger.info("Simulação: histórico de removidos seria atualizado.")

        summary = {
            "ok": not result.validation_errors,
            "dry_run": options.dry_run,
            "total": len(items),
            "novos": len(new_ids),
            "alterados": len(changed_ids),
            "removidos": len(removed),
            "duplicados": duplicates,
            "sha256": digest,
            "mudou": result.changed,
            "arquivos": len(result.files_written),
            "blocos": len(result.chunks),
            "sitemap": sitemap_result.as_dict() if sitemap_result else None,
            "paginas_seo": paginas_result,
            "fontes_resumo": ", ".join(
                f"{source}: {status.get('status', '?')} ({status.get('rows', 0)})"
                for source, status in source_status.items()
            ),
            "geocodificacao": geocode_stats,
            "locais": location_stats,
            "geracao": generation_date,
            "data_atualizacao": data_atualizacao,
            "historico_alterado": history_changed,
            "mensagem": result.message,
            "erros": result.validation_errors,
        }
        if not options.dry_run:
            try:
                atomic_write_json(
                    paths.logs / "ultima-execucao.json", summary, paths.data
                )
            except OSError as exc:
                logger.warning("Não foi possível gravar o resumo: %s", exc)
        _print_summary(summary, as_json=options.json_output)
        if result.validation_errors:
            return 3
        if not result.changed and not previous_items:
            return 2
        return 0
    finally:
        context.cleanup()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return run(args)
