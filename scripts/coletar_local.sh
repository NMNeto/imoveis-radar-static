#!/usr/bin/env bash
# Coleta local (Raspberry Pi) da lista da Caixa e envio ao GitHub.
#
# Por que existe: o CSV da Caixa fica atrás do Radware Bot Manager, que libera
# IPs residenciais e bloqueia os runners do GitHub.  O Pi baixa o arquivo e
# commita apenas ``data/raw/caixa/Lista_imoveis_geral.csv``; o pipeline do
# GitHub Actions continua validando, geocodificando e publicando.
#
# Uso:
#   scripts/coletar_local.sh
#   scripts/coletar_local.sh --dry-run
#
# Variáveis:
#   REPO_DIR      raiz do repositório (padrão: pai deste script)
#   PYTHON        interpretador (padrão: $REPO_DIR/.venv/bin/python)
#   KUMA_PUSH_URL URL de push do Uptime Kuma (opcional)
#   GIT_PUSH      "0" desliga o push (padrão: 1)
set -euo pipefail

REPO_DIR="${REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PYTHON="${PYTHON:-$REPO_DIR/.venv/bin/python}"
DESTINO="$REPO_DIR/data/raw/caixa"
ARQUIVO="$DESTINO/Lista_imoveis_geral.csv"
DRY_RUN=0
GIT_PUSH="${GIT_PUSH:-1}"

for argumento in "$@"; do
    case "$argumento" in
        --dry-run) DRY_RUN=1 ;;
        -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
        *) echo "argumento desconhecido: $argumento" >&2; exit 2 ;;
    esac
done

log() { printf '%s %s\n' "$(date '+%F %T')" "$*"; }

# O Radware da Caixa barra Chromium headless; o coletor precisa de um display.
# Sem DISPLAY, reexecuta sob Xvfb automaticamente (funciona no systemd e no SSH).
if [[ -z "${DISPLAY:-}" && -z "${IMOVANTA_XVFB:-}" ]] && command -v xvfb-run >/dev/null 2>&1; then
    export IMOVANTA_XVFB=1
    exec xvfb-run -a "$0" "$@"
fi

pings() {
    local status="$1" msg="$2"
    [[ -n "${KUMA_PUSH_URL:-}" ]] || return 0
    curl -fsS -m 10 --get \
        --data-urlencode "status=$status" \
        --data-urlencode "msg=$msg" \
        "$KUMA_PUSH_URL" >/dev/null 2>&1 || log "aviso: ping do Uptime Kuma falhou"
}

cd "$REPO_DIR"

if [[ ! -x "$PYTHON" ]]; then
    log "ERRO: $PYTHON não existe (rode: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt)"
    exit 1
fi

log "atualizando o repositório…"
git pull --rebase --autostash --quiet || log "aviso: git pull falhou; seguindo com a versão local"

mkdir -p "$DESTINO"

log "baixando a lista da Caixa…"
if ! SOURCE_OUTPUT_DIR="$DESTINO" "$PYTHON" scripts/imoveis_radar/collectors/extrair_caixa.py; then
    log "ERRO: download da Caixa falhou; mantendo o arquivo atual"
    pings down "download-falhou"
    exit 1
fi

if [[ ! -s "$ARQUIVO" ]]; then
    log "ERRO: $ARQUIVO vazio"
    pings down "arquivo-vazio"
    exit 1
fi

GERACAO="$("$PYTHON" - "$ARQUIVO" <<'PY'
import sys
from pathlib import Path

sys.path.insert(0, "scripts")
from imoveis_radar.csv_sources import read_generation_date

print(read_generation_date(Path(sys.argv[1])) or "")
PY
)"

if [[ -z "$GERACAO" ]]; then
    log "ERRO: não consegui ler a 'Data de geração' do CSV"
    pings down "csv-sem-data"
    exit 1
fi
log "data de geração: $GERACAO"

if ! git status --porcelain -- "$ARQUIVO" | grep -q .; then
    log "sem mudanças no CSV; nada a enviar"
    pings up "sem-mudancas"
    exit 0
fi

if [[ "$DRY_RUN" = "1" ]]; then
    log "dry-run: commit e push seriam feitos para $GERACAO"
    pings up "dry-run"
    exit 0
fi

git add "$ARQUIVO"
git commit -m "dados: lista da Caixa $GERACAO (coleta local)"

if [[ "$GIT_PUSH" != "0" ]]; then
    if ! git push --quiet; then
        log "push falhou; tentando rebase…"
        git pull --rebase --autostash
        git push --quiet
    fi
    log "enviado ao GitHub: $GERACAO"
else
    log "GIT_PUSH=0: commit local feito, sem push"
fi

pings up "ok-$GERACAO"
