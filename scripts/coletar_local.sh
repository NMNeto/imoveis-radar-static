#!/usr/bin/env bash
# Coleta local (Raspberry Pi) das fontes bloqueadas por IP e envio ao GitHub.
#
# Por que existe: a Caixa fica atrás do Radware Bot Manager (bloqueia runners) e
# o portal do BB limita IPs com rajadas.  O Pi coleta com IP residencial e
# commita só data/raw/<fonte>/; o pipeline do GitHub Actions valida, geocodifica
# e publica.  Se o Pi não enviar, o Actions continua tentando — e o
# checar_fontes.py só alarma se o arquivo commitado também estiver velho.
#
# Uso:
#   scripts/coletar_local.sh
#   scripts/coletar_local.sh --dry-run
#   FONTES="caixa" scripts/coletar_local.sh
#
# Variáveis:
#   FONTES        fontes a coletar (padrão: "caixa bb")
#   REPO_DIR      raiz do repositório (padrão: pai deste script)
#   PYTHON        interpretador (padrão: $REPO_DIR/.venv/bin/python)
#   KUMA_PUSH_URL URL de push do Uptime Kuma (opcional)
#   GIT_PUSH      "0" desliga o push (padrão: 1)
set -euo pipefail

REPO_DIR="${REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PYTHON="${PYTHON:-$REPO_DIR/.venv/bin/python}"
FONTES="${FONTES:-caixa bb}"
DRY_RUN=0
GIT_PUSH="${GIT_PUSH:-1}"

for argumento in "$@"; do
    case "$argumento" in
        --dry-run) DRY_RUN=1 ;;
        -h|--help) sed -n '2,24p' "$0"; exit 0 ;;
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

ARQUIVO_CAIXA="$REPO_DIR/data/raw/caixa/Lista_imoveis_geral.csv"
ARQUIVO_BB="$REPO_DIR/data/raw/bb/imoveis_bb_geral.csv"
ALTERADOS=()
COLETADOS=()
FALHAS=0

coletar_caixa() {
    local destino="$REPO_DIR/data/raw/caixa"
    local geracao
    mkdir -p "$destino"
    log "Caixa: baixando a lista completa…"
    if ! SOURCE_OUTPUT_DIR="$destino" "$PYTHON" scripts/imoveis_radar/collectors/extrair_caixa.py; then
        log "Caixa: download falhou; arquivo atual preservado"
        return 1
    fi
    if [[ ! -s "$ARQUIVO_CAIXA" ]]; then
        log "Caixa: arquivo vazio"
        return 1
    fi
    geracao="$("$PYTHON" - "$ARQUIVO_CAIXA" <<'PY'
import sys
from pathlib import Path

sys.path.insert(0, "scripts")
from imoveis_radar.csv_sources import read_generation_date

print(read_generation_date(Path(sys.argv[1])) or "")
PY
)"
    if [[ -z "$geracao" ]]; then
        log "Caixa: não consegui ler a 'Data de geração'"
        return 1
    fi
    log "Caixa: data de geração $geracao"
    COLETADOS+=("caixa $geracao")
    git status --porcelain -- "$ARQUIVO_CAIXA" | grep -q . && ALTERADOS+=("$ARQUIVO_CAIXA")
    return 0
}

coletar_bb() {
    local destino="$REPO_DIR/data/raw/bb"
    local temporario linhas_novas linhas_atuais
    mkdir -p "$destino"
    temporario="$(mktemp -d)"
    log "BB: baixando catálogo (detalhes reaproveitados)…"
    if ! SOURCE_OUTPUT_DIR="$temporario" SOURCE_DATE_PREFIX="" SOURCE_CSV_ONLY=1 \
        SOURCE_PREVIOUS_CSV="$ARQUIVO_BB" \
        "$PYTHON" scripts/imoveis_radar/collectors/extrair_bb.py; then
        log "BB: coleta falhou; arquivo atual preservado"
        rm -rf "$temporario"
        return 1
    fi
    if [[ ! -s "$temporario/imoveis_bb_geral.csv" ]]; then
        log "BB: CSV não gerado"
        rm -rf "$temporario"
        return 1
    fi
    linhas_novas=$(wc -l < "$temporario/imoveis_bb_geral.csv")
    linhas_atuais=0
    [[ -f "$ARQUIVO_BB" ]] && linhas_atuais=$(wc -l < "$ARQUIVO_BB")
    # Nunca substitui por uma coleta parcial (o CSV é gravado em checkpoints).
    if (( linhas_atuais > 0 && linhas_novas < linhas_atuais * 7 / 10 )); then
        log "BB: coleta suspeita ($linhas_novas linhas contra $linhas_atuais); mantendo a anterior"
        rm -rf "$temporario"
        return 1
    fi
    mv "$temporario/imoveis_bb_geral.csv" "$ARQUIVO_BB"
    rm -rf "$temporario"
    log "BB: $((linhas_novas - 1)) imóveis"
    COLETADOS+=("bb")
    git status --porcelain -- "$ARQUIVO_BB" | grep -q . && ALTERADOS+=("$ARQUIVO_BB")
    return 0
}

for fonte in $FONTES; do
    case "$fonte" in
        caixa|bb) ;;
        *) log "fonte desconhecida: $fonte"; FALHAS=$((FALHAS + 1)); continue ;;
    esac
    if ! "coletar_$fonte"; then
        FALHAS=$((FALHAS + 1))
    fi
done

if [[ ${#COLETADOS[@]} -eq 0 ]]; then
    log "nenhuma fonte coletada"
    pings down "nenhuma-fonte"
    exit 1
fi

log "coletado: ${COLETADOS[*]}"

if [[ ${#ALTERADOS[@]} -eq 0 ]]; then
    log "sem mudanças nos CSVs; nada a enviar"
    pings up "sem-mudancas"
    exit 0
fi

if [[ "$DRY_RUN" = "1" ]]; then
    log "dry-run: commit e push seriam feitos (${ALTERADOS[*]})"
    pings up "dry-run"
    exit 0
fi

git add "${ALTERADOS[@]}"
git commit -m "dados: coleta local (${COLETADOS[*]})"

if [[ "$GIT_PUSH" != "0" ]]; then
    for tentativa in 1 2 3; do
        if git push --quiet; then
            log "enviado ao GitHub"
            break
        fi
        log "push rejeitado; sincronizando e tentando de novo ($tentativa/3)…"
        git pull --rebase --autostash --quiet
        if (( tentativa == 3 )); then
            log "ERRO: não foi possível enviar"
            pings down "push-falhou"
            exit 1
        fi
    done
else
    log "GIT_PUSH=0: commit local feito, sem push"
fi

if (( FALHAS > 0 )); then
    pings up "parcial-${FALHAS}-falha"
else
    pings up "ok"
fi
