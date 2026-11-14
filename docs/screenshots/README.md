# Screenshots de comparação

Capturados com Playwright/Chromium, locale `pt-BR`, após 5–6 s de espera.

| Arquivo | Descrição |
| --- | --- |
| `original-desktop.png` | projeto original, 1440×1000 |
| `static-desktop.png` | site estático, 1440×1000 (aviso já dispensado) |
| `original-mobile.png` | projeto original, 390×844 |
| `static-mobile.png` | site estático, 390×844 (aviso já dispensado) |
| `static-notice-desktop.png` | aviso de primeira visita, desktop |
| `static-notice-mobile.png` | aviso de primeira visita, mobile |
| `diff-desktop.png` | diferença amplificada (3×) |

Resultado: 99,58% dos pixels idênticos no desktop e 98,25% no mobile. As
diferenças restantes são o botão “Atualizar agora” (removido e substituído por
“Aviso”), o texto de status de atualização e o timing de tiles do mapa.
Detalhes em [../comparacao-visual.md](../comparacao-visual.md).
