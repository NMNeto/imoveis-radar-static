# Imóveis Radar — site estático

Versão estática do **Imóveis Radar**, publicada na Cloudflare Pages e
atualizada automaticamente por um script Python no GitHub Actions.

O visual, o layout, os filtros, a busca, a ordenação, o mapa e o conteúdo são
equivalentes aos do projeto original. O site original
(`/home/nmneto/github/imoveis-radar`) foi tratado como **somente leitura** e
não foi modificado.

## O que este projeto faz

- Gera JSON estático a partir das quatro fontes já usadas pelo site original:
  **Caixa**, **Banco do Brasil**, **Santander** e **Itaú**.
- Preserva os campos e as fórmulas de desconto/lucro do projeto original.
- Mantém filtros, busca, ordenação, paginação progressiva, mapa Leaflet,
  compartilhamento por URL e exportação CSV.
- Atualiza os dados diariamente no GitHub Actions e publica no Cloudflare
  Pages via integração Git.
- Faz proxy das imagens de BB/Santander/Itaú por uma Pages Function, sem
  armazenar imagens no repositório.
- Mantém localmente (no navegador) ajustes de valor de venda, exclusões e
  premissas, com exportação para aplicar ao repositório.

## Arquitetura em uma tela

```text
GitHub Actions (cron diário / manual)
        │
        ├── baixa CSV da Caixa
        ├── roda coletores Playwright (BB, Santander, Itaú)
        ├── normaliza, valida, deduplica, calcula desconto/lucro
        ├── geocodifica novos bairros (Nominatim/Photon, com cache)
        ├── compara com a versão anterior (novos/alterados/removidos)
        └── grava JSON/CSV em public/data/ e faz commit
                              │
                              ▼
Cloudflare Pages (build: nenhum; output: public/)
        ├── index.html + static/ (HTML/CSS/JS/Leaflet)
        ├── data/manifest.json → blocos de imóveis
        └── functions/api/image.js (proxy de imagens)
                              │
                              ▼
Navegador: carrega os JSON, filtra/ordena no cliente e desenha cartões + mapa
```

O frontend **não executa Python**. O Python roda apenas no GitHub Actions ou
na sua máquina.

## Estrutura

```text
.
├── public/                     # artefato publicado no Pages
│   ├── index.html
│   ├── static/                 # CSS, JS, Leaflet, placeholder
│   ├── data/                   # JSON/CSV gerados (versionados)
│   ├── _headers
│   ├── _routes.json
│   └── robots.txt
├── functions/api/image.js      # Pages Function: proxy de imagens
├── scripts/
│   ├── atualizar_imoveis.py    # entrada do atualizador
│   ├── importar_config.py      # aplica config-local.json ao repositório
│   ├── dev_server.py           # pré-visualização local com /api/image
│   └── imoveis_radar/          # núcleo (coleta, modelo, geo, publicação)
├── data/
│   ├── raw/                    # CSVs das fontes (Caixa/BB/Santander/Itaú)
│   ├── config/                 # settings, exclusões, valores de venda
│   ├── geo/geocode_cache.json
│   ├── seeds/                  # centroides de estados/cidades
│   ├── history/removidos.json
│   └── logs/                   # logs locais (ignorados pelo Git)
├── tests/                      # pytest
├── docs/
├── .github/workflows/
│   ├── atualizar-imoveis.yml   # cron + manual + commit + deploy
│   └── validar.yml             # testes em push/PR
├── requirements.txt
├── requirements-dev.txt
└── pyproject.toml
```

## Pré-requisitos

- Python 3.11+ (recomendado 3.12)
- Para os coletores: Playwright + Chromium (`playwright install chromium`)
- Nenhum Node.js/build step é necessário.

## Rodar localmente

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
pip install pytest            # opcional, para testes

# 1) Gera os dados iniciais a partir dos CSVs já incluídos (sem rede)
python scripts/atualizar_imoveis.py --skip-collect --no-geocode

# 2) Pré-visualiza o site em http://127.0.0.1:8080
python scripts/dev_server.py --port 8080
```

O `dev_server.py` serve `public/` e implementa o mesmo `/api/image` da Pages
Function, para que as imagens de BB/Santander/Itaú apareçam no preview.

## Atualizar os dados

```bash
# Simulação: coleta e compara, mas não grava nada
python scripts/atualizar_imoveis.py --dry-run

