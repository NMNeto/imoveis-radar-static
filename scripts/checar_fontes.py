#!/usr/bin/env python3
"""Aponta fontes sem dados novos e falha o job para disparar o alerta.

Lê ``public/data/ultima_atualizacao.json`` e sinaliza:

* fonte com ``status: falhou`` (coleta quebrada, publicando dados antigos);
* CSV desatualizado (``desatualizado: true`` ou ``stale_days`` acima do limite);
* execução inteira parada (``data_atualizacao`` mais antiga que o limite).

Uso:
    python scripts/checar_fontes.py
    python scripts/checar_fontes.py --max-age-hours 30 --max-stale-days 3
    python scripts/checar_fontes.py --ignore bb --json

Sai com código 1 quando encontra problema, para o GitHub Actions marcar o job
como falho e enviar o e-mail de alerta.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))

from imoveis_radar.config import PROJECT_ROOT, SOURCE_FILES  # noqa: E402
from imoveis_radar.csv_sources import stale_days  # noqa: E402

SUMMARY_PATH = PROJECT_ROOT / "public" / "data" / "ultima_atualizacao.json"


@dataclass
class Problema:
    fonte: str
    motivo: str
    detalhe: str = ""


def horas_desde_commit(source_id: str, root: Path = PROJECT_ROOT) -> float | None:
    """Horas desde o último commit do CSV da fonte (coleta local do Pi).

    Devolve ``None`` quando o arquivo nunca foi commitado ou o git não está
    disponível (por exemplo, rodando fora do repositório).
    """
    caminho = Path("data") / "raw" / source_id / SOURCE_FILES.get(source_id, "")
    try:
        resultado = subprocess.run(
            ["git", "log", "-1", "--format=%ct", "--", str(caminho)],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=15,
        )
        carimbo = int((resultado.stdout or "").strip() or 0)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    if not carimbo:
        return None
    return max(0.0, (time.time() - carimbo) / 3600)


def parse_datetime(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(
            tzinfo=None
        )
    except ValueError:
        return None


def check_summary(
    summary: dict,
    *,
    now: datetime | None = None,
    max_age_hours: float = 0,
    max_stale_days: int = 3,
    ignore: tuple[str, ...] = (),
    fresh_source: Callable[[str], float | None] | None = None,
    fresh_hours: float = 30,
) -> list[Problema]:
    """Devolve a lista de problemas encontrados no resumo da execução."""
    now = now or datetime.now()
    problemas: list[Problema] = []

    atualizacao = parse_datetime(summary.get("data_atualizacao"))
    if max_age_hours <= 0:
        pass
    elif atualizacao is None:
        problemas.append(
            Problema("atualização", "sem data de atualização", "data_atualizacao ausente")
        )
    else:
        horas = (now - atualizacao).total_seconds() / 3600
        if horas > max_age_hours:
            problemas.append(
                Problema(
                    "atualização",
                    "atualização parada",
                    f"última publicação há {horas:.1f}h (limite {max_age_hours:g}h)",
                )
            )

    for source_id, fonte in (summary.get("fontes") or {}).items():
        if source_id in ignore:
            continue
        status = (fonte or {}).get("status")
        if status in ("falhou", "erro"):
            # O Actions pode falhar e o Pi ter enviado o CSV horas antes:
            # nesse caso os dados estão frescos e não há o que alarmar.
            if fresh_source and fresh_hours > 0:
                horas = fresh_source(source_id)
                if horas is not None and horas <= fresh_hours:
                    continue
            problemas.append(
                Problema(
                    source_id,
                    "coleta falhou",
                    (fonte.get("last_error") or "sem detalhe").splitlines()[0][:160],
                )
            )
            continue

        dias = fonte.get("stale_days")
        if dias is None:
            dias = stale_days(fonte.get("generation_date"))
        if fonte.get("desatualizado") or (dias is not None and dias > max_stale_days):
            problemas.append(
                Problema(
                    source_id,
                    "dados desatualizados",
                    f"CSV com {dias} dia(s) (limite {max_stale_days})"
                    if dias is not None
                    else "CSV sem data de geração",
                )
            )
    return problemas


def describe(summary: dict, problemas: list[Problema], max_stale_days: int) -> str:
    linhas = []
    for source_id, fonte in (summary.get("fontes") or {}).items():
        dias = fonte.get("stale_days")
        if dias is None:
            dias = stale_days(fonte.get("generation_date"))
        atraso = f", CSV com {dias}d" if dias is not None else ""
        linhas.append(
            f"  {source_id:10} {str(fonte.get('status')):8} "
            f"{fonte.get('rows', 0):>6} linha(s){atraso}"
        )
    if problemas:
        linhas.append("")
        for problema in problemas:
            linhas.append(
                f"[FALHA] {problema.fonte}: {problema.motivo}"
                + (f" — {problema.detalhe}" if problema.detalhe else "")
            )
    else:
        linhas.append("")
        linhas.append(f"[OK   ] todas as fontes com dados dentro de {max_stale_days} dia(s)")
    return "\n".join(linhas)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, default=SUMMARY_PATH)
    parser.add_argument(
        "--max-age-hours",
        type=float,
        default=0,
        help="horas máximas desde a última publicação (0 = não verifica)",
    )
    parser.add_argument(
        "--max-stale-days",
        type=int,
        default=3,
        help="dias máximos de atraso aceitos no CSV de uma fonte (padrão: 3)",
    )
    parser.add_argument(
        "--fresh-hours",
        type=float,
        default=30,
        help="horas em que um CSV commitado pelo Pi conta como fresco (0 = desliga)",
    )
    parser.add_argument(
        "--ignore",
        action="append",
        default=[],
        help="fonte a ignorar (pode repetir)",
    )
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        summary = json.loads(args.summary.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"Resumo indisponível ({args.summary}): {exc}", file=sys.stderr)
        return 2

    problemas = check_summary(
        summary,
        max_age_hours=args.max_age_hours,
        max_stale_days=args.max_stale_days,
        ignore=tuple(args.ignore),
        fresh_source=horas_desde_commit if args.fresh_hours > 0 else None,
        fresh_hours=args.fresh_hours,
    )
    if args.json:
        print(
            json.dumps(
                {
                    "ok": not problemas,
                    "problemas": [asdict(problema) for problema in problemas],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(describe(summary, problemas, args.max_stale_days))
    return 0 if not problemas else 1


if __name__ == "__main__":
    raise SystemExit(main())
