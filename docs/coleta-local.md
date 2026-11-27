# Coleta local (Raspberry Pi)

O CSV da Caixa fica atrás do **Radware Bot Manager**, que libera IPs
residenciais e bloqueia os runners do GitHub. A solução é dividir o trabalho:

| Onde | O que faz |
| --- | --- |
| **Raspberry Pi** (IP residencial) | baixa a **Caixa** (`Lista_imoveis_geral.csv`) e o **BB** (`imoveis_bb_geral.csv`) e commita em `data/raw/` |
| **GitHub Actions** | valida, geocodifica, publica, gera páginas SEO/sitemap e commita `public/`; se o Pi não enviou, tenta coletar as duas fontes |

O script roda as duas fontes por padrão. Para rodar só uma:

```bash
FONTES="caixa" scripts/coletar_local.sh
FONTES="bb"    scripts/coletar_local.sh
```

O pipeline do Actions continua tentando baixar as duas fontes. Se o arquivo
que veio do Pi for mais novo, o guard de `download_caixa()` **não sobrescreve** e
apenas registra `download_ignorado` no `ultima_atualizacao.json`.

No BB não existe "Data de geração" no CSV, então a regra é outra: se o coletor
do Actions **falha**, o arquivo do Pi é preservado; se ele **consegue** coletar,
os dados são atuais por definição e podem substituir. Para não alarmar à toa, o
`checar_fontes.py --fresh-hours 30` ignora a falha do Actions quando o CSV foi
commitado pelo Pi nas últimas 30 h (checagem por `git log` do arquivo).

## 1. Requisitos

- Raspberry Pi OS 64-bit (Playwright não tem build para 32-bit).
- ~2 GB livres (Chromium + dependências ≈ 500 MB).
- Python 3.11+ e git.
- `xvfb` — o Radware barra Chromium **headless**; o coletor roda headful num
  display virtual (`sudo apt-get install -y xvfb`).
- Acesso de escrita ao repositório (deploy key ou token).

## 2. Instalação

```bash
git clone git@github.com:NMNeto/imoveis-radar-static.git
cd imoveis-radar-static

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install --with-deps chromium
sudo apt-get install -y xvfb
```

> `--with-deps` instala as bibliotecas de sistema via `apt` e pede `sudo`.

## 3. Acesso ao GitHub

**Opção A — deploy key (recomendado).** Chave SSH só para este repositório,
com permissão de escrita:

```bash
ssh-keygen -t ed25519 -C "imovanta-pi" -f ~/.ssh/imovanta_pi -N ""
cat ~/.ssh/imovanta_pi.pub
# GitHub → repo → Settings → Deploy keys → Add deploy key (Allow write access)
```

Depois aponte o clone para ela em `~/.ssh/config`:

```
Host github.com
  IdentityFile ~/.ssh/imovanta_pi
  IdentitiesOnly yes
```

**Opção B — fine-grained token.** GitHub → Settings → Developer settings →
Fine-grained tokens → *Only select repositories* → este repositório →
*Repository permissions* → **Contents: Read and write**. Configure como
credencial do git:

```bash
git config credential.helper store
printf 'https://TOKEN@github.com\n' > ~/.git-credentials
chmod 600 ~/.git-credentials
```

## 4. Teste manual

```bash
cd ~/imoveis-radar-static
.venv/bin/python scripts/imoveis_radar/collectors/extrair_caixa.py
head -1 data/raw/caixa/Lista_imoveis_geral.csv    # Data de geração:;DD/MM/AAAA

scripts/coletar_local.sh --dry-run                # baixa, mostra a data, não commita
```

Se o `head` mostrar a data de hoje, o IP da sua rede passou pelo Radware.
O script detecta que não há `DISPLAY` e se reexecuta sob `xvfb-run`.

O coletor abre a tela **Lista completa de imóveis**, escolhe `Todos` em
`#cmb_estado` e clica em **Próximo** (`#btn_next1`). A sessão fica num perfil
persistente (`~/.cache/imovanta-chrome`), o que reduz o desafio do Radware
entre execuções.

Se ainda assim aparecer CAPTCHA, o caminho é o download manual no navegador
(*Todos* → *Próximo*) e commit do arquivo.

## 5. Agendamento (systemd)

```bash
sudo cp deploy/sistema/imovanta-caixa.service /etc/systemd/system/
sudo cp deploy/sistema/imovanta-caixa.timer   /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now imovanta-caixa.timer
systemctl list-timers imovanta-caixa.timer
```

- Roda às **05:30 BRT** (o Actions roda às 06:00 BRT; a folga evita disputa de push).
- O BB é baixado num diretório temporário e só substitui o arquivo se tiver
  pelo menos 70% das linhas da coleta anterior (evita publicar coleta parcial
  quando o portal limita no meio).
- `Persistent=true` recupera a execução perdida se faltar luz.
- `journalctl -u imovanta-caixa.service -n 100 --no-pager` mostra o log.

Variáveis opcionais em `/home/pi/.config/imovanta/caixa.env`:

```bash
KUMA_PUSH_URL=https://kuma.seudominio.com/api/push/SEU_TOKEN
```

O script envia `status=up` quando termina bem e `status=down` quando o download
falha — no Uptime Kuma, crie um monitor **Push** com intervalo de 24 h e
*grace* de 6 h.

## 6. Problemas comuns

| Sintoma | Causa provável | Ação |
| --- | --- | --- |
| `Radware Bot Manager bloqueou o acesso (CAPTCHA)` | IP marcado ou execução headless | confirmar `xvfb-run`; testar em outra rede; reduzir frequência |
| `não foi possível abrir o Chromium headful` | execução sem `DISPLAY`/`xvfb` | `sudo apt-get install -y xvfb` |
| `download não gerou …` | botão/rótulo mudou na Caixa | abrir a página no navegador e conferir os textos |
| `playwright: Executable doesn't exist` | Chromium não instalado | `.venv/bin/playwright install --with-deps chromium` |
| `Permission denied (publickey)` no push | deploy key sem escrita | marcar *Allow write access* |
| `push falhou` + conflito | Actions commitou ao mesmo tempo | o script já tenta rebase 3×; conferir `journalctl` |
| `BB: coleta suspeita` | portal limitou no meio | rodar de novo mais tarde; o arquivo anterior é mantido |

## 7. Desligar

```bash
sudo systemctl disable --now imovanta-caixa.timer
```

O Actions volta a ser o único coletor da Caixa (com o CSV congelado, se o
portal continuar bloqueando) e o alerta de dados desatualizados assume.
