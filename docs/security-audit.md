# Auditoria de segurança — Imóveis Radar (Cloudflare Pages)

Data: 14/11/2026  
Escopo: código do site estático em `/home/nmneto/github/imoveis-radar-static`,
Pages Function `functions/api/image.js`, `public/_headers`, build/artefatos,
dependências e frontend.  
Modo: correções aplicadas **localmente**, com testes no preview. O site
publicado só recebe as mudanças após commit/push.

## 1. Resumo executivo

| # | Verificação | Situação encontrada | Ação |
| --- | --- | --- | --- |
| 1 | Cabeçalhos de segurança | `_headers` só tinha XFO, nosniff e Referrer-Policy | CSP, Permissions-Policy, HSTS, COOP, CORP e X-Permitted-Cross-Domain-Policies adicionados |
| 2 | Source maps | Sem arquivos `.map`, mas Leaflet e MarkerCluster tinham `sourceMappingURL` apontando para mapas inexistentes | Comentários removidos; nenhum `.map` em `public/` ou `functions/` |
| 3 | Segredos | Nenhum `.env`, token ou senha versionado; chave pública do Santander no coletor server-side | `.gitignore` reforçado; chave pública documentada e sobrescrevível por `SANTANDER_API_KEY` |
| 4 | CORS | `Access-Control-Allow-Origin: *` na Function de imagem | Cabeçalho removido; `Cross-Origin-Resource-Policy: same-origin` adicionado |
| 5 | Redirects abertos | Não existe `_redirects`; o único redirecionamento é fixo para `google.com` no aviso | Nenhuma correção necessária; comportamento documentado |
| 6 | Dependências | Sem `package.json`/npm; `pip-audit` runtime limpo; `pytest 8.4.2` com vulnerabilidade | `pytest` atualizado para `>=9.0.3,<10`; testes passando |
| 7 | XSS/`innerHTML` | `onerror` inline e URLs interpoladas sem escape | Handlers inline removidos; URLs escapadas; `safeUrl` com `new URL`; imagens só HTTPS |
| 8 | Recursos externos/SRI | Scripts/estilos são locais; Google Forms/OSM são iframe/imagens | Sem SRI aplicável a iframe; CSP restringe origens; tudo em HTTPS |

Resultado: **38 testes passando**, preview local com CSP ativa sem erros de
console, mapa, imagens, popups, configurações e formulário de sugestões
funcionando.

## 2. Cabeçalhos de segurança (`public/_headers`)

Arquivo alterado: `public/_headers`.

Adicionado ao bloco `/*`:

```text
Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self';
  img-src 'self' data: https://venda-imoveis.caixa.gov.br
    https://*.tile.openstreetmap.org; font-src 'self'; connect-src 'self';
  frame-src https://docs.google.com https://forms.gle; object-src 'none';
  base-uri 'self'; form-action 'self'; frame-ancestors 'self';
  upgrade-insecure-requests
X-Frame-Options: SAMEORIGIN
X-Content-Type-Options: nosniff
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=()
Strict-Transport-Security: max-age=63072000; includeSubDomains; preload
Cross-Origin-Opener-Policy: same-origin
Cross-Origin-Resource-Policy: same-origin
Access-Control-Allow-Origin: https://imoveis-radar-static.pages.dev
X-Permitted-Cross-Domain-Policies: none
```

Decisões:

- **`script-src 'self'`** — não há scripts inline. Os antigos `onerror`
  inline foram removidos (ver seção 7).
- **`style-src 'self'`** — o CSS é local e o Leaflet usa CSSOM
  (`element.style`), não `<style>` inline. Testado com mapa, clusters e
  popups; não houve violação de CSP.
- **`img-src`** — permite `self` (imagens/proxy), `data:` (fallback do
  Leaflet), o host das fotos da Caixa e os subdomínios de tiles do OSM.
- **`frame-src`** — permite o iframe do Google Forms (`docs.google.com`) e o
  link curto (`forms.gle`).
- **`frame-ancestors 'self'` + XFO SAMEORIGIN** — o site não pode ser
  enquadrado por terceiros. SAMEORIGIN foi mantido em vez de DENY por
  compatibilidade com previews, sem perda prática.
- **`Cross-Origin-Resource-Policy: same-origin`** — impede hotlink/embed dos
  nossos assets por outros sites.
- **HSTS** — o Pages serve somente HTTPS; `preload` é opcional para o domínio
  final (a inclusão na lista de preload depende do proprietário do domínio).

O preview local (`scripts/dev_server.py`) passou a ler `public/_headers` e
aplicar as regras, para que os testes reflitam a produção.

## 3. Source maps

- Não existe `package.json`, Vite, Next, SvelteKit ou build step. O site é
  publicado diretamente de `public/`.
