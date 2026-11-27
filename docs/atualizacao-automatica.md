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
12. `python scripts/checar_fontes.py` — falha o job se alguma fonte ficou sem
    dados novos (ver seção 3).
13. `python scripts/enviar_alerta_email.py` — roda só em falha (`if: failure()`)
    e envia o e-mail com as fontes problemáticas.

O job tem `timeout-minutes: 120` e `concurrency` para não rodar duas
atualizações ao mesmo tempo.

## 3. Falhas, novas tentativas e alertas

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

### Novas tentativas

Cada coletor Playwright é executado até `--collector-attempts` vezes (padrão
**2**), com `--collector-retry-delay` segundos entre elas (padrão **120**).
O download da Caixa já repetia 3 vezes com backoff exponencial; agora os
demais coletores têm o mesmo comportamento.

```bash
python scripts/atualizar_imoveis.py --collector-attempts 3 --collector-retry-delay 180
```

### CSV velho ("baixou igual ao de ontem")

Um download pode dar 200 e ainda assim devolver o **mesmo arquivo** de dias
atrás — foi o que aconteceu com a Caixa em novembro/2026 (CSV com data de
geração de 19/11 servido por dias). Para isso existe o atraso calculado a
partir de `Data de geração` do próprio CSV:

- `stale_days` e `desatualizado: true` aparecem em
  `public/data/ultima_atualizacao.json` por fonte;
- acima de `--max-stale-days` (padrão **3**) o log avisa e o alerta dispara;
- os dados antigos **continuam publicados** (status segue `ok`): é a melhor
  versão disponível, e marcar a fonte como falha faria o site tratar todos os
  imóveis como removidos.

### Verificação e e-mail

O passo `checar_fontes.py` roda depois do commit e falha o job quando:

| Situação | Como é detectada |
| --- | --- |
| Coleta quebrada | `status: falhou` na fonte |
| CSV parado | `desatualizado: true` ou `stale_days > 3` |
| Publicação parada (opcional) | `--max-age-hours` (padrão 0 = desligado) |

Com o job vermelho, o passo `enviar_alerta_email.py` manda o e-mail com a
tabela de fontes, o erro de cada uma e o link do run. Não configure
`--max-age-hours` sem necessidade: em dias sem mudança nos dados o
`data_atualizacao` é preservado de propósito.

Para silenciar uma fonte conhecida enquanto se investiga:

```bash
python scripts/checar_fontes.py --ignore bb
```

### Caixa: fluxo da tela de download

O CSV direto (`/listaweb/Lista_imoveis_geral.csv`) está atrás do **Radware Bot
Manager** e chegou a devolver o mesmo arquivo por 8 dias. Por isso a Caixa tem
um segundo caminho:

1. `download_caixa()` tenta o CSV direto (3 tentativas com backoff).
2. Se falhar **ou** vier com `desatualizado: true`, o pipeline roda
   `scripts/imoveis_radar/collectors/extrair_caixa.py`, que abre
   `/sistema/download-lista.asp` num Chromium, escolhe **Todos**, clica em
   **Próxima** e captura o download.
3. O arquivo alternativo só substitui o atual se a `Data de geração` for mais
   nova (`_mais_recente`). Caso contrário, mantém o anterior e o alerta aponta
   o atraso.

O fallback é opcional na prática: se o Chromium também for bloqueado, o
pipeline segue com o CSV anterior e o e-mail avisa. Nada é apagado.

### BB: menos requisições por dia

O portal do BB responde `Nenhum Imóvel encontrado` quando recebe muitas
requisições (rate limit temporário) — foi a causa das falhas de 18 a 26/11.
Agora o coletor:

- espera o `POST /catalogo` popular `#contagem` (`Encontramos N imóveis`), em
  vez de dormir 4 s fixos;
- repete a abertura até 6 vezes com esperas de 3/10/30/90/180 s: o portal
  responde `Nenhum Imóvel encontrado` por 1–4 min quando limita o IP
  (medido em 27/11/2026), então esperas curtas no começo e longas depois
  atravessam o bloqueio sem perder tempo;
- reaproveita o detalhe do CSV anterior quando preço e avaliação do cartão não
  mudaram (o portal tem ~1.350 imóveis; antes eram 1.350 requisições de detalhe
  por dia, agora só as novidades);
