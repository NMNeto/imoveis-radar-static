"""Proteções de isolamento e gravação atômica.

Regra de ouro: qualquer escrita precisa acontecer dentro de ``paths.data`` ou
``paths.public``.  Se ``IMOVEIS_ORIGINAL_DIR`` estiver definido, o script
recusa rodar quando o diretório do projeto novo estiver dentro (ou contiver) o
projeto original.
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import tempfile
from pathlib import Path

from .config import Paths


class UnsafePathError(RuntimeError):
    """Tentativa de escrita fora do projeto novo."""


class LockBusyError(RuntimeError):
    """Outra execução do atualizador está em andamento."""


def _resolve(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:
        return path.absolute()


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        _resolve(path).relative_to(_resolve(root))
        return True
    except ValueError:
        return False


def ensure_within(path: Path, root: Path) -> Path:
    resolved = _resolve(path)
    root_resolved = _resolve(root)
    if not is_relative_to(resolved, root_resolved):
        raise UnsafePathError(f"Escrita recusada fora de {root_resolved}: {resolved}")
    return resolved


def assert_isolated(paths: Paths) -> None:
    """Valida que os diretórios de escrita estão contidos no projeto novo."""
    root = _resolve(paths.root)
    for path in (paths.data, paths.public):
        if not is_relative_to(path, root):
            raise UnsafePathError(
                f"Diretório de escrita {_resolve(path)} não está dentro do projeto {root}"
            )
    original = os.environ.get("IMOVEIS_ORIGINAL_DIR")
    if original:
        original_path = _resolve(Path(original))
        if is_relative_to(root, original_path) or is_relative_to(original_path, root):
            raise UnsafePathError(
                "O projeto novo e o projeto original se sobrepõem: "
                f"{root} x {original_path}"
            )


def assert_not_original(paths: Paths, original: str | Path) -> None:
    original_path = _resolve(Path(original))
    for path in (paths.data, paths.public, paths.root):
        if is_relative_to(path, original_path):
            raise UnsafePathError(f"Operação recusada dentro do projeto original: {path}")


def atomic_write_bytes(path: Path, data: bytes, root: Path) -> bool:
    """Grava ``data`` atomicamente.  Retorna False se o conteúdo já é igual."""
    target = ensure_within(path, root)
    if target.exists():
        try:
            if target.read_bytes() == data:
                return False
        except OSError:
            pass
    target.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "wb", dir=str(target.parent), prefix=f".{target.name}.", delete=False
    )
    try:
        with handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(handle.name, 0o664)
        os.replace(handle.name, target)
    finally:
        with contextlib.suppress(OSError):
            if os.path.exists(handle.name):
                os.unlink(handle.name)
    return True


def canonical_json_bytes(payload) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def atomic_write_json(path: Path, payload, root: Path) -> bool:
    return atomic_write_bytes(path, canonical_json_bytes(payload), root)


@contextlib.contextmanager
def run_lock(paths: Paths, blocking: bool = False):
    """Impede duas atualizações concorrentes no mesmo diretório de dados."""
    lock_path = paths.data / ".atualizacao.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path, "a+", encoding="utf-8")
    try:
        flags = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
        try:
            fcntl.flock(handle.fileno(), flags)
        except BlockingIOError as exc:
            raise LockBusyError(
                "Outra atualização já está em execução (arquivo .atualizacao.lock)"
            ) from exc
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        yield
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()
