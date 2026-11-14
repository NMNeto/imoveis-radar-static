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
- O aviso de primeira visita foi dispensado nos screenshots de layout; ele
  está documentado separadamente em `static-notice-*`.

## 2. Evidências

| Arquivo | Conteúdo |
| --- | --- |
| `docs/screenshots/original-desktop.png` | original, 1440×1000 |
| `docs/screenshots/original-mobile.png` | original, 390×844 |
| `docs/screenshots/static-antes-limpeza-desktop.png` | estático **com a configuração original**, 1440×1000 |
| `docs/screenshots/static-antes-limpeza-mobile.png` | estático **com a configuração original**, 390×844 |
| `docs/screenshots/diff-layout-antes-limpeza.png` | diferença de layout antes da limpeza |
| `docs/screenshots/static-desktop.png` | estático **atual**, após limpar as listas, 1440×1000 |
| `docs/screenshots/static-mobile.png` | estático **atual**, após limpar as listas, 390×844 |
| `docs/screenshots/diff-desktop.png` | diferença atual (inclui mudança intencional de conteúdo) |
| `docs/screenshots/static-notice-desktop.png` | aviso de primeira visita, desktop |
| `docs/screenshots/static-notice-mobile.png` | aviso de primeira visita, mobile |

## 3. Comparação de conteúdo (DOM)

| Métrica | Original | Estático |
| --- | --- | --- |
| Título | Busca Imóveis | Busca Imóveis |
| Cabeçalho | 26.317 imóveis · gerado em 2026-11-12 | idêntico |
| Contagem com a configuração original | 11.882 imóveis (mostrando 5.000) | 11.882 — idêntico |
| Contagem após limpar as listas | 11.882 | **17.876** — mudança intencional |
| Cartões renderizados | 60 | 60 |
| Primeiros cartões (configuração original) | Santander R$ 25.464, Caixa R$ 13.300, Caixa R$ 180.936 | idênticos |
| Erros de página | 0 | 0 |
| Erros de console | 0 | 0 |

A primeira comparação revelou que os empates de desconto estavam em ordem
diferente porque o novo pipeline ordenava por ID. A ordenação foi corrigida
para preservar a ordem das linhas de cada CSV, exatamente como o original.
Com a mesma configuração, os cartões ficaram na mesma ordem.

Depois, a pedido, as listas de configuração foram limpas para **um exemplo
sem correspondência real em cada uma**. Por isso o site atual mostra 17.876
imóveis no filtro padrão, em vez de 11.882. Essa diferença é intencional e
não é uma regressão de layout.

## 4. Diferença de pixels

### 4.1. Layout com a mesma configuração (antes da limpeza)

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
menu ou responsividade.

### 4.2. Estado atual após limpar as listas

| Viewport | Pixels diferentes | Percentual | Motivo |
| --- | --- | --- | --- |
| Desktop 1440×1000 | 356.886 | **24,784%** | conteúdo diferente: mais imóveis visíveis, outros cartões e clusters |

O número maior **não indica mudança de layout**: é o efeito esperado de
remover as exclusões que escondiam 7.160 imóveis e os 153 overrides de valor.
A estrutura visual continua a mesma.

## 5. Testes funcionais executados

- Filtro UF = RJ: a lista e o mapa atualizam; a contagem aumenta após a
  limpeza das listas.
- Combos de UF/cidade/bairro: opções e typeahead funcionando.
- Busca textual, desconto mínimo, lucro mínimo, financiamento, modalidade e
  fonte: filtros aplicados no cliente.
- Ordenação: maior desconto, lucro R$, lucro %, menor/maior preço, endereço.
- “Carregar mais”: 60 → 120 cartões.
- Mapa: clusters, popups e “Filtrar pelo mapa”/“Limpar área”.
- “Compartilhar”: URL com filtros.
- “Baixar CSV”: download do CSV combinado.
- “Configurações”: abre mostrando **um exemplo em cada lista**
  (`00000000`, `CIDADE EXEMPLO,BAIRRO EXEMPLO,all`,
  `00000000,350000`), salva overrides no navegador e exporta
  `config-local.json`.
- Exemplos não escondem nem ajustam imóveis: 0 badges “excluído” e 0 badges
  “ajustado” no carregamento inicial.
- “Ajustar valor” e “Excluir”: recalculam desconto/lucro e refletem na lista.
- “Aviso”: reabre o aviso de consulta independente e armazenamento local
  (o botão “Atualizar agora” foi removido por segurança, já que o site é
  público).
- Primeira visita: o aviso abre automaticamente; “Entendi e continuar” fecha
  e grava a marca no `localStorage`; recarregar não reabre; o botão “Aviso”
  reabre quando quiser.
- “Não concordo”: redireciona para `https://www.google.com/` e não grava a
  marca de leitura.
- “Sugestões”: abre o Google Form em um modal, carrega o título e as perguntas
  corretas e oferece “Abrir no Google Forms” como fallback.
- “Ajuda”: abre o guia com filtros, fórmulas, imóveis sem avaliação/preço,
  configurações, mapa e privacidade; o atalho dentro do aviso também funciona.
- “Filtrar pelo mapa”: inicia ativo, atualiza ao mover o mapa e “Limpar área”
  desativa. Os botões de geocodificação manual foram removidos.
- Cidades/bairros: variantes equivalentes aparecem uma única vez (ex.:
  Niterói, não Niteroi/Niterói).
- GTM: nenhuma requisição ao Google sem consentimento; com o checkbox marcado,
  `gtm.js` e o GA4 carregam; ao revogar, a página recarrega sem GTM.
- Console sem erros em desktop e mobile.

## 6. Conclusão

Com a mesma configuração, o layout é equivalente ao original: **99,58%** dos
pixels idênticos no desktop e **98,25%** no mobile. As diferenças restantes
nessa comparação são o botão “Atualizar agora” (substituído por “Aviso”), o
texto de status e o timing dos tiles do mapa.

Depois da limpeza das listas, o conteúdo mudou intencionalmente (17.876
imóveis em vez de 11.882), mas a estrutura visual, os filtros, o mapa e as
interações permanecem os mesmos.