# Usa os CSVs existentes em data/raw/ (sem acessar os portais)
python scripts/atualizar_imoveis.py --skip-collect

# Atualização completa (Caixa + coletores + geocodificação)
python scripts/atualizar_imoveis.py

# Somente validar os JSONs publicados
python scripts/atualizar_imoveis.py --validate-only
```

O script é idempotente: se a origem não mudou, os arquivos de dados não são
regravados. Se uma fonte falhar, a versão anterior dela é preservada e o
processo registra o erro; nenhuma fonte é considerada removida por falha.

## Testes

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

Cobrem normalização, leitura dos quatro CSVs, pontuação, exclusões, geocache,
diff/histórico, publicação atômica, idempotência, importação de configuração e
o fluxo completo do CLI.

## Configuração

Os arquivos canônicos ficam em `data/config/`:

- `settings.json` — taxa de venda, custos fixos, fator de leilão;
- `exclude_ids.txt` — um ID por linha;
- `exclude_locations.csv` — `Cidade,Bairro,Endereço` (`all` é curinga);
- `market_value.csv` — `ID,Valor de Venda Aproximado`.

No site, a caixa **Configurações** edita esses valores **neste navegador**
(localStorage). O botão **Exportar** baixa `config-local.json`; para aplicar
ao repositório, rode:

```bash
python scripts/importar_config.py ~/Downloads/config-local.json
```

Depois faça commit de `data/config/`. A próxima atualização já usará a nova
configuração para todos os visitantes.

## Deploy na Cloudflare Pages

Configuração resumida (detalhes em [docs/cloudflare-pages.md](docs/cloudflare-pages.md)):

| Item | Valor |
| --- | --- |
| Repositório | este repositório |
| Branch de produção | `main` |
| Framework preset | None / Static HTML |
| Build command | *(vazio)* |
| Build output directory | `public` |
| Functions directory | `functions` (padrão) |
| Variáveis obrigatórias | nenhuma |

A Pages Function `/api/image` é publicada junto com o site e usa o cache de
borda. O Cloudflare Pages faz um novo deploy a cada push; opcionalmente,
configure o secret `CLOUDFLARE_DEPLOY_HOOK_URL` para disparar um deploy hook
ao final do workflow.

## Atualização automática

O workflow `.github/workflows/atualizar-imoveis.yml` roda:

- diariamente às **09:00 UTC** (= 06:00 em America/Sao_Paulo);
- manualmente via **Actions → Atualizar imóveis → Run workflow**;
- testes, atualização, validação, commit somente se houver mudança e push;
- deploy hook opcional.

Para outra frequência, edite o `cron`. O GitHub Actions sempre usa UTC.

## Documentação

- [Checklist de entrega](docs/entrega.md)
- [Relatório técnico do site original](docs/relatorio-tecnico-original.md)
- [Arquitetura e decisões](docs/arquitetura.md)
- [Dados, campos e atualização](docs/dados-e-atualizacao.md)
- [Atualização automática](docs/atualizacao-automatica.md)
- [Cloudflare Pages](docs/cloudflare-pages.md)
- [Comparação visual](docs/comparacao-visual.md)
- [Validação dos dados](docs/validacao-dados.md)
- [Integridade do projeto original](docs/integridade-original.md)
- [Franquias gratuitas](docs/franquias-gratuitas.md)
- [Avisos de terceiros](THIRD_PARTY_NOTICES.md)

## Decisões e limitações

- **Sem backend de aplicação.** O Pages serve arquivos estáticos; a única
  função é o proxy de imagens.
- **“Atualizar agora”** abre o workflow no GitHub Actions em vez de disparar
  uma atualização diretamente, para não expor um token no navegador.
- **Geocodificação** roda no Python, com cache e limite de requisições;
  os botões de geocodificação do site apenas orientam/abrem o workflow.
- **Configurações** no navegador são locais; use Exportar + `importar_config.py`
  para torná-las globais.
- **Imagens de terceiros** podem ser bloqueadas pela origem; nesse caso o site
  usa o placeholder local.
- **Dados** pertencem às fontes originais; o projeto não é afiliado à Caixa,
  BB, Santander ou Itaú.
