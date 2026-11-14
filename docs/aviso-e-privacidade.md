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
- **Sugestões:** o formulário é hospedado pelo **Google Forms**. O site não
  armazena as respostas; elas ficam na conta do responsável pelo formulário.
  O Google pode usar cookies próprios; consulte a política de privacidade do
  Google.
- **Google Tag Manager (GTM-PQ5NNHX6):** o container só é carregado depois do
  consentimento explícito no aviso de primeira visita (checkbox de análise,
  medição e publicidade). Sem consentimento, nenhuma requisição é feita ao
  Google. O container pode ativar Google Analytics, Google Ads/DoubleClick e
  pixels de parceiros e definir cookies. A escolha pode ser alterada pelo
  botão **Aviso**.
- **Mapa:** tiles do OpenStreetMap; geocodificação Nominatim/Photon no
  servidor, não no navegador.

Como não há cookies não essenciais, não é necessário um banner de
consentimento no estilo “aceitar/rejeitar”. O aviso informativo é uma medida
de transparência e pode ser reaberto pelo botão **Aviso** no topo.

## 2. Texto implementado

Título: **Antes de continuar**

> Este site é uma ferramenta independente de **consulta**, criada para
> aprendizado com a ajuda de IA, e **não vende imóveis**. Reunimos anúncios
> públicos da Caixa, Banco do Brasil, Santander e Itaú para ajudar você a
> localizar oportunidades.
>
> Preços, disponibilidade, condições, imagens e links podem mudar a qualquer
> momento. **Confirme sempre as informações no site oficial da fonte** antes de
> tomar qualquer decisão. Ao clicar em “Ver oferta”, você sai deste site e
> passa a seguir as políticas do portal de origem.
>
> **Cookies e armazenamento:** não usamos cookies próprios de publicidade.
> Com o seu consentimento, carregamos o Google Tag Manager, que pode ativar
> tags de análise, medição e publicidade do Google e de parceiros e definir
> cookies. Você pode recusar; o site funciona normalmente. Também usamos
> armazenamento local para preferências e para este aviso. A Cloudflare pode
> usar cookies de segurança. [Saiba mais](https://policies.google.com/technologies/cookies).

Checkbox:

> **Aceito o uso de cookies de análise, medição e publicidade do Google e de
> parceiros de medição para ajudar a melhorar o site. (Opcional)**

Botões:

- **Entendi e continuar** — fecha o aviso, grava a marca no `localStorage` e,
  se o checkbox estiver marcado, grava o consentimento do GTM.
- **Não concordo** — redireciona para `https://www.google.com/` usando
  `location.replace`, sem deixar o aviso no histórico. O aviso não é marcado
  como lido; se a pessoa voltar, ele aparece de novo.

> **Por que só redirecionar?** `window.close()` só funciona de forma confiável
> em abas abertas por `window.open`; em uma aba normal o navegador ignora a
> chamada. O redirecionamento é a saída garantida e previsível.

Texto do rodapé do aviso:

> Se você não concordar com estes termos, use “Não concordo” para sair.

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

## 5. Google Tag Manager (GTM-PQ5NNHX6)

- O snippet foi adaptado para CSP: a inicialização (`dataLayer`, `gtag`) está
  em `public/static/gtm-loader.js`, um arquivo local, sem `unsafe-inline`.
- O script externo `https://www.googletagmanager.com/gtm.js?id=GTM-PQ5NNHX6`
  só é injetado se a chave
  `imoveis-radar-static:analytics-consent:v1` estiver como `granted`.
- O checkbox do aviso grava essa chave. “Entendi e continuar” sem o checkbox
  mantém o GTM desligado. “Não concordo” também grava `denied` e sai para o
  Google.
- Para revogar depois: **Aviso** → desmarcar o checkbox → **Entendi e
  continuar**. A página recarrega e o GTM deixa de ser carregado.
- O container pode carregar Google Analytics, Google Ads/DoubleClick e pixels
  de parceiros; a CSP libera os hosts necessários. Revise as tags dentro do
  GTM, pois elas podem mudar fora deste repositório.
- O site não inclui o `<noscript>` do GTM, para não carregar o container sem
  consentimento.

## 6. Sugestões

O botão **Sugestões** abre o Google Form
<https://forms.gle/HnciJsM5Xzto8ATd6> em um modal. A URL de incorporação e o
link externo ficam em `public/static/config.js`:

```js
feedbackUrl: "https://forms.gle/HnciJsM5Xzto8ATd6",
feedbackEmbedUrl: "https://docs.google.com/forms/d/e/.../viewform?embedded=true",
```

- As respostas são privadas na conta Google do responsável.
- O site não armazena nenhuma resposta.
- Se o iframe não carregar, o modal oferece “Abrir no Google Forms”.
- Se você trocar o formulário, atualize as duas URLs em `config.js`.
- Confira no Google Forms se o link de “Ver respostas” não está público.
