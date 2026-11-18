# SEO — checklist operacional

Este documento cobre as ações que **não** são só código: verificação no Google
Search Console, Bing, e a checagem do WAF. O que é código está implementado e
validado por `tests/test_seo.py`.

## 1. Google Search Console (fazer uma vez)

1. **Verificar a propriedade de domínio** `imovanta.com.br` via **DNS TXT**:
   - GSC → *Adicionar propriedade* → **Domínio**.
   - Copie o valor `google-site-verification=...`.
   - Cloudflare → DNS → *Add record* → **TXT**, nome `@`, conteúdo copiado.
   - Volte ao GSC e clique em *Verificar* (a propagação leva segundos na
     Cloudflare).
2. **Enviar o sitemap:** `https://imovanta.com.br/sitemap.xml`.
3. **Inspecionar a home** → *Solicitar indexação*.
4. **Confirmar que não há `noindex`:** `python scripts/verificar_seo.py` já
   valida `meta robots`, `X-Robots-Tag`, canonical, H1, JSON-LD, robots.txt e
   sitemap.
5. **Relatório "Páginas":** anotar o motivo real (`Rastreada – não indexada`
   vs. `Detectada – não indexada`). Isso define se o gargalo é conteúdo ou
   descoberta.

## 2. Bing / IndexNow

1. Bing Webmaster Tools → *Add site* → importar do GSC (mais rápido).
2. Enviar o mesmo `sitemap.xml`.
3. IndexNow é opcional; o sitemap já cobre a descoberta diária.

## 3. Host duplicado (`www`)

`https://www.imovanta.com.br/` responde **200** hoje. O canonical aponta para o
apex, mas o correto é **301**:

- Cloudflare → **Rules → Redirect Rules → Create**.
- Expressão: `http.host eq "www.imovanta.com.br"`.
- Destino: `concat("https://imovanta.com.br", http.request.uri.path)`.
- Status: **301**, preservar query string.

## 4. WAF e Googlebot

A regra do CSV (`Managed Challenge` em `/data/busca_imoveis.csv`) **não deve**
desafiar bots verificados. Para confirmar:

1. Cloudflare → **Security → Events**.
2. Filtre por `Rule ID` da regra do CSV e por `bot` = *Googlebot*.
3. Se aparecer challenge para Googlebot, edite a regra e adicione
   `and not cf.client.bot` à expressão, mantendo o desafio para humanos.

Enquanto isso, o `robots.txt` já pede para o rastreador **não** baixar o CSV
(14 MB) e não rastrear os estados voláteis da interface (`sort`, `bbox`,
`exclusoes`).

> A verificação de UA não serve como prova: apenas o UA de Googlebot verificado
> pela Cloudflare é reconhecido. Use sempre os Security Events.

## 5. O que foi implementado no código

| Item | Onde |
| --- | --- |
| `robots.txt` com `Sitemap:` e exclusões | `public/robots.txt` |
| Sitemap derivado das páginas publicadas | `scripts/imoveis_radar/sitemap.py` |
| Sitemap gerado no fim de cada atualização | `scripts/imoveis_radar/cli.py` |
| Geração manual do sitemap | `scripts/gerar_sitemap.py` |
| Title/description/OG/Twitter da home | `public/index.html` |
| JSON-LD `WebSite` + `Organization` + `SearchAction` | `public/index.html` |
| H1 com texto real (sr-only, sem mudar layout) | `public/index.html` |
| Imagem OG 1200×630 | `public/static/og-image.png` |
| Cache/Content-Type de `sitemap.xml` e `robots.txt` | `public/_headers` |
| Verificação automática pós-deploy | `scripts/verificar_seo.py` |
| Testes de regressão | `tests/test_seo.py` |

Comandos úteis:

```bash
python scripts/gerar_sitemap.py            # regenera public/sitemap.xml
python scripts/verificar_seo.py            # audita produção
python scripts/verificar_seo.py --url http://127.0.0.1:8080/
python scripts/gerar_og_image.py           # regera a imagem OG (Pillow)
```

## 6. Limites atuais (conscientes)

- O sitemap lista **apenas a home**, porque ainda não existem páginas em path.
  Ele cresce automaticamente quando as landing pages (`/imoveis/{uf}/{cidade}/`)
  forem geradas — basta o `index.html` existir e não ter `noindex`.
- `Disallow: /data/` **não** foi aplicado: sem pré-renderização o Google
  depende dos JSONs para renderizar o app. Aplicar só depois do item 9 do plano
  de SEO (landing pages pré-renderizadas).
- Páginas de filtro continuam com canonical para `/`; elas não são indexáveis
  por design até virarem paths próprios.

## 7. Páginas de SEO por estado, cidade e banco

- Geradas por `scripts/imoveis_radar/paginas.py` no fim de cada atualização
  (e manualmente por `python scripts/gerar_paginas.py`).
- URLs: `/imoveis/`, `/imoveis/{uf}/`, `/imoveis/{uf}/{cidade}/`,
  `/imoveis/banco/{fonte}/`. Cidade entra com **≥ 10 imóveis** na visão padrão.
- Cada página tem HTML completo (sem JS), H1 textual, números próprios
  (total, desconto médio, preço mediano, % financiável), 12 cards
  pré-renderizados, canonical autorreferente, `BreadcrumbList` +
  `CollectionPage`, e links internos para as páginas vizinhas.
- Páginas que deixam de ter o mínimo são removidas automaticamente.
- O sitemap passa a listar essas páginas (hoje 188 URLs).

## 8. Desempenho (LCP)

- A home agora traz 24 cards pré-renderizados no HTML e os scripts usam
  `defer`; a primeira pintura de conteúdo não depende dos ~3 MB de JSON.
- A imagem do primeiro card com URL direta recebe `preload` +
  `fetchpriority="high"`, para não ficar atrás das imagens do proxy.
- Páginas de cidade medem LCP ~1 s em 4G lento com CPU 4×; a home ainda é
  limitada pelas imagens (o proxy `/api/image` busca a origem na primeira vez).
- Próximo passo para a home: dividir os JSONs por UF e carregar só a fatia
  necessária.
