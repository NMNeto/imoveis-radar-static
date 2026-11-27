# Coleta local (Raspberry Pi)

O CSV da Caixa fica atrás do **Radware Bot Manager**, que libera IPs
residenciais e bloqueia os runners do GitHub. A solução é dividir o trabalho:

| Onde | O que faz |
| --- | --- |
| **Raspberry Pi** (IP residencial) | baixa `Lista_imoveis_geral.csv` e commita em `data/raw/caixa/` |
| **GitHub Actions** | valida, geocodifica, publica, gera páginas SEO/sitemap e commita `public/` |

O pipeline do Actions continua tentando baixar a Caixa. Se o arquivo que veio
do Pi for mais novo, o guard de `download_caixa()` **não sobrescreve** e apenas
registra `download_ignorado` no `ultima_atualizacao.json`. Se o Pi ficar 3 dias
sem enviar, o `checar_fontes.py` marca `dados desatualizados` e o alerta dispara.

## 1. Requisitos

- Raspberry Pi OS 64-bit (Playwright não tem build para 32-bit).
- ~2 GB livres (Chromium + dependências ≈ 500 MB).
- Python 3.11+ e git.
- Acesso de escrita ao repositório (deploy key ou token).

## 2. Instalação

```bash
git clone git@github.com:NMNeto/imoveis-radar-static.git
cd imoveis-radar-static

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install --with-deps chromium
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
Se aparecer página de CAPTCHA, o caminho é o download manual no navegador
(*Todos* → *Próxima*) e commit do arquivo.

## 5. Agendamento (systemd)

```bash
sudo cp deploy/sistema/imovanta-caixa.service /etc/systemd/system/
sudo cp deploy/sistema/imovanta-caixa.timer   /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now imovanta-caixa.timer
systemctl list-timers imovanta-caixa.timer
```

- Roda às **05:30 BRT** (o Actions roda às 06:00 BRT; a folga evita disputa de push).
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
| `Radware Bot Manager bloqueou o acesso (CAPTCHA)` | IP marcado ou rede corporativa | testar em outra rede; reduzir frequência |
| `download não gerou …` | botão/rótulo mudou na Caixa | abrir a página no navegador e conferir os textos |
| `playwright: Executable doesn't exist` | Chromium não instalado | `.venv/bin/playwright install --with-deps chromium` |
| `Permission denied (publickey)` no push | deploy key sem escrita | marcar *Allow write access* |
| `push falhou` + conflito | Actions commitou ao mesmo tempo | rodar o timer mais cedo ou `git pull --rebase` |

## 7. Desligar

```bash
sudo systemctl disable --now imovanta-caixa.timer
```

O Actions volta a ser o único coletor da Caixa (com o CSV congelado, se o
portal continuar bloqueando) e o alerta de dados desatualizados assume.
