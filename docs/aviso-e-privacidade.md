# Aviso de primeira visita e privacidade

## 1. O que o site usa

- **Cookies próprios:** nenhum. Não há analytics, publicidade, pixels de
  rastreamento ou login.
- **Armazenamento local (`localStorage`):**
  - `imoveis-radar-static:overrides:v1` — ajustes de valor de venda,
    exclusões e premissas feitos pelo usuário no navegador;
  - `imoveis-radar-static:notice:v1` — marca que o aviso de primeira visita
    já foi lido.
- **Cloudflare:** a plataforma pode definir cookies estritamente necessários
  de segurança (por exemplo, `__cf_bm`/`cf_clearance`, conforme a configuração
  da zona). Eles não são usados para publicidade ou perfilamento pelo site.
- **Terceiros:** ao clicar em “Ver oferta”, o usuário vai para Caixa, BB,
  Santander, Itaú ou parceiros. Esses sites têm suas próprias políticas de
  cookies e privacidade.
- **Mapa:** tiles do OpenStreetMap; geocodificação Nominatim/Photon no
  servidor, não no navegador.

Como não há cookies não essenciais, não é necessário um banner de
consentimento no estilo “aceitar/rejeitar”. O aviso informativo é uma medida
de transparência e pode ser reaberto pelo botão **Aviso** no topo.

## 2. Texto implementado

Título: **Antes de continuar**

> Este site é uma ferramenta independente de **consulta** e **não vende
> imóveis**. Reunimos anúncios públicos da Caixa, Banco do Brasil, Santander e
> Itaú para ajudar você a localizar oportunidades.
>
> Preços, disponibilidade, condições, imagens e links podem mudar a qualquer
> momento. **Confirme sempre as informações no site oficial da fonte** antes de
> tomar qualquer decisão. Ao clicar em “Ver oferta”, você sai deste site e
> passa a seguir as políticas do portal de origem.
>
> **Cookies e armazenamento:** não usamos cookies próprios de publicidade,
> análise ou rastreamento. Usamos o armazenamento local do navegador apenas
> para lembrar seus ajustes de configuração e para não mostrar este aviso
> novamente. A Cloudflare pode usar cookies estritamente necessários de
> segurança da plataforma.

Botão: **Entendi e continuar**

## 3. Sugestões alternativas

### 3.1. Curta e direta

> **Site apenas para consulta.** Não vendemos imóveis. Preços e
> disponibilidade podem mudar; confirme sempre no site oficial da fonte.
> Não usamos cookies de rastreamento — apenas armazenamento local para suas
> preferências e para este aviso.

### 3.2. Formal

> **Aviso importante.** Este site é independente e tem finalidade
> exclusivamente informativa, não constituindo oferta de venda. As informações
> são coletadas de portais públicos e podem sofrer alterações sem aviso.
> Recomendamos confirmar todos os dados diretamente na fonte original antes de
> qualquer decisão. O site não utiliza cookies próprios de publicidade ou
> análise; utiliza armazenamento local estritamente para preferências e para
> registrar a leitura deste aviso.

### 3.3. Amigável

> **Bem-vindo!** Este site ajuda você a encontrar imóveis, mas não vende nada.
> As ofertas são das fontes originais — confirme preço, disponibilidade e
> condições lá antes de seguir. Também não usamos cookies de rastreamento:
> só guardamos suas preferências no navegador.

## 4. Como alterar

- Texto e estrutura: `public/index.html`, elemento `#notice-dialog`.
- Estilo: `public/static/style.css`, classes `.notice-dialog`/`.notice-form`.
- Comportamento: `public/static/app.js`, funções `showNoticeIfNeeded`,
  `openNotice`, `acceptNotice`.
- A chave `imoveis-radar-static:notice:v1` no `localStorage` controla se o
  aviso já foi lido. Para testar novamente, apague essa chave no DevTools.
