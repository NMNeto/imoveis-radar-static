"""Caminhos, constantes e opções de execução.

Todo caminho de escrita é derivado de :class:`Paths`.  O restante do código
nunca escreve fora de ``data/`` ou ``public/`` do projeto novo.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

SOURCE_NAMES = {
    "caixa": "Caixa",
    "bb": "Banco do Brasil",
    "santander": "Santander",
    "itau": "Itaú",
}

SOURCE_ORDER = tuple(SOURCE_NAMES)

#: Arquivo produzido/consumido por cada fonte.  O caminho é relativo a
#: ``data/raw/<fonte>/``.
SOURCE_FILES = {
    "caixa": "Lista_imoveis_geral.csv",
    "bb": "imoveis_bb_geral.csv",
    "santander": "santander_imoveis_geral.csv",
    "itau": "itau_imoveis_geral.csv",
}

#: Coletor Playwright de cada fonte (None = download HTTP simples).
SOURCE_COLLECTORS = {
    "caixa": "extrair_caixa.py",
    "bb": "extrair_bb.py",
    "santander": "extrair_santander.py",
    "itau": "extrair_itau.py",
}

CAIXA_URL = os.environ.get(
    "IMOVEIS_CAIXA_URL",
    "https://venda-imoveis.caixa.gov.br/listaweb/Lista_imoveis_geral.csv",
)

#: Abaixo desta fração da quantidade anterior a fonte é considerada suspeita
#: (portal bloqueado, página vazia, CAPTCHA).  Pode ser ajustada por ambiente.
DEFAULT_MIN_ROWS_RATIO = float(os.environ.get("IMOVEIS_MIN_ROWS_RATIO", "0.5"))
DEFAULT_MIN_ROWS = {
    "caixa": int(os.environ.get("IMOVEIS_MIN_ROWS_CAIXA", "1000")),
    "bb": int(os.environ.get("IMOVEIS_MIN_ROWS_BB", "10")),
    "santander": int(os.environ.get("IMOVEIS_MIN_ROWS_SANTANDER", "10")),
    "itau": int(os.environ.get("IMOVEIS_MIN_ROWS_ITAU", "5")),
}

DEFAULT_CHUNK_SIZE = int(os.environ.get("IMOVEIS_MAX_ITEMS_POR_ARQUIVO", "6000"))
DEFAULT_MIN_CAIXA_BYTES = int(os.environ.get("IMOVEIS_MIN_BYTES_CAIXA", "100000"))
DEFAULT_HTTP_TIMEOUT = int(os.environ.get("IMOVEIS_HTTP_TIMEOUT", "60"))
DEFAULT_HTTP_RETRIES = int(os.environ.get("IMOVEIS_HTTP_RETRIES", "3"))
DEFAULT_COLLECTOR_TIMEOUT = int(os.environ.get("IMOVEIS_COLLECTOR_TIMEOUT", "1800"))
#: Quantas vezes um coletor Playwright é executado antes de desistir.
DEFAULT_COLLECTOR_ATTEMPTS = int(os.environ.get("IMOVEIS_COLLECTOR_ATTEMPTS", "2"))
#: Espera entre tentativas do mesmo coletor (segundos).
DEFAULT_COLLECTOR_RETRY_DELAY = float(
    os.environ.get("IMOVEIS_COLLECTOR_RETRY_DELAY", "120")
)
#: Dias entre a geração do CSV da fonte e hoje antes de sinalizar atraso.
DEFAULT_MAX_STALE_DAYS = int(os.environ.get("IMOVEIS_MAX_STALE_DAYS", "3"))
DEFAULT_GEOCODE_MAX = int(os.environ.get("IMOVEIS_GEOCODE_MAX", "200"))
DEFAULT_GEOCODE_INTERVAL = float(os.environ.get("IMOVEIS_GEOCODE_INTERVAL", "1.5"))
DEFAULT_HISTORY_DAYS = int(os.environ.get("IMOVEIS_HISTORY_DAYS", "365"))

#: Limites da Cloudflare Pages (documentados em docs/franquias-gratuitas.md).
PAGES_MAX_FILE_BYTES = 25 * 1024 * 1024
PAGES_MAX_FILES = 20_000


@dataclass(frozen=True)
class Paths:
    """Caminhos absolutos do projeto novo."""

    root: Path = PROJECT_ROOT
    data: Path = PROJECT_ROOT / "data"
    public: Path = PROJECT_ROOT / "public"

    @classmethod
    def from_env(cls) -> "Paths":
        root = Path(os.environ.get("IMOVEIS_PROJECT_ROOT", PROJECT_ROOT)).resolve()
        data = Path(os.environ.get("IMOVEIS_DATA_DIR", root / "data")).resolve()
        public = Path(os.environ.get("IMOVEIS_PUBLIC_DIR", root / "public")).resolve()
        return cls(root=root, data=data, public=public)

    @property
    def raw(self) -> Path:
        return self.data / "raw"

    @property
    def config(self) -> Path:
        return self.data / "config"

    @property
    def geo(self) -> Path:
        return self.data / "geo"

    @property
    def seeds(self) -> Path:
        return self.data / "seeds"

    @property
    def history(self) -> Path:
        return self.data / "history"

    @property
    def logs(self) -> Path:
        return self.data / "logs"

    @property
    def public_data(self) -> Path:
        return self.public / "data"

    @property
    def collectors(self) -> Path:
        return self.root / "scripts" / "imoveis_radar" / "collectors"

    def raw_csv(self, source_id: str) -> Path:
        return self.raw / source_id / SOURCE_FILES[source_id]

    def source_dir(self, source_id: str) -> Path:
        return self.raw / source_id

    @property
    def config_file(self) -> Path:
        return self.config / "settings.json"

    @property
    def exclude_ids_file(self) -> Path:
        return self.config / "exclude_ids.txt"

    @property
    def exclude_locations_file(self) -> Path:
        return self.config / "exclude_locations.csv"

    @property
    def market_values_file(self) -> Path:
        return self.config / "market_value.csv"

    @property
    def geocode_cache_file(self) -> Path:
        return self.geo / "geocode_cache.json"

    @property
    def history_file(self) -> Path:
        return self.history / "removidos.json"

    def ensure_dirs(self) -> None:
        for path in (
            self.data,
            self.public,
            self.raw,
            self.config,
            self.geo,
            self.seeds,
            self.history,
            self.logs,
            self.public_data,
        ):
            path.mkdir(parents=True, exist_ok=True)


@dataclass
class RunOptions:
    """Opções de uma execução do atualizador."""

    dry_run: bool = False
    skip_collect: bool = False
    validate_only: bool = False
    force_publish: bool = False
    allow_source_drop: bool = False
    geocode: bool = True
    sources: tuple[str, ...] = SOURCE_ORDER
    min_rows_ratio: float = DEFAULT_MIN_ROWS_RATIO
    chunk_size: int = DEFAULT_CHUNK_SIZE
    min_caixa_bytes: int = DEFAULT_MIN_CAIXA_BYTES
    http_timeout: int = DEFAULT_HTTP_TIMEOUT
    http_retries: int = DEFAULT_HTTP_RETRIES
    collector_timeout: int = DEFAULT_COLLECTOR_TIMEOUT
    collector_attempts: int = DEFAULT_COLLECTOR_ATTEMPTS
    collector_retry_delay: float = DEFAULT_COLLECTOR_RETRY_DELAY
    max_stale_days: int = DEFAULT_MAX_STALE_DAYS
    geocode_max: int = DEFAULT_GEOCODE_MAX
    geocode_interval: float = DEFAULT_GEOCODE_INTERVAL
    history_days: int = DEFAULT_HISTORY_DAYS
    log_file: Path | None = None
    verbose: bool = False
    json_output: bool = False
    extra: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        invalid = [source for source in self.sources if source not in SOURCE_NAMES]
        if invalid:
            raise ValueError(f"Fonte(s) desconhecida(s): {', '.join(invalid)}")
        if self.chunk_size < 100:
            raise ValueError("O tamanho do bloco deve ser >= 100")
        if not 0 < self.min_rows_ratio <= 1:
            raise ValueError("min_rows_ratio deve estar entre 0 e 1")
        if self.collector_attempts < 1:
            raise ValueError("collector_attempts deve ser >= 1")
