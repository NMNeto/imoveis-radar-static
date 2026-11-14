# Screenshots de comparação

Capturados com Playwright/Chromium, locale `pt-BR`, após 5–6 s de espera.

| Arquivo | Descrição |
| --- | --- |
| `original-desktop.png` | projeto original, 1440×1000 |
| `original-mobile.png` | projeto original, 390×844 |
| `static-antes-limpeza-desktop.png` | estático com a configuração original, 1440×1000 |
| `static-antes-limpeza-mobile.png` | estático com a configuração original, 390×844 |
| `diff-layout-antes-limpeza.png` | diferença de layout antes da limpeza |
| `static-desktop.png` | estático atual, após limpar as listas, 1440×1000 |
| `static-mobile.png` | estático atual, após limpar as listas, 390×844 |
| `diff-desktop.png` | diferença atual (inclui conteúdo intencionalmente diferente) |
| `static-notice-desktop.png` | aviso de primeira visita, desktop |
| `static-notice-mobile.png` | aviso de primeira visita, mobile |
| `feedback-desktop.png` | modal Sugestões com o Google Form, desktop |
| `feedback-mobile.png` | modal Sugestões com o Google Form, mobile |

- **Layout com a mesma configuração:** 99,58% de pixels idênticos no desktop
  e 98,25% no mobile.
- **Estado atual:** 17.876 imóveis (antes 11.882), pois as listas de exclusão
  e valores manuais foram limpas para um exemplo sem correspondência real.
  A diferença de 24,78% no desktop é de **conteúdo**, não de layout.

Detalhes em [../comparacao-visual.md](../comparacao-visual.md).
