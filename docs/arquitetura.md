# Arquitetura do site estático

## 1. Visão geral

```text
┌─────────────────────────────────────────────────────────────────────┐
│ GitHub Actions (atualizar-imoveis.yml)                              │
│  cron diário 09:00 UTC / workflow_dispatch                          │
│                                                                     │
│  pytest ─► coleta (Caixa HTTP + Playwright BB/Santander/Itaú)       │
│          ─► validação por fonte (linhas/colunas/queda suspeita)     │
│          ─► normalização + pontuação + exclusões + geocache         │
│          ─► diff (novos/alterados/removidos) + histórico            │
│          ─► gravação atômica em public/data/                        │
│          ─► commit somente se mudou + push                          │
└─────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Cloudflare Pages                                                    │
│  build command: (nenhum)   output: public/                          │
│                                                                     │
│  /index.html + /static/*  ──► assets estáticos (grátis/ilimitados)  │
│  /data/manifest.json      ──► lista de blocos + versão              │
│  /data/imoveis-<hash>-*.json ─► dados                               │
│  /data/meta.json          ──► facetas e configuração resumida       │
│  /data/config.json        ──► listas para a caixa de configurações  │
│  /data/busca_imoveis.csv  ──► exportação                            │
│  /api/image?url=...       ──► Pages Function (proxy/cache)          │
└─────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Navegador                                                           │
│  fetch(manifest) → fetch(blocos em paralelo) → concatena            │
│  filtros/facetas/ordenação/paginação em JavaScript                  │
│  cartões + mapa Leaflet + popups                                    │
│  overrides locais (localStorage) + exportação de configuração       │
└─────────────────────────────────────────────────────────────────────┘
```

## 2. Por que essa arquitetura

- **Cloudflare Pages** entrega HTML/CSS/JS/JSON por CDN, com HTTPS e previews
  de PR, sem servidor para manter.
- **JSON estático** elimina a necessidade de Flask/Gunicorn e mantém o custo
  em zero. O volume atual (26 mil imóveis, ~27 MB de JSON, 5 blocos) cabe nos
  limites do Pages (25 MiB por arquivo, 20 mil arquivos).
- **Python no GitHub Actions** preserva a lógica de coleta, normalização e
  pontuação já existente, sem rodar Python no navegador.
- **Pages Function** substitui apenas o `/api/image` do Flask, que era
  necessário por bloqueio de hotlink. Não há outros endpoints dinâmicos.
- **Configuração local + exportação** evita introduzir um backend de escrita
  (D1/Workers) só para editar listas. Quem quiser tornar uma alteração global
  exporta o JSON e roda `scripts/importar_config.py`.

## 3. Geração dos dados

O atualizador segue as fases:

1. **Coleta isolada por fonte** — cada coletor escreve em um diretório
   temporário. Só substitui o CSV oficial depois de validado.
2. **Validação de fonte** — arquivo existe, cabeçalho contém UF/Cidade/Preço/
   Link, quantidade acima do mínimo e acima de `min_rows_ratio` da anterior.
   Uma queda brusca é tratada como bloqueio, não como remoção em massa.
3. **Construção do item** — porta fiel de `caixa_data.py`: IDs prefixados
   (`bb:`, `santander:`, `itau:`), valores, desconto, lucro, exclusões.
4. **Geocodificação** — sementes de estados/cidades, cache existente e, para
   novos bairros, Nominatim/Photon com throttle de 1,5 s; limite por execução.
5. **Diff** — assinatura SHA-256 por item (sem timestamps). Itens novos ganham
   `primeira_visao`/`atualizado_em`; itens alterados atualizam
   `atualizado_em`; itens ausentes em fontes que responderam com sucesso vão
   para `data/history/removidos.json`.
6. **Publicação atômica** — blocos com nome versionado por hash, arquivos
   auxiliares e `manifest.json` por último. Uma falha no meio não altera a
   versão que o site está lendo.
7. **Idempotência** — se o hash dos itens não mudou, nada é regravado.

## 4. Formato dos arquivos

### `manifest.json`

