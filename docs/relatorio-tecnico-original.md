# Relatório técnico do site original

Análise realizada em modo somente leitura em
`/home/nmneto/github/imoveis-radar` (HEAD `67490ef`, branch `main`).
Nenhum arquivo, banco, configuração, dependência ou histórico Git foi alterado.

## 1. Visão geral

O **Imóveis Radar** é uma aplicação Flask monolítica que agrega imóveis com
desconto de quatro fontes:

| Fonte | Arquivo bruto | Coleta |
| --- | --- | --- |
| Caixa | `web/data/Lista_imoveis_geral.csv` | download HTTPS do CSV oficial |
| Banco do Brasil | `web/data/bb/imoveis_bb_geral.csv` | Playwright + HTTP nos detalhes |
| Santander | `web/data/santander/santander_imoveis_geral.csv` | Playwright + API interna do portal |
| Itaú | `web/data/itau/itau_imoveis_geral.csv` | Playwright (SPA Angular) |

O dataset é mantido em arquivos CSV/JSON, sem banco de dados. O Flask carrega
tudo em memória e serve uma UI vanilla JS com Leaflet.

## 2. Tecnologias

- **Backend:** Python 3.12, Flask 3, Gunicorn, requests.
- **Coletores:** Playwright/Chromium, BeautifulSoup, pandas/openpyxl (etapas de
  filtragem/Excel do coletor original), threading.
- **Frontend:** HTML, CSS e JavaScript puro; Leaflet + Leaflet.markercluster
  vendorizados; tiles do OpenStreetMap; nenhum build step.
- **Geocodificação:** Nominatim com fallback Photon; cache JSON; sementes de
  centroides de estados/cidades (`estados.csv`, `municipios.csv`).
- **Infra:** Docker/Docker Compose; volume `web/data`; porta 9000 no host,
  8000 no contêiner; agendador em thread.

## 3. Páginas e rotas

| Rota | Método | Função |
| --- | --- | --- |
| `/` | GET | UI estática (`web/static/index.html`) |
| `/healthz` | GET | Saúde do processo/dataset |
| `/api/meta` | GET | Contagens, UFs, cidades, bairros, modalidades, status de update/geocode |
| `/api/properties` | GET | Lista filtrada, ordenada e paginada (limite padrão 5.000) |
| `/api/facets` | GET | Opções de UF/cidade/bairro/modalidade com interseção de filtros |
| `/api/config` | GET/POST | Lê/substitui exclusões, valores de venda e premissas |
| `/api/market-value` | POST | Define/remove um valor de venda manual |
| `/api/update` | POST | Dispara atualização em thread |
| `/api/update/status` | GET | Status da atualização |
| `/api/csv` | GET | CSV combinado das quatro fontes |
| `/api/image` | GET | Proxy/cache de imagens BB/Santander/Itaú com allowlist |
| `/api/geocode` | POST | Geocodifica escopo filtrado ou tudo |
| `/api/geocode/status` | GET | Status do job de geocodificação |
| `/api/geocode/cancel` | POST | Cancela o job |
| `/api/reload` | POST | Recarrega o dataset do disco |

Não existe página de detalhe própria: cada cartão aponta para a URL da oferta
na fonte (`Link de acesso`).

## 4. Componentes

- `web/app.py` — Flask, estado em memória, agendador, jobs, proxy de imagem,
  exportação CSV e endpoints de configuração/geocode.
- `web/caixa_data.py` — adaptador multi-fonte, normalização, pontuação,
  exclusões, geocache, filtros e ordenação.
- `web/updater.py` — download e normalização do CSV da Caixa; status atômico.
- `web/collectors/` — coletores independentes de BB, Santander e Itaú; runner
  com timeout, logs e preservação da versão anterior.
- `web/geocode.py`, `web/geocode_client.py` — CLI e cliente Nominatim/Photon.
- `web/static/` — HTML, CSS, JS, placeholder e Leaflet vendorizado.

## 5. CSS, JavaScript e recursos visuais

- `style.css`: tema claro, variáveis `--bg`, `--panel`, `--accent` etc.,
  layout em grid (lista + mapa), cartões com imagem 4:3, badges, combos
  typeahead, dialog de configurações, responsividade em 900 px e 600 px.
- `app.js`: estado local, combos, filtros, facetas, mapa com clusters,
  popups, paginação “Carregar mais” (60 por vez), compartilhamento por URL,
  ajuste de valor, exclusão, configurações, update/geocode.
- Sem fontes externas: `system-ui, -apple-system, "Segoe UI", Roboto, ...`.
- Imagens: Caixa hot-linked em
  `https://venda-imoveis.caixa.gov.br/fotos/F{id:013d}21.jpg`; BB/Santander/Itaú
  passam por `/api/image` por bloqueio de hotlink; placeholder local
  `static/placeholder.svg`.
- Mapas: tiles `https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png`.

## 6. Dados e modelo

### Campos do item servido pela API

`id`, `id_fonte`, `fonte`, `fonte_nome`, `uf`, `cidade`, `bairro`, `endereco`,
`preco`, `preco_label`, `valor_avaliacao`, `valor_ajustado`, `ajustado`,
`sem_avaliacao`, `sem_preco`, `desconto`, `lucro`, `lucro_pct`,
`financiamento`, `descricao`, `modalidade`, `link`, `imagem`, `arquivo`,
`excluido`, `motivo_exclusao`, `lat`, `lng`, `geo_precisao`, `geo_fonte`.

### Fórmulas

