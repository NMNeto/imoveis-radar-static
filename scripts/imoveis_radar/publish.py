"""Publicação atômica dos JSONs, CSV, estatísticas e histórico."""
from __future__ import annotations

import glob
import hashlib
import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from .config import (
    PAGES_MAX_FILE_BYTES,
    PAGES_MAX_FILES,
    Paths,
)
from .model import items_to_csv, validate_items
from .safety import atomic_write_bytes, atomic_write_json, canonical_json_bytes

logger = logging.getLogger(__name__)

FORMAT_VERSION = 1
MANIFEST_FILE = "manifest.json"
META_FILE = "meta.json"
STATS_FILE = "estatisticas.json"
LAST_UPDATE_FILE = "ultima_atualizacao.json"
CONFIG_PUBLIC_FILE = "config.json"
CSV_FILE = "busca_imoveis.csv"


@dataclass
class PublishResult:
    changed: bool
    dry_run: bool
    data_hash: str
    total: int
    chunks: list[str] = field(default_factory=list)
    files_written: list[str] = field(default_factory=list)
    validation_errors: list[str] = field(default_factory=list)
    message: str = ""


def _chunk_names(count: int, digest: str | None = None) -> list[str]:
    width = max(3, len(str(max(0, count - 1))))
    prefix = f"imoveis-{digest[:12]}-" if digest else "imoveis-"
    return [f"{prefix}{index:0{width}d}.json" for index in range(count)]


def chunk_items(
    items: list[dict], size: int, digest: str | None = None
) -> tuple[list[list[dict]], list[str]]:
    if size < 1:
        raise ValueError("Tamanho de bloco inválido")
    chunks = [items[index : index + size] for index in range(0, len(items), size)]
    return chunks, _chunk_names(len(chunks), digest)