- `find public functions -name '*.map'` não retorna arquivos.
- `leaflet.js` e `leaflet.markercluster.js` tinham
  `//# sourceMappingURL=...map` apontando para arquivos inexistentes.
  Os comentários foram removidos para não gerar 404 nem sugerir mapas
  públicos.
- `functions/api/image.js` é uma Function simples; não há `_worker.js.map`
  versionado.
- Teste automatizado `tests/test_security.py` garante que não há `.map` nem
  `sourceMappingURL` em `public/static`.

## 4. Segredos

Varreduras realizadas:

```bash
git ls-files | grep -Ei '(\.env|wrangler\.toml|\.pem|\.key|credentials|secrets?)'
grep -RInE 'ghp_|github_pat_|sk-[A-Za-z0-9]|AIza|BEGIN .*PRIVATE KEY|password[=:]' ...
```

Resultado: nenhum segredo privado versionado.

- `.env`, `.env.*`, `.dev.vars*`, `wrangler.toml` e `wrangler.jsonc` foram
  adicionados ao `.gitignore`.
- O único valor com aparência de chave é
  `scripts/imoveis_radar/collectors/extrair_santander.py:32`: a chave
  **pública** usada pelo front-end do portal Santander. Ela não dá acesso a
  conta, dados ou escrita; é sobrescrevível por `SANTANDER_API_KEY`. O
  coletor roda apenas no GitHub Actions, nunca no navegador.
- O workflow usa `${{ secrets.CLOUDFLARE_DEPLOY_HOOK_URL }}` e
  `GITHUB_TOKEN`; nenhum valor é impresso nos logs.
- `public/static/config.js` contém apenas URLs públicas (proxy de imagem e
  Google Forms).

## 5. CORS (Pages Function)

Arquivo: `functions/api/image.js`.

Antes:

```js
"Access-Control-Allow-Origin": "*"
```

Depois:

```js
"Cross-Origin-Resource-Policy": "same-origin"
```

A imagem é consumida por `<img>` same-origin; não há necessidade de CORS. A
allowlist de hosts, a validação de HTTPS/porta 443, a checagem de
`Content-Type: image/*`, o limite de 20 MB e a validação do host final após
redirect continuam ativos. Não há `Access-Control-Allow-Credentials`.

A chave do Cache API passou a incluir `__imoveis_cache=v2`, invalidando
respostas antigas que ainda carregavam `Access-Control-Allow-Origin: *`.
Para os assets estáticos, o `_headers` fixa
`Access-Control-Allow-Origin: https://imoveis-radar-static.pages.dev` em vez
do `*` padrão do Pages.

## 6. Redirects abertos

- Não existe `public/_redirects`.
- O único redirecionamento client-side é o botão **Não concordo** do aviso,
  com destino fixo `https://www.google.com/` via `location.replace`.
- Os links de oferta e o Google Form são links externos explícitos, com
  `rel="noopener noreferrer"`, não redirecionamentos controlados pelo site.
- Não há endpoint que aceite URL de destino arbitrária.

## 7. XSS, `innerHTML` e manipulação de DOM

Arquivos: `public/static/app.js`, `public/index.html`.

Correções:

1. **Removidos handlers inline** `onerror="..."` dos cartões e popups.
   Agora as imagens usam `data-fallback` e um único listener global de
   `error` em fase de captura:
   - cartão → `static/placeholder.svg`;
   - popup → esconde a imagem.
   Isso é compatível com `script-src 'self'` (sem `unsafe-inline`).
2. **URLs escapadas** em `href` e `src`: `escapeHtml(link)` e
   `escapeHtml(image)`.
3. **`safeUrl`** valida com `new URL`, aceita apenas `http:`/`https:` e
   normaliza a URL. `imageSrc` exige HTTPS para imagens.
4. Os demais usos de `innerHTML` foram revisados:
   - combos/opções usam `escapeHtml`;
   - cartões/popups escapam textos e atributos;
   - fallback do mapa é uma string estática;
   - `textContent` é usado em status/toasts.
5. Não há `eval`, `new Function` ou `document.write` no código do site.
6. O conteúdo do Leaflet/MarkerCluster é biblioteca vendorizada; não recebe
   dados não confiáveis além do popup que já é escapado.

## 8. Dependências e SRI

- Não há `package.json`; `npm audit` não se aplica.
- Runtime Python (`requirements.txt`): `pip-audit` → **No known
  vulnerabilities found**.
- Desenvolvimento (`requirements-dev.txt`): `pytest 8.4.2` apresentava
  `PYSEC-2026-1845`; atualizado para `pytest>=9.0.3,<10`. Nova auditoria:
  **No known vulnerabilities found**. Os 38 testes passam com pytest 9.
- Scripts e CSS são locais (`public/static/*`), então SRI não é necessário
  para eles. O iframe do Google Forms não suporta SRI; a proteção é a CSP
  `frame-src` restrita. Os tiles do OSM são imagens HTTPS; não há script
  externo.
