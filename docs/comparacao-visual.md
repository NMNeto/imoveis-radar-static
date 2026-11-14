# Relatório de comparação visual

## 1. Método

- Original executado a partir de uma **cópia temporária** em
  `/tmp/opencode/original-preview`, com:
  - `DISABLE_BACKGROUND_JOBS=1` (sem scheduler/update);
  - `RUN_COLLECTORS=0`;
  - `DATA_DIR` apontando para a cópia temporária;
  - código lido do projeto original, sem escrita nele.
- Site estático servido por `scripts/dev_server.py`, que implementa o mesmo
  `/api/image` usado em produção.
- Mesmo Chromium/Playwright, viewport e locale (`pt-BR`).
- Espera de 5–6 s para imagens, tiles e clusters assentarem.
- Comparação pixel a pixel com Pillow (`ImageChops.difference`).

## 2. Evidências

| Arquivo | Conteúdo |
| --- | --- |
| `docs/screenshots/original-desktop.png` | original, 1440×1000 |
| `docs/screenshots/static-desktop.png` | estático, 1440×1000 |
| `docs/screenshots/original-mobile.png` | original, 390×844 |
| `docs/screenshots/static-mobile.png` | estático, 390×844 |
| `docs/screenshots/diff-desktop.png` | diferença amplificada |

## 3. Comparação de conteúdo (DOM)

| Métrica | Original | Estático |
| --- | --- | --- |
| Título | Busca Imóveis | Busca Imóveis |
| Cabeçalho | 26.317 imóveis · gerado em 2026-11-12 | idêntico |
| Contagem | 11.882 imóveis (mostrando 5.000) | idêntico |
| Cartões renderizados | 60 | 60 |
| Primeiro cartão | Santander, R$ 25.464, -90,2% | idêntico |
| Segundo cartão | Caixa, R$ 13.300 | idêntico |
| Terceiro cartão | Caixa, R$ 180.936 | idêntico |
| Erros de página | 0 | 0 |
| Erros de console | 0 | 0 |

A primeira comparação revelou que os empates de desconto estavam em ordem
diferente porque o novo pipeline ordenava por ID. A ordenação foi corrigida
para preservar a ordem das linhas de cada CSV, exatamente como o original.
Após a correção, os cartões ficaram na mesma ordem.

## 4. Diferença de pixels

| Viewport | Pixels diferentes | Percentual | Região |
| --- | --- | --- | --- |
| Desktop 1440×1000 | 2.765 | **0,192%** | texto de “Atualizado” no topo + tiles do mapa |
| Mobile 390×844 | 6.015 | **1,827%** | apenas o texto de “Atualizado” no topo |

A diferença de mobile é dominada pelo texto de status de atualização: a cópia
temporária do original não tinha `data/last_update.json`, então exibia
“Ainda não atualizado”; o estático exibe a data do último dado publicado. Em
produção o original também exibe uma data, portanto essa diferença é
circunstancial.

No desktop, além do status, há pequenas diferenças de renderização de tiles
do OpenStreetMap e de clusters do mapa (timing de carregamento). Não há
diferença estrutural de layout, tipografia, cores, espaçamento, cartões,
menu ou responsividade.

## 5. Testes funcionais executados

- Filtro UF = RJ: contagem caiu para **1.070 imóveis**; a lista e o mapa
  atualizaram.
- Combos de UF/cidade/bairro: opções e typeahead funcionando.
- Busca textual, desconto mínimo, lucro mínimo, financiamento, modalidade e
  fonte: filtros aplicados no cliente.
- Ordenação: maior desconto, lucro R$, lucro %, menor/maior preço, endereço.
- “Carregar mais”: 60 → 120 cartões.
- Mapa: clusters, popups e “Filtrar pelo mapa”/“Limpar área”.
- “Compartilhar”: URL com filtros.
- “Baixar CSV”: download do CSV combinado.
- “Configurações”: abre, mostra 171 IDs, 141 locais e 153 valores, salva
  overrides no navegador, exporta `config-local.json`.
- “Ajustar valor” e “Excluir”: recalculam desconto/lucro e refletem na lista.
- “Atualizar agora”: abre o workflow do GitHub Actions.
- Console sem erros em desktop e mobile.

## 6. Conclusão

O site estático é visualmente equivalente ao original: **99,81%** dos pixels
idênticos no desktop e **98,17%** no mobile, com as diferenças explicadas por
status de atualização e timing de tiles. O conteúdo, a ordem dos cartões, os
filtros, o mapa e as interações foram preservados.
