# Atualização automática

## 1. Workflow

Arquivo: `.github/workflows/atualizar-imoveis.yml`

Gatilhos:

- **Agendado:** `cron: "0 9 * * *"` — 09:00 UTC = **06:00 America/Sao_Paulo**.
- **Manual:** Actions → **Atualizar imóveis** → **Run workflow**.
  - `dry_run`: simula sem gravar/commitar.
  - `skip_collect`: usa os CSVs existentes (sem portais).
  - `max_imoveis`: limita a coleta para teste.

O GitHub Actions **sempre interpreta cron em UTC**. Para mudar a frequência,
edite o `cron`; exemplos:

```yaml
- cron: "0 9 * * *"       # 1x/dia, 06:00 BRT
- cron: "0 9,15,21 * * *" # 3x/dia, 06:00/12:00/18:00 BRT
- cron: "0 9 * * 1-5"     # dias úteis, 06:00 BRT
```

## 2. Etapas do job

1. Checkout (`fetch-depth: 0`).
2. Python 3.12 + cache de pip.
3. `pip install -r requirements-dev.txt`.
4. Cache do Chromium do Playwright por `requirements.txt`.
5. `playwright install --with-deps chromium`.
6. `python -m pytest -q` — se falhar, nada é coletado/publicado.
7. `python scripts/atualizar_imoveis.py --json`.
8. `python scripts/atualizar_imoveis.py --validate-only`.
9. `git add data public`; se não houver diff, não commita.
10. Commit `dados: atualização automática ...` e `git push`.
11. Deploy hook opcional.

O job tem `timeout-minutes: 120` e `concurrency` para não rodar duas
atualizações ao mesmo tempo.

## 3. Falhas

- **Coleta de uma fonte falha:** o script mantém a versão anterior daquela
  fonte, registra o erro e continua. O workflow só falha se o script retornar
  código ≠ 0.
- **Nenhuma fonte e sem dados anteriores:** código 2, workflow falha, nada é
  commitado.
- **Validação do JSON falha:** código 3, nada é commitado.
- **Testes falham:** job para antes da coleta.
- **Push rejeitado:** o job falha; nenhum dado inválido é publicado.

Nunca há commit de dados incompletos: a publicação só ocorre depois de
validação de campos, tipos, IDs únicos, URLs e limites de tamanho.

## 4. Commit e deploy

O commit inclui:

- `public/data/*` (JSON/CSV publicados);
- `data/raw/*` (CSVs usados como fallback);
- `data/geo/geocode_cache.json` (se mudou);
- `data/history/removidos.json` (se mudou).

Não inclui `data/logs/` nem `.venv/` (`.gitignore`).

A integração Git do Cloudflare Pages dispara um novo deploy a cada push na
branch `main`. O passo de deploy hook é **opcional**; configure o secret
`CLOUDFLARE_DEPLOY_HOOK_URL` se quiser disparar explicitamente (por exemplo,
quando o build do Pages não estiver conectado ao Git).

## 5. Permissões e secrets

```yaml
permissions:
  contents: write
```

- `GITHUB_TOKEN`: automático, usado no push.
- `CLOUDFLARE_DEPLOY_HOOK_URL`: opcional.
- Nenhuma credencial de Caixa/BB/Santander/Itaú é usada; a coleta é pública.
- Nenhum token é colocado no código ou no frontend.

## 6. Custo e limites

- GitHub Actions: repositório público usa runners gratuitos; repositório
  privado consome a cota do plano (2.000 min/mês no Free). O job típico leva
  poucos minutos; com Chromium e geocodificação, fica bem abaixo de 1 h.
- Cloudflare Pages: 500 builds/mês no Free; um push por dia ≈ 30 builds/mês.
- Pages Functions: 100.000 requisições/dia no Free, compartilhadas com
  Workers. O proxy de imagem só é chamado quando um cartão carrega imagem de
  BB/Santander/Itaú.

## 7. Execução local equivalente

```bash
# O que o workflow faz, sem commitar
python -m pytest -q
python scripts/atualizar_imoveis.py --json
python scripts/atualizar_imoveis.py --validate-only
```

## 8. Frequência e horário

O horário de 06:00 BRT foi escolhido para pegar as atualizações noturnas dos
portais antes do uso diurno. Se quiser 3x/dia como o original, use
`"0 9,15,21 * * *"` (06:00, 12:00 e 18:00 BRT). Evite horários de pico dos
portais e respeite os limites de uso.