def data_hash(items: list[dict]) -> str:
    digest = hashlib.sha256()
    for item in items:
        payload = json.dumps(
            item, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        digest.update(payload.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def payload_hash(payload) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def read_manifest(public_data: Path) -> dict | None:
    path = public_data / MANIFEST_FILE
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def load_previous_items(paths: Paths) -> list[dict]:
    """Lê a versão publicada anterior, se existir."""
    manifest = read_manifest(paths.public_data)
    if manifest:
        chunks = manifest.get("chunks") or []
        items: list[dict] = []
        for name in chunks:
            path = paths.public_data / name
            if not path.exists():
                logger.warning("Bloco anterior ausente: %s", path)
                return []
            try:
                with open(path, encoding="utf-8") as handle:
                    payload = json.load(handle)
            except (OSError, ValueError):
                logger.warning("Bloco anterior inválido: %s", path)
                return []
            if not isinstance(payload, list):
                return []
            items.extend(payload)
        return items

    # Compatibilidade com uma versão inicial de arquivo único.
    for candidate in (
        paths.public_data / "imoveis.json",
        paths.data / "imoveis.json",
    ):
        if candidate.exists():
            try:
                with open(candidate, encoding="utf-8") as handle:
                    payload = json.load(handle)
                if isinstance(payload, list):
                    return payload
            except (OSError, ValueError):
                return []
    return []


def load_history(path: Path) -> dict:
    if not path.exists():
        return {"version": 1, "updated": None, "items": {}}
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {"version": 1, "updated": None, "items": {}}
    if not isinstance(data, dict):
        return {"version": 1, "updated": None, "items": {}}
    data.setdefault("version", 1)
    data.setdefault("items", {})
    return data


def _history_snapshot(item: dict) -> dict:
    fields = (
        "id",
        "id_fonte",
        "fonte",
        "fonte_nome",
        "uf",
        "cidade",
        "bairro",
        "endereco",
        "preco",
        "valor_avaliacao",
        "modalidade",
        "link",
        "imagem",
    )
    return {field: item.get(field) for field in fields}


def update_history(
    history: dict,
    removed: list[dict],
    current_ids: set[str],
    now: str,
    days: int,
) -> bool:
    items = history.setdefault("items", {})
    changed = False
    for item in removed:
        items[item["id"]] = {
            "removido_em": now,
            "motivo": "ausente na fonte",
            "item": _history_snapshot(item),
        }
        changed = True
    for item_id in list(items):
        if item_id in current_ids:
            items.pop(item_id, None)
            changed = True
    cutoff = datetime.now() - timedelta(days=days)
    for item_id, entry in list(items.items()):
        removed_at = entry.get("removido_em")
        try:
            when = datetime.fromisoformat(removed_at)
        except (TypeError, ValueError):
            continue
        if when < cutoff:
            items.pop(item_id, None)
            changed = True
    if changed:
        history["updated"] = now
    return changed


def _write_public(paths: Paths, name: str, payload: bytes, result: PublishResult) -> None:
    target = paths.public_data / name
    if atomic_write_bytes(target, payload, paths.public):
        result.files_written.append(name)


def _validate_sizes(directory: Path, names: list[str]) -> list[str]:
    errors = []
    for name in names:
        path = directory / name
        if not path.exists():
            errors.append(f"arquivo ausente: {name}")
            continue
        if path.stat().st_size > PAGES_MAX_FILE_BYTES:
            errors.append(
                f"arquivo {name} tem {path.stat().st_size} bytes; "
                f"limite Cloudflare Pages: {PAGES_MAX_FILE_BYTES}"
            )
    return errors


def publish(
    paths: Paths,
    items: list[dict],
    meta: dict,
    stats: dict,
    last_update: dict,
    config_public: dict,
    *,
    chunk_size: int,
    dry_run: bool = False,
    force: bool = False,
) -> PublishResult:
    """Publica os dados.  Só substitui a versão anterior após validar tudo."""
    source_order = {"caixa": 0, "bb": 1, "santander": 2, "itau": 3}
    # Estável: mantém a ordem das linhas de cada CSV, como no projeto original.
    items = sorted(items, key=lambda item: source_order.get(item.get("fonte"), 99))
    errors = validate_items(items)
    if errors:
        return PublishResult(
            changed=False,
            dry_run=dry_run,
            data_hash="",
            total=len(items),
            validation_errors=errors[:50],
            message="Validação falhou; nada foi publicado",
        )

    digest = data_hash(items)
    meta_digest = payload_hash(meta)
    config_digest = payload_hash(config_public)
    version_digest = hashlib.sha256(
        f"{digest}:{meta_digest}:{config_digest}".encode("utf-8")
    ).hexdigest()
    # Nome dos blocos derivado do conteúdo dos itens: mudanças só de config/meta
    # não renomeiam nem regravam os blocos.
    chunks, chunk_names = chunk_items(items, chunk_size, digest)
    previous = read_manifest(paths.public_data)
    previous_hash = (previous or {}).get("sha256")
    changed = force or previous_hash != version_digest

    result = PublishResult(
        changed=changed,
        dry_run=dry_run,
        data_hash=digest,
        total=len(items),
        chunks=chunk_names,
    )
    if not changed:
        result.message = "Sem alterações nos dados; versão anterior preservada"
        logger.info(result.message)
        return result

    manifest = {
        "formato": "imoveis-radar-static/1",
        "versao": FORMAT_VERSION,
        "sha256": version_digest,
        "data_sha256": digest,
        "meta_sha256": meta_digest,
        "config_sha256": config_digest,
        "gerado_em": last_update.get("data_atualizacao"),
        "total": len(items),
        "chunks": chunk_names,
        "fontes": meta.get("fontes", []),
        "config": {
            "settings": config_public.get("settings", {}),
            "market_values_count": len(config_public.get("market_values", {})),
            "exclude_ids_count": len(config_public.get("exclude_ids", [])),
            "exclude_locations_count": len(config_public.get("exclude_locations", [])),
        },
        "arquivos": {
            "meta": META_FILE,
            "estatisticas": STATS_FILE,
            "ultima_atualizacao": LAST_UPDATE_FILE,
            "config": CONFIG_PUBLIC_FILE,
            "csv": CSV_FILE,
        },
    }

    target_dir = paths.public_data
    temporary = None
    write_root = paths.public
    if dry_run:
        temporary = tempfile.TemporaryDirectory(prefix="imoveis-dry-run-")
        target_dir = Path(temporary.name)
        write_root = target_dir
        logger.info("Simulação: gravando em diretório temporário %s", target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    def write(name: str, payload: bytes) -> None:
        target = target_dir / name
        if atomic_write_bytes(target, payload, write_root):
            result.files_written.append(name)

    # Blocos primeiro.
    for chunk, name in zip(chunks, chunk_names):
        write(name, canonical_json_bytes(chunk))

    # Arquivos auxiliares.
    write(META_FILE, canonical_json_bytes(meta))
    write(STATS_FILE, canonical_json_bytes(stats))
    write(LAST_UPDATE_FILE, canonical_json_bytes(last_update))
    write(CONFIG_PUBLIC_FILE, canonical_json_bytes(config_public))
    write(CSV_FILE, items_to_csv(items).encode("utf-8"))

    # Manifesto por último: um leitor sempre vê uma versão coerente.
    write(MANIFEST_FILE, canonical_json_bytes(manifest))

    # Valida os arquivos gerados antes de considerar a publicação concluída.
    all_names = chunk_names + [
        META_FILE,
        STATS_FILE,
        LAST_UPDATE_FILE,
        CONFIG_PUBLIC_FILE,
        CSV_FILE,
        MANIFEST_FILE,
    ]
    errors = _validate_sizes(target_dir, all_names)
    if errors:
        result.validation_errors = errors
        result.message = "Arquivos gerados fora dos limites; publicação falhou"
        logger.error(result.message)
        return result

    if not dry_run:
        # Remove blocos antigos que não fazem mais parte do manifesto.
        keep = set(chunk_names)
        for path in glob.glob(str(paths.public_data / "imoveis-*.json")):
            if Path(path).name not in keep:
                try:
                    os.unlink(path)
                    logger.info("Bloco antigo removido: %s", Path(path).name)
                except OSError:
                    pass

    result.message = "Dados publicados"
    logger.info(
        "%s: %s imóveis em %s bloco(s); %s",
        result.message,
        len(items),
        len(chunk_names),
        "simulação" if dry_run else "arquivos atualizados",
    )
    if temporary is not None:
        temporary.cleanup()
    return result


def validate_public_dataset(paths: Paths) -> dict:
    """Valida a versão publicada e devolve um relatório."""
    report = {
        "ok": False,
        "errors": [],
        "warnings": [],
        "total": 0,
        "chunks": 0,
        "files": 0,
        "largest_file": 0,
        "largest_file_name": None,
    }
    manifest = read_manifest(paths.public_data)
    if not manifest:
        report["errors"].append("manifest.json ausente ou inválido")
        return report
    chunk_names = manifest.get("chunks") or []
    if not isinstance(chunk_names, list) or not chunk_names:
        report["errors"].append("manifest.json sem lista de blocos")
        return report

    items: list[dict] = []
    for name in chunk_names:
        path = paths.public_data / name
        if not path.exists():
            report["errors"].append(f"bloco ausente: {name}")
            continue
        size = path.stat().st_size
        report["files"] += 1
        if size > report["largest_file"]:
            report["largest_file"] = size
            report["largest_file_name"] = name
        if size > PAGES_MAX_FILE_BYTES:
            report["errors"].append(f"bloco {name} excede 25 MiB")
        try:
            with open(path, encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, ValueError) as exc:
            report["errors"].append(f"bloco {name} inválido: {exc}")
            continue
        if not isinstance(payload, list):
            report["errors"].append(f"bloco {name} não é uma lista")
            continue
        items.extend(payload)

    report["chunks"] = len(chunk_names)
    report["total"] = len(items)
    if manifest.get("total") != len(items):
        report["errors"].append(
            f"manifest.total={manifest.get('total')} difere dos {len(items)} itens"
        )
    report["errors"].extend(validate_items(items)[:100])

    meta_path = paths.public_data / (manifest.get("arquivos", {}).get("meta") or META_FILE)
    if not meta_path.exists():
        report["errors"].append("meta.json ausente")
    else:
        try:
            with open(meta_path, encoding="utf-8") as handle:
                meta = json.load(handle)
            if meta.get("total_properties") != len(items):
                report["errors"].append(
                    "meta.total_properties difere da quantidade de itens"
                )
            report["files"] += 1
        except (OSError, ValueError) as exc:
            report["errors"].append(f"meta.json inválido: {exc}")

    for name in (STATS_FILE, LAST_UPDATE_FILE, CONFIG_PUBLIC_FILE, CSV_FILE):
        path = paths.public_data / name
        if not path.exists():
            report["warnings"].append(f"arquivo auxiliar ausente: {name}")
        else:
            report["files"] += 1
            if path.stat().st_size > PAGES_MAX_FILE_BYTES:
                report["errors"].append(f"{name} excede 25 MiB")

    if report["files"] > PAGES_MAX_FILES:
        report["errors"].append(
            f"{report['files']} arquivos excedem o limite de {PAGES_MAX_FILES} do Pages"
        )
    report["ok"] = not report["errors"]
    return report


def validate_existing(paths: Paths) -> int:
    report = validate_public_dataset(paths)
    if report["ok"]:
        logger.info(
            "JSON válido: %s imóveis, %s bloco(s), %s arquivo(s); maior arquivo %.1f MiB",
            report["total"],
            report["chunks"],
            report["files"],
            report["largest_file"] / 1024 / 1024,
        )
        for warning in report["warnings"]:
            logger.warning(warning)
        return 0
    for error in report["errors"]:
        logger.error(error)
    return 1
