"""Coleta das quatro fontes com validação, timeout e preservação da última versão.

Regras:
* cada coletor escreve em um diretório temporário;
* o CSV só substitui o anterior depois de validado;
* falha de uma fonte nunca apaga os dados anteriores dela;
* nenhum arquivo é gravado fora de ``data/``.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import requests

from .config import (
    CAIXA_URL,
    DEFAULT_MIN_ROWS,
    SOURCE_COLLECTORS,
    SOURCE_FILES,
    SOURCE_NAMES,
    Paths,
    RunOptions,
)
from .csv_sources import SourceFile, read_source_rows, validate_source_csv
from .safety import atomic_write_json, ensure_within

logger = logging.getLogger(__name__)

CAIXA_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64; rv:150.0) Gecko/20100101 Firefox/150.0"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Priority": "u=0, i",
    "Connection": "keep-alive",
}


@dataclass
class CollectedSource:
    source_id: str
    status: str
    path: Path | None = None
    rows: int = 0
    previous_rows: int = 0
    last_success: str | None = None
    last_error: str | None = None
    duration_s: float = 0.0
    persisted: bool = False
    temporary_dir: Path | None = None
    details: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def as_dict(self) -> dict:
        return {
            "source": self.source_id,
            "nome": SOURCE_NAMES.get(self.source_id, self.source_id),
            "status": self.status,
            "rows": self.rows,
            "previous_rows": self.previous_rows,
            "last_success": self.last_success,
            "last_error": self.last_error,
            "duration_s": round(self.duration_s, 2),
            "persisted": self.persisted,
            **self.details,
        }


class CollectionContext:
    """Mantém diretórios temporários vivos até o fim do build."""

    def __init__(self) -> None:
        self._dirs: list[Path] = []

    def new_dir(self, prefix: str) -> Path:
        path = Path(tempfile.mkdtemp(prefix=f"imoveis-{prefix}-"))
        self._dirs.append(path)
        return path

    def adopt(self, path: Path) -> None:
        self._dirs.append(path)

    def cleanup(self) -> None:
        for path in self._dirs:
            shutil.rmtree(path, ignore_errors=True)
        self._dirs.clear()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _previous_rows(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        return len(read_source_rows(path))
    except Exception:
        return 0


def _write_source_status(paths: Paths, statuses: dict[str, dict]) -> None:
    payload = {
        "atualizado_em": _now(),
        "fontes": statuses,
    }
    try:
        atomic_write_json(paths.logs / "status-fontes.json", payload, paths.data)
    except Exception as exc:  # status nunca derruba a atualização
        logger.warning("Não foi possível gravar status das fontes: %s", exc)


def _validate(
    path: Path,
    source_id: str,
    options: RunOptions,
    previous_rows: int,
) -> SourceFile:
    return validate_source_csv(
        path,
        source_id,
        min_rows=DEFAULT_MIN_ROWS.get(source_id, 1),
        min_rows_ratio=options.min_rows_ratio,
        previous_rows=previous_rows,
        allow_source_drop=options.allow_source_drop,
    )


def download_caixa(
    paths: Paths,
    options: RunOptions,
    context: CollectionContext,
    persist: bool,
) -> CollectedSource:
    started = time.time()
    target = paths.raw_csv("caixa")
    previous_rows = _previous_rows(target)
    work_dir = context.new_dir("caixa")
    temp_csv = work_dir / "Lista_imoveis_geral.csv"
    status = CollectedSource(
        source_id="caixa",
        status="falhou",
        path=target if target.exists() else None,
        previous_rows=previous_rows,
        temporary_dir=work_dir,
    )

    last_error = None
    for attempt in range(1, options.http_retries + 1):
        try:
            logger.info("Baixando CSV da Caixa (tentativa %s/%s)…", attempt, options.http_retries)
            response = requests.get(
                CAIXA_URL,
                headers=CAIXA_HEADERS,
                timeout=options.http_timeout,
            )
            if response.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(
                    f"HTTP {response.status_code}", response=response
                )
            response.raise_for_status()
            content = response.content
            if len(content) < options.min_caixa_bytes:
                raise RuntimeError(f"resposta pequena demais ({len(content)} bytes)")
            probe = content[:4096].decode("latin1", errors="ignore").lower()
            if probe.lstrip().startswith("<") or "captcha" in probe or "radware" in probe:
                raise RuntimeError("Caixa retornou CAPTCHA/HTML em vez do CSV")
            with open(temp_csv, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            source_file = _validate(temp_csv, "caixa", options, previous_rows)
            if persist:
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(temp_csv, target)
                status.path = target
                status.persisted = True
            else:
                status.path = temp_csv
            status.status = "ok"
            status.rows = source_file.rows
            status.last_success = _now()
            status.last_error = None
            status.details.update(
                {
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "bytes": len(content),
                    "url": CAIXA_URL,
                    "generation_date": source_file.generation_date,
                }
            )
            logger.info("Caixa: %s imóveis baixados e validados.", status.rows)
            break
        except Exception as exc:
            last_error = str(exc)
            logger.warning("Falha na Caixa (tentativa %s): %s", attempt, exc)
            if attempt < options.http_retries:
                time.sleep(min(30, 5 * (2 ** (attempt - 1))))

    if status.status != "ok":
        status.last_error = last_error
        if target.exists():
            status.path = target
            status.rows = previous_rows
            logger.error(
                "Caixa falhou; mantendo a versão anterior (%s linhas).", previous_rows
            )
    status.duration_s = time.time() - started
    return status


def run_collector(
    source_id: str,
    paths: Paths,
    options: RunOptions,
    context: CollectionContext,
    persist: bool,
) -> CollectedSource:
    started = time.time()
    target = paths.raw_csv(source_id)
    previous_rows = _previous_rows(target)
    work_dir = context.new_dir(source_id)
    status = CollectedSource(
        source_id=source_id,
        status="falhou",
        path=target if target.exists() else None,
        previous_rows=previous_rows,
        temporary_dir=work_dir,
    )
    script_name = SOURCE_COLLECTORS.get(source_id)
    if not script_name:
        status.last_error = f"coletor não configurado para {source_id}"
        return status
    script = paths.collectors / script_name
    if not script.exists():
        status.last_error = f"coletor ausente: {script}"
        return status

    env = os.environ.copy()
    env.update(
        {
            "SOURCE_OUTPUT_DIR": str(work_dir),
            "SOURCE_DATE_PREFIX": "",
            "SOURCE_CSV_ONLY": "1",
            "PYTHONUNBUFFERED": "1",
        }
    )
    for key in ("MAX_IMOVEIS", "MAX_ITAU_PAGES", "MAX_SANTANDER_PAGES"):
        if options.extra.get(key):
            env[key] = str(options.extra[key])

    log_path = paths.logs / f"coletor-{source_id}-{datetime.now():%Y%m%d-%H%M%S}.log"
    try:
        logger.info("Executando coletor %s (timeout %ss)…", source_id, options.collector_timeout)
        completed = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(work_dir),
            env=env,
            capture_output=True,
            text=True,
            timeout=options.collector_timeout,
        )
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            f"$ {sys.executable} {script}\n"
            f"exit={completed.returncode}\n"
            f"--- stdout ---\n{completed.stdout or ''}\n"
            f"--- stderr ---\n{completed.stderr or ''}\n",
            encoding="utf-8",
        )
        if completed.returncode != 0:
            tail = (completed.stderr or completed.stdout or "").strip().splitlines()
            raise RuntimeError(tail[-1] if tail else f"coletor saiu com código {completed.returncode}")

        csv_path = work_dir / SOURCE_FILES[source_id]
        if not csv_path.exists():
            candidates = list(work_dir.glob(f"*{SOURCE_FILES[source_id]}"))
            if candidates:
                csv_path = candidates[0]
        source_file = _validate(csv_path, source_id, options, previous_rows)
        if persist:
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(csv_path, target)
            status.path = target
            status.persisted = True
        else:
            status.path = csv_path
        status.status = "ok"
        status.rows = source_file.rows
        status.last_success = _now()
        status.last_error = None
        status.details.update(
            {
                "generation_date": source_file.generation_date,
                "log": log_path.name,
            }
        )
        logger.info("%s: %s imóveis coletados e validados.", source_id, status.rows)
    except subprocess.TimeoutExpired:
        status.last_error = f"coletor excedeu {options.collector_timeout}s"
        logger.error("%s: %s", source_id, status.last_error)
    except Exception as exc:
        status.last_error = str(exc)
        logger.exception("%s: falha na coleta: %s", source_id, exc)

    if status.status != "ok":
        if target.exists():
            status.path = target
            status.rows = previous_rows
            logger.error(
                "%s falhou; mantendo a versão anterior (%s linhas).",
                source_id,
                previous_rows,
            )
    status.duration_s = time.time() - started
    return status


def collect_all(
    paths: Paths,
    options: RunOptions,
    context: CollectionContext,
    persist: bool,
) -> tuple[dict[str, CollectedSource], set[str]]:
    statuses: dict[str, CollectedSource] = {}
    for source_id in options.sources:
        if options.skip_collect:
            target = paths.raw_csv(source_id)
            try:
                source_file = _validate(target, source_id, options, 0)
                statuses[source_id] = CollectedSource(
                    source_id=source_id,
                    status="ok",
                    path=target,
                    rows=source_file.rows,
                    previous_rows=source_file.rows,
                    last_success=source_file.generation_date,
                    persisted=False,
                    details={"modo": "dados existentes"},
                )
                logger.info("%s: usando dados existentes (%s linhas).", source_id, source_file.rows)
            except Exception as exc:
                statuses[source_id] = CollectedSource(
                    source_id=source_id,
                    status="falhou",
                    path=target if target.exists() else None,
                    last_error=str(exc),
                    details={"modo": "dados existentes"},
                )
                logger.warning("%s: dados existentes inválidos: %s", source_id, exc)
            continue

        if source_id == "caixa":
            status = download_caixa(paths, options, context, persist)
        else:
            status = run_collector(source_id, paths, options, context, persist)
        statuses[source_id] = status

    successful = {source_id for source_id, status in statuses.items() if status.ok}
    _write_source_status(paths, {key: value.as_dict() for key, value in statuses.items()})
    return statuses, successful
