#!/usr/bin/env python3
"""Ponto de entrada do atualizador de imóveis.

Uso:
    python scripts/atualizar_imoveis.py --help
    python scripts/atualizar_imoveis.py --dry-run
    python scripts/atualizar_imoveis.py --skip-collect
    python scripts/atualizar_imoveis.py --validate-only
"""
from __future__ import annotations

import sys
from pathlib import Path

# Permite executar o arquivo diretamente (sem instalar pacote).
sys.path.insert(0, str(Path(__file__).resolve().parent))

from imoveis_radar.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