```json
{
  "formato": "imoveis-radar-static/1",
  "versao": 1,
  "sha256": "hash-da-versão(itens+meta+config)…",
  "data_sha256": "3365c5ff54fe…",
  "meta_sha256": "…",
  "config_sha256": "…",
  "gerado_em": "2026-11-14T00:11:34",
  "total": 26317,
  "chunks": [
    "imoveis-3365c5ff54fe-000.json",
    "imoveis-3365c5ff54fe-001.json"
  ],
  "fontes": [{"id": "caixa", "nome": "Caixa", "count": 23782}],
  "config": {"settings": {}, "market_values_count": 153,
             "exclude_ids_count": 171, "exclude_locations_count": 141},
  "arquivos": {
    "meta": "meta.json",
    "estatisticas": "estatisticas.json",
    "ultima_atualizacao": "ultima_atualizacao.json",
    "config": "config.json",
    "csv": "busca_imoveis.csv"
  }
}
```

### Blocos de imóveis

Cada `imoveis-<hash>-NNN.json` é uma lista de objetos com os mesmos campos da
API original, mais `primeira_visao` e `atualizado_em`. O tamanho padrão é
6.000 itens por bloco (configurável), mantendo cada arquivo bem abaixo de
25 MiB.

### `meta.json`

Mesmo conteúdo de `/api/meta` (sem status dinâmico): total, UFs, cidades,
bairros, modalidades, fontes, faixa de preço, contagens de configuração e
geocache.

### `estatisticas.json`

Totais, por fonte, excluídos, imagens, coordenadas, precisão geográfica,
preço/desconto/lucro, top UFs, geocodificação e coleta.

### `ultima_atualizacao.json`

Data da última mudança de dados, totais de novos/alterados/removidos, hash e
status das fontes. Só é regravado quando os dados mudam.

### `config.json`

Configuração pública para a caixa de Configurações: `settings`,
`exclude_ids`, `exclude_locations`, `market_values`.

## 5. Frontend

- Carrega `data/manifest.json` e depois os blocos em paralelo.
- Aplica overrides locais e recalcula desconto/lucro.
- Porta `filter_items`, `sort_items` e a lógica de facetas de `caixa_data.py`.
- Usa a mesma paginação progressiva (60 por vez, teto de 5.000 itens).
- Mantém URL compartilhável, typeahead, mapa com clusters, popups, CSV,
  “Ajustar valor” e “Excluir”.
- Imagens de BB/Santander/Itaú passam por `/api/image`; Caixa continua
  hot-linked.
- `config.js` centraliza `imageProxy` e as URLs do Google Form de sugestões
  (`feedbackUrl`/`feedbackEmbedUrl`) sem build step.
- O aviso de primeira visita usa `localStorage` apenas para lembrar que o
  usuário já o leu; não há cookies próprios de análise/publicidade.
- O modal **Sugestões** carrega o Google Form sob demanda (somente ao abrir),
  reduzindo requisições e evitando cookies de terceiros no carregamento
  inicial.

## 6. Isolamento do projeto original

- O projeto novo fica em `/home/nmneto/github/imoveis-radar-static`, irmão do
  original, **fora** da árvore dele.
- Nenhum link simbólico entre os projetos.
- Todas as escritas passam por `safety.ensure_within`, que recusa caminhos
  fora de `data/`/`public/` do projeto novo.
- `assert_isolated` recusa execução se `IMOVEIS_ORIGINAL_DIR` se sobrepuser
  ao projeto novo.
- O script nunca usa o diretório original como `cwd`; os coletores rodam em
  diretórios temporários.
- O Git do projeto novo foi inicializado do zero; o original não é remote.

## 7. Limites e evolução

- 5 blocos de ~6 MB + CSV de ~14 MB + auxiliares = 10 arquivos em `public/`,
  muito abaixo dos 20 mil arquivos e 25 MiB/arquivo do Pages Free.
- Se o dataset crescer, aumente o número de blocos (não o tamanho por bloco).
- Se um dia for necessário editar configuração global com autenticação,
  Cloudflare D1 + Worker ou Turnstile podem ser adicionados sem mudar o
  frontend; hoje isso não é necessário.
