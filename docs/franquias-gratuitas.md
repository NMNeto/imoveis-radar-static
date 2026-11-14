# Estimativa de consumo das franquias gratuitas

Consultado em **14/11/2026** na documentação oficial da Cloudflare e do
GitHub. Limites podem mudar; confira os links ao final antes de assumir
compromissos.

## 1. Cloudflare Pages (Free)

| Recurso | Limite Free | Uso estimado neste projeto |
| --- | --- | --- |
| Builds | 500/mês, 1 concorrente, timeout 20 min | ~30/mês (1 commit de dados/dia) + pushes de código |
| Arquivos por site | 20.000 | 10 arquivos em `public/` |
| Tamanho por arquivo | 25 MiB | maior: CSV ~14,3 MB; blocos ~6,2 MB |
| Projetos | 100 | 1 |
| Requests/bandwidth estáticos | gratuitos e ilimitados (uso justo) | site pessoal |
| Previews | ilimitados | habilitados por PR |
| Header rules | 100 | 2 regras |
| Redirects | 2.000 + 100 | 0 |

**Folga:** muito confortável. O único cuidado é manter cada bloco JSON abaixo
de 25 MiB; o script já divide em blocos de 6.000 itens.

## 2. Cloudflare Workers / Pages Functions (Free)

Requests a Pages Functions contam na cota de Workers Free.

| Recurso | Limite Free | Uso estimado |
| --- | --- | --- |
| Requisições | 100.000/dia (reset 00:00 UTC) | ver abaixo |
| CPU por requisição | 10 ms | proxy de imagem (I/O + cópia de buffer) |
| Memória | 128 MB/isolate | imagens até 20 MB |
| Subrequests | 50/requisição | 1 fetch por imagem |
| Workers por conta | 100 | 1 Function (`/api/image`) |

Estimativa de requisições:

- Apenas imagens de **BB/Santander/Itaú** passam pela Function (2.534 itens
  com imagem não-Caixa no dataset atual). Imagens da Caixa são hot-linked e
  não contam.
- Uma visita típica vê 60 cartões; talvez 10–20 sejam de fontes não-Caixa.
- 1.000 visitas/dia × 15 imagens ≈ **15.000 req/dia** (15% da cota).
- 5.000 visitas/dia × 15 ≈ **75.000 req/dia** (75% da cota).
- Acima disso, o cache de borda reduz o tráfego para a origem, mas **cada
  requisição ao Worker ainda conta**. Para tráfego muito alto, considere
  servir imagens do R2 ou otimizar o número de imagens por página.

**Atenção ao CPU de 10 ms:** o proxy lê a imagem em `ArrayBuffer` e devolve.
Isso é predominantemente I/O, mas imagens muito grandes podem se aproximar do
limite. Monitore `Exceeded CPU Time Limits` no dashboard. Se ocorrer, reduza o
tamanho máximo, faça streaming ou migre as imagens para R2 (ver abaixo).

## 3. Cloudflare D1 (Free) — não usado

| Recurso | Limite Free |
| --- | --- |
| Bancos | 10 |
| Armazenamento | 5 GB total |
| Linhas lidas | 5 milhões/dia |
| Linhas escritas | 100.000/dia |
| Tamanho máximo do banco | 500 MB |
| Time Travel | 7 dias |

O projeto **não usa D1**. Não há necessidade de banco relacional para 26 mil
itens servidos como JSON. Se um dia houver autenticação/edição global, D1 pode
ser adicionado sem mudar o frontend.

## 4. Cloudflare KV (Free) — não usado

| Recurso | Limite Free |
| --- | --- |
| Leituras | 100.000/dia |
| Escritas em chaves diferentes | 1.000/dia |
| Armazenamento | 1 GB |
| Valor por chave | 25 MiB |

Não é necessário: o cache de geocodificação fica no repositório e o cache de
imagens usa o Cache API da Function.

## 5. Cloudflare R2 (Free) — não usado

| Recurso | Limite Free |
| --- | --- |
| Armazenamento | 10 GB-mês |
| Class A (escritas) | 1 milhão/mês |
| Class B (leituras) | 10 milhões/mês |
| Egress | grátis |

Não é necessário no estado atual. Seria a opção natural se você quisesse
guardar as imagens de BB/Santander/Itaú no seu próprio storage e parar de
depender dos CDNs dos portais. Isso exigiria um passo de download no Python e
um bucket público — **não foi introduzido** para não criar serviço extra.

## 6. Cloudflare Turnstile (Free) — não usado

| Recurso | Limite Free |
| --- | --- |
| Widgets | 20 |
| Hostnames por widget | 10 |
| Desafios | ilimitados |
| Analytics | 7 dias |

Não há formulário público de escrita no site estático, então Turnstile não é
necessário. Se você adicionar um formulário de contato ou um gatilho de
atualização aberto ao público, Turnstile é a proteção recomendada.

## 7. GitHub Actions

| Repositório | Custo |
| --- | --- |
| Público | runners padrão gratuitos |
| Privado (Free) | 2.000 min/mês |

Estimativa do job:

- checkout + pip + cache: ~1 min;
- `playwright install --with-deps chromium`: ~1–3 min (com cache, menos);
- testes: ~10 s;
- coleta Caixa: ~10 s;
- coletores BB/Santander/Itaú: ~5–25 min (depende dos portais);
- geocodificação de até 200 locais: ~5 min;
- validação/commit/push: ~10 s.

Total típico: **10–35 min/dia** → **300–1.050 min/mês**. Em repositório
público, sem custo. Em privado, cabe nos 2.000 min/mês, mas monitore se os
coletores demorarem. Para reduzir, use `IMOVEIS_GEOCODE_MAX=0` em alguns dias
ou rode 3x/semana.

## 8. Resumo

| Serviço | Necessário? | Uso atual | Risco de cobrança |
| --- | --- | --- | --- |
| Pages | Sim | 10 arquivos, ~30 builds/mês | nenhum no Free |
| Pages Functions | Sim (imagens) | ~15k req/dia em 1k visitas | nenhum até 100k/dia |
| GitHub Actions | Sim | 10–35 min/dia | nenhum em repo público |
| D1 | Não | 0 | — |
| KV | Não | 0 | — |
| R2 | Não | 0 | — |
| Turnstile | Não | 0 | — |

Nenhum serviço pago foi introduzido. Se o tráfego ou o tempo de CPU do proxy
crescerem, a evolução natural é mover as imagens não-Caixa para R2 (10 GB
grátis) ou reduzir a quantidade/tamanho das imagens — não ativar plano pago
sem autorização.

## 9. Fontes oficiais

- Pages limits: <https://developers.cloudflare.com/pages/platform/limits/>
- Pages Functions pricing: <https://developers.cloudflare.com/pages/functions/pricing/>
- Workers limits: <https://developers.cloudflare.com/workers/platform/limits/>
- D1 limits: <https://developers.cloudflare.com/d1/platform/limits/>
- D1 pricing: <https://developers.cloudflare.com/d1/platform/pricing/>
- KV limits: <https://developers.cloudflare.com/kv/platform/limits/>
- R2 pricing: <https://developers.cloudflare.com/r2/pricing/>
- Turnstile plans: <https://developers.cloudflare.com/turnstile/plans/>
- GitHub Actions billing: <https://docs.github.com/en/billing/managing-billing-for-github-actions>