```text
desconto   = (valor_ajustado - preco) / valor_ajustado * 100
fator      = 1 se modalidade ∈ {VENDA ONLINE, VENDA DIRETA ONLINE}
             senão fator_preco (padrão 1.05)
custo_fixo = custo_fixo (modo fixo)
             ou valor_ajustado * custo_fixo / 100 (modo percentual)
lucro      = (valor_ajustado - valor_ajustado * taxa_venda - custo_fixo)
             - preco * fator
lucro_pct  = lucro / valor_ajustado * 100
```

Padrões: `taxa_venda=0.06`, `custo_fixo=40000`, `custo_fixo_modo=fixo`,
`fator_preco=1.05`. Imóveis sem avaliação mantêm `desconto/lucro/lucro_pct`
nulos e só são excluídos por filtros de desconto/lucro quando o mínimo é > 0.

### Configuração editável

`web/data/settings.json`, `exclude_ids.txt`, `exclude_locations.csv`,
`market_value.csv`; editáveis pela UI e persistidos no volume Docker.

### Geocache

`web/data/geocode_cache.json` com chaves `UF|CIDADE|BAIRRO`, pontos
(`bairro`/`cidade`/`estado`) e misses com TTL de 30 dias. Cidades/estados vêm
de `municipios.csv`/`estados.csv`; bairros vêm de Nominatim/Photon. O mapa usa
jitter determinístico por ID para separar imóveis no mesmo local.

## 7. Origem e atualização das listas

1. O agendador roda às **06:00, 12:00 e 18:00 America/Sao_Paulo**, além de
   **Atualizar agora** e uma atualização de inicialização se o dado estiver
   velho.
2. `updater.download_and_normalize` baixa o CSV da Caixa com User-Agent de
   navegador, rejeita HTML/CAPTCHA, grava de forma atômica e mantém versão
   normalizada.
3. `collectors.runner` executa BB/Santander/Itaú em subprocessos com timeout
   (padrão 1800 s), logs e escrita atômica; se um coletor falha, o CSV anterior
   daquela fonte permanece.
4. `app.load_state()` chama `caixa_data.load_dataset`, que lê os quatro CSVs,
   aplica configuração, calcula desconto/lucro, exclusões e coordenadas.
5. A UI consome `/api/meta`, `/api/properties` e `/api/facets`.

Falha em uma fonte não apaga as demais. O erro aparece no cabeçalho e no
status da fonte.

## 8. Filtros, busca, ordenação e paginação

Filtros: UF (múltipla, vírgula), cidade, bairro, preço máximo, desconto
mínimo, lucro mínimo, financiamento, modalidade, fonte, texto livre (`q`),
`bbox` do mapa e `aplicar_exclusoes`. A busca textual normaliza acentos e
maiúsculas e cobre ID, UF, cidade, bairro, endereço, descrição e modalidade.

Ordenações: `desconto_desc` (padrão), `lucro_desc`, `lucro_pct_desc`,
`preco_asc`, `preco_desc`, `endereco`. A paginação é progressiva: a API
devolve até 5.000 itens e a UI mostra 60 por vez com “Carregar mais”.

As facetas de UF/cidade/bairro ignoram os filtros de localização entre si, mas
respeitam preço/desconto/lucro/financiamento/modalidade/texto. Modalidade
ignora o próprio filtro.

## 9. Volume e características observadas

Com os dados presentes no projeto original em 13/11/2026:

| Métrica | Valor |
| --- | --- |
| Total de imóveis | 26.317 |
| Caixa | 23.782 |
| Banco do Brasil | 892 |
| Santander | 1.300 |
| Itaú | 343 |
| Excluídos por configuração | 7.160 |
| Com imagem | 26.275 |
| Com coordenadas | 26.317 |
| Precisão bairro/cidade/estado | 845 / 25.370 / 102 |
| UFs | 27 |
| Modalidades | 9 |
| IDs excluídos / locais / valores manuais | 171 / 141 / 153 |

O CSV da Caixa tem ~8,6 MB e 23.782 linhas; o dataset combinado tem cerca de
27 MB em JSON compacto. O projeto original ocupa ~395 MB por incluir
`.venv`, caches e imagens.

## 10. Funcionalidades dependentes de backend

| Funcionalidade | Dependência original | Solução no site estático |
| --- | --- | --- |
| Filtros/facetas/ordenação | `/api/properties`, `/api/facets` | portadas para JS, sobre os JSON carregados |
| Paginação | `limit`/`offset` da API | corte local de 5.000 + “Carregar mais” |
| Atualizar agora | job no Flask | abre o workflow do GitHub Actions |
| Baixar CSV | `/api/csv` | `data/busca_imoveis.csv` gerado pelo Python |
| Proxy de imagens | `/api/image` | Pages Function `functions/api/image.js` |
| Ajustar valor | `POST /api/market-value` | override em localStorage + exportação |
| Excluir imóvel | `POST /api/config` | exclusão local + exportação |
| Configurações | `GET/POST /api/config` | edição local + exportação/importação |
| Geocodificar | jobs Nominatim no Flask | geocodificação no Python, com cache |
| Compartilhar | URL | mantido (client-side) |

## 11. Riscos e observações

- Os portais podem bloquear automação (CAPTCHA/Akamai); por isso o atualizador
  preserva a última versão válida e valida a quantidade de linhas.
- Imagens de terceiros podem falhar/expirar; o placeholder local cobre isso.
- Nominatim/Photon têm limites de uso; o cache e o intervalo de 1,5 s são
  obrigatórios.
- O site original não tem autenticação; a versão estática também é pública.
- Não há banco de dados nem credenciais no projeto original.