- Todas as imagens do site são HTTPS ou same-origin; `imageSrc` rejeita
  `http://`.

## 9. Testes e validação

Comandos executados:

```bash
python -m pytest -q          # 37 passed
pip-audit -r requirements.txt
pip-audit -r requirements-dev.txt
```

Testes de navegador (Playwright/Chromium) no preview local com os headers
reais de `public/_headers`:

- página carrega; 17.876 imóveis e 60 cartões;
- imagens da Caixa, BB, Santander e Itaú carregam (proxy incluído);
- 12 tiles do OSM e marcadores/clusters renderizam;
- popup do mapa abre;
- modal de Sugestões carrega o Google Form (`docs.google.com`);
- “Não concordo” vai para `https://www.google.com/`;
- “Configurações” abre e exporta `config-local.json` (download funciona sob
  CSP);
- fallback de imagem quebrada troca para `static/placeholder.svg`;
- **0 erros de console, 0 violações de CSP**.

## 10. Validação no domínio publicado

Após o primeiro deploy das correções, foi verificado em
`https://imoveis-radar-static.pages.dev/`:

- CSP, HSTS, XFO, nosniff, Referrer-Policy, Permissions-Policy, COOP e CORP
  presentes;
- Function de imagem com resposta nova sem `Access-Control-Allow-Origin: *`;
- respostas de imagem antigas em cache ainda tinham `*`; por isso a chave do
  Cache API foi versionada para `v2`;
- assets estáticos do Pages vinham com `Access-Control-Allow-Origin: *`
  padrão; o `_headers` agora fixa a origem de produção;
- caminhos `.map` retornavam o `index.html` com 200 (soft-404), mas **sem
  conteúdo de source map**; foi adicionada uma página `404.html` para que o
  Pages responda 404 de verdade quando essa configuração estiver ativa.

O site continuou funcionando no teste de produção: 17.876 imóveis, 60
cartões, mapa, imagens, modal de sugestões e configurações, sem erros de
console ou violações de CSP.

## 11. Riscos residuais e recomendações

1. **Google Forms** — as respostas são privadas na conta Google do
   proprietário, mas isso depende das configurações do formulário. Confirme
   que o link de “Ver respostas” não está público e que a coleta de e-mail é
   intencional. O site não armazena respostas.
2. **Chave pública do Santander** — não é segredo, mas pode ser rotacionada
   pelo portal. Se isso ocorrer, defina `SANTANDER_API_KEY` no ambiente do
   GitHub Actions.
3. **CSP e novas fontes** — ao adicionar uma nova fonte de imagens, será
   necessário incluir o host em `img-src`; ao adicionar outro iframe, incluir
   em `frame-src`. Evite `unsafe-inline`/`unsafe-eval`.
4. **HSTS preload** — o header já está presente; a inclusão na lista de
   preload é uma decisão do domínio final.
5. **Proxy de imagem** — a allowlist e o cache reduzem abuso, mas não há
   rate limit por IP. Se necessário, adicione Turnstile/rate limit na
   Function.
6. **Produção** — as correções estão locais; após o push, valide os headers
   no domínio publicado com:

```bash
curl -sSI https://imoveis-radar-static.pages.dev/ | grep -Ei \
  'content-security-policy|x-frame-options|strict-transport-security|cross-origin'
```

## 12. Arquivos alterados nesta auditoria

| Arquivo | Alteração |
| --- | --- |
| `public/_headers` | CSP e cabeçalhos de segurança completos; CORS restrito |
| `public/404.html` | página 404 real (evita soft-404 em caminhos `.map`) |
| `functions/api/image.js` | removido CORS `*`; CORP; chave de cache versionada |
| `public/static/app.js` | `safeUrl`/HTTPS, escape de URLs, fim dos `onerror` inline, fallback global |
| `public/static/vendor/leaflet.js` | removido `sourceMappingURL` |
| `public/static/vendor/leaflet.markercluster.js` | removido `sourceMappingURL` |
| `.gitignore` | `.env*`, `.dev.vars*`, `wrangler.toml/jsonc` |
| `requirements-dev.txt` | `pytest>=9.0.3,<10` |
| `scripts/dev_server.py` | preview aplica `_headers` do Pages |
| `tests/test_security.py` | testes de headers/CSP/maps/CORS/handlers/segredos |
| `docs/validacao-dados.md`, `docs/entrega.md`, `README.md` | atualização de contagens e documentação |

## 13. Conclusão

As vulnerabilidades apontadas foram tratadas ou documentadas. O preview local
funciona com CSP restritiva, sem `unsafe-inline`/`unsafe-eval`, sem CORS
curinga e sem source maps. A validação no domínio publicado fica pendente do
push e do deploy do Cloudflare Pages.