- baixa detalhes com 2 workers e espera o conteúdo da página mudar ao paginar.

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

### Secrets do alerta por e-mail

| Secret | Exemplo | Obrigatório |
| --- | --- | --- |
| `SMTP_HOST` | `smtp.gmail.com` | sim |
| `SMTP_PORT` | `587` | não (padrão 587) |
| `SMTP_SECURITY` | `starttls` / `ssl` / `none` | não (padrão `starttls`) |
| `SMTP_USER` | `alertas@seudominio.com` | sim |
| `SMTP_PASS` | senha de app / API key | sim |
| `ALERT_EMAIL_FROM` | `alertas@seudominio.com` | não (usa `SMTP_USER`) |
| `ALERT_EMAIL_TO` | `voce@seudominio.com,outro@...` | sim |

Sem `SMTP_HOST`/`ALERT_EMAIL_TO` o job falha normalmente e o script apenas
avisa no log — nenhum e-mail é enviado e nada quebra.

Teste local sem enviar:

```bash
python scripts/checar_fontes.py
python scripts/enviar_alerta_email.py --dry-run
```

### Onde cadastrar

GitHub → **Settings → Secrets and variables → Actions → New repository secret**.
Os nomes precisam ser **exatamente** os da tabela (maiúsculas e underscore).

### Gmail (conta secundária)

1. Ative a **verificação em duas etapas** na conta.
2. `myaccount.google.com` → **Segurança** → **Senhas de app** → criar
   "Imovanta" → copie os **16 caracteres** (sem espaços).
3. Cadastre:

| Secret | Valor |
| --- | --- |
| `SMTP_HOST` | `smtp.gmail.com` |
| `SMTP_PORT` | `587` |
| `SMTP_SECURITY` | `starttls` |
| `SMTP_USER` | a conta secundária (`algo@gmail.com`) |
| `SMTP_PASS` | a senha de app de 16 caracteres |
| `ALERT_EMAIL_FROM` | a mesma conta secundária |
| `ALERT_EMAIL_TO` | para onde o alerta deve ir (pode ser outra conta) |

> O Gmail exige que o `From` seja a conta autenticada. Limite de ~500
> destinatários/dia; o alerta manda 1 e-mail por execução com problema.

### Outros provedores

| Provedor | Host | Porta | Segurança | Senha |
| --- | --- | --- | --- | --- |
| Outlook/Hotmail | `smtp-mail.outlook.com` | `587` | `starttls` | senha de app (se 2FA) |
| Yahoo | `smtp.mail.yahoo.com` | `587` | `starttls` | senha de app |
| Zoho | `smtp.zoho.com` | `587` | `starttls` | senha de app |
| Brevo (300/dia grátis) | `smtp-relay.brevo.com` | `587` | `starttls` | SMTP key do painel |

No Brevo o `ALERT_EMAIL_FROM` precisa ser um remetente verificado. Contas
corporativas da Microsoft podem exigir OAuth e recusar SMTP simples — nesse
caso use Gmail ou Brevo.

### Cadastro pelo terminal (opcional)

```bash
gh secret set SMTP_HOST --body "smtp.gmail.com"
gh secret set SMTP_PORT --body "587"
gh secret set SMTP_SECURITY --body "starttls"
gh secret set SMTP_USER --body "conta@gmail.com"
gh secret set SMTP_PASS          # pede o valor sem mostrar na tela
gh secret set ALERT_EMAIL_FROM --body "conta@gmail.com"
gh secret set ALERT_EMAIL_TO --body "voce@exemplo.com"
gh secret list
```

`SMTP_PASS` é pedido no terminal (não fica no histórico). Nunca coloque a
senha em arquivo do repositório.

### Testar

1. Actions → **Testar alerta por e-mail** → **Run workflow**.
2. O log deve terminar com `Alerta enviado para ...`.

Localmente, sem o Actions:

```bash
SMTP_HOST=smtp.gmail.com SMTP_PORT=587 SMTP_SECURITY=starttls \
SMTP_USER=conta@gmail.com SMTP_PASS='senha de app' \
ALERT_EMAIL_TO=voce@exemplo.com \
python scripts/enviar_alerta_email.py --test
```

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
