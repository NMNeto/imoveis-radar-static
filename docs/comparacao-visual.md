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
| `docs/screenshots/static-notice-desktop.png` | aviso de primeira visita, desktop |
| `docs/screenshots/static-notice-mobile.png` | aviso de primeira visita, mobile |
| `docs/screenshots/diff-desktop.png` | diferença amplificada |

Para comparar o layout, o aviso de primeira visita foi dispensado no
screenshot estático (o botão “Entendi e continuar” foi clicado). O aviso em si
está documentado nas imagens `static-notice-*`.

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
| Desktop 1440×1000 | 6.023 | **0,418%** | botão “Aviso” vs. “Atualizar agora”, status e tiles do mapa |
| Mobile 390×844 | 5.774 | **1,754%** | botão “Aviso” vs. “Atualizar agora” + status no topo |

A diferença de mobile é dominada pelo cabeçalho: o original ainda tem o botão
“Atualizar agora”, enquanto o site público o removeu e colocou “Aviso” no
lugar, além do texto de status de atualização. A cópia temporária do original
não tinha `data/last_update.json`, então exibia “Ainda não atualizado”; o
estático exibe a data do último dado publicado. Em produção o original também
exibe uma data, portanto essa parte é circunstancial.

No desktop, além do cabeçalho, há pequenas diferenças de renderização de tiles
do OpenStreetMap e de clusters do mapa (timing de carregamento). Não há
diferença estrutural de layout, tipografia, cores, espaçamento, cartões,
menu ou responsividade. A remoção do botão de atualização e o aviso de primeira
visita são mudanças intencionais solicitadas.

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
- “Aviso”: reabre o aviso de consulta independente e armazenamento local
  (o botão “Atualizar agora” foi removido por segurança, já que o site é
  público).
- Primeira visita: o aviso abre automaticamente; “Entendi e continuar” fecha
  e grava a marca no `localStorage`; recarregar não reabre; o botão “Aviso”
  reabre quando quiser.
- “Não aceito”: redireciona para `https://www.google.com/` (com tentativa de
  fechar a aba quando permitido pelo navegador) e não grava a marca de leitura.
- Console sem erros em desktop e mobile.

## 6. Conclusão

O site estático é visualmente equivalente ao original: **99,58%** dos pixels
idênticos no desktop e **98,25%** no mobile. As diferenças restantes são
intencionais ou circunstanciais: o botão “Atualizar agora” foi removido e
substituído por “Aviso”, o texto de status de atualização difere e os tiles do
mapa carregam em timing diferente. O conteúdo, a ordem dos cartões, os filtros,
o mapa e as interações foram preservados. O aviso de primeira visita está
documentado separadamente e não altera o layout depois de dispensado.
