# Publicação na Cloudflare Pages

## 1. Pré-requisitos

- Conta gratuita na Cloudflare.
- Repositório novo no GitHub (este projeto).
- Nenhum build step, Node.js ou variável obrigatória.

## 2. Criar o projeto no Pages

1. Acesse **Cloudflare Dashboard → Workers & Pages → Create → Pages →
   Connect to Git**.
2. Autorize a Cloudflare a ler o repositório `imoveis-radar-static`.
3. Selecione o repositório e a branch `main`.
4. Preencha:

| Campo | Valor |
| --- | --- |
| Project name | `imoveis-radar-static` (ou outro) |
| Production branch | `main` |
| Framework preset | `None` |
| Build command | *(deixar vazio)* |
| Build output directory | `public` |
| Root directory | `/` |
| Environment variables | *(nenhuma obrigatória)* |

5. Clique em **Save and Deploy**.

O primeiro deploy publica `public/index.html`, `public/static/*`,
`public/data/*` e a Function `functions/api/image.js`.

> **Por que sem build?** O Python roda no GitHub Actions e grava os JSONs
> diretamente em `public/data/`. O Pages só serve o artefato. Isso elimina
> dependência de Node/Python no ambiente de build do Pages.

## 3. Validar no endereço pages.dev

Após o deploy, abra:

```text
https://<projeto>.pages.dev/
```

Checklist:

- [ ] A página carrega com o mesmo visual do original.
- [ ] “26.317 imóveis” aparece no cabeçalho.
- [ ] Filtros de UF/cidade/bairro funcionam.
- [ ] Busca, desconto mínimo, lucro mínimo e financiamento funcionam.
- [ ] Ordenação e “Carregar mais” funcionam.
- [ ] Mapa carrega tiles e clusters.
- [ ] Imagens de Caixa aparecem.
- [ ] Imagens de Santander/Itaú/BB aparecem via `/api/image`.
- [ ] “Baixar CSV” baixa `data/busca_imoveis.csv`.
- [ ] “Compartilhar” copia a URL com filtros.
- [ ] O aviso de primeira visita aparece, fecha em “Entendi e continuar” e
      não reabre ao recarregar; o botão “Aviso” reabre.
- [ ] “Sugestões” abre o Google Form no modal e o fallback “Abrir no Google
      Forms” funciona.
- [ ] “Ajuda” abre o guia completo; o atalho “Ver o guia de ajuda” funciona
      dentro do aviso de primeira visita.
- [ ] O GTM não faz requisições antes do consentimento; ao marcar o checkbox
      e aceitar, o `gtm.js` carrega; ao revogar, deixa de carregar.
- [ ] “Configurações” abre e salva ajustes locais.
- [ ] Console do navegador sem erros.
- [ ] Layout responsivo em 390 px e 1440 px.

Teste direto do proxy:

```text
https://<projeto>.pages.dev/api/image?url=https%3A%2F%2Fshi.santander.com.br%2Fproperties%2F02.05150%2Fi_89068_02.jpg
```

Respostas esperadas: `200 image/*` ou `502` se a origem bloquear. Em caso de
502, o frontend cai no placeholder local — o layout não quebra.

## 4. Functions e roteamento

- `functions/api/image.js` é detectado automaticamente pelo Pages.
- `public/_routes.json` limita a invocação de Functions a `/api/*`, então
  arquivos estáticos e JSON **não** consomem a cota de Workers.
- `public/_headers` define cache:
  - `/data/*`: 5 minutos;
  - `/static/*`: 1 hora;
  - cabeçalhos de segurança básicos.
- O proxy valida protocolo HTTPS, hostname em allowlist, porta 443, tipo
  `image/*` e tamanho máximo de 20 MB. Ele usa o Cache API por 7 dias.

## 5. Previews e histórico

- **Preview deployments** são habilitados por padrão para branches/PRs.
- Cada push em `main` gera um novo deploy de produção.
- O histórico de deploys fica em **Deployments** e permite rollback.
- PRs de mudanças de código geram URL de preview; mudanças de dados também
  podem ser revisadas antes do merge.

## 6. Domínio personalizado

Não altere DNS de produção sem autorização. Quando for validar com domínio
próprio:

1. **Pages → Custom domains → Set up a domain**.
2. Se o domínio estiver na Cloudflare, o Pages cria o CNAME necessário.
3. Se estiver fora, crie um `CNAME` apontando para `<projeto>.pages.dev`.
4. Valide primeiro em um subdomínio de teste (ex.: `novo.exemplo.com`) e só
   depois troque o domínio principal.
5. O HTTPS é automático.

## 7. Deploy hook opcional

A integração Git já dispara o deploy. Se quiser um gatilho explícito no fim do
workflow:

1. Pages → Settings → Builds & deployments → **Deploy hooks** → Create.
2. Copie a URL.
3. No GitHub: Settings → Secrets and variables → Actions → New secret
   `CLOUDFLARE_DEPLOY_HOOK_URL`.
4. O workflow fará `POST` nessa URL após o push.

## 8. Limites relevantes (Free)

Consultado em 14/11/2026 na documentação oficial:

| Recurso | Limite Free |
| --- | --- |
| Builds | 500/mês; 1 concorrente; timeout 20 min |
| Arquivos por site | 20.000 |
| Tamanho por arquivo | 25 MiB |
| Projetos | 100 por conta |
| Bandwidth/requests estáticos | gratuitos e ilimitados (uso justo) |
| Functions | contam na cota de Workers: 100.000 req/dia |
| Header rules | 100 regras, 2.000 caracteres por linha |
| Redirects | 2.000 estáticos + 100 dinâmicos |

Este projeto tem **10 arquivos** em `public/` e o maior tem ~14 MB (CSV),
portanto está bem dentro dos limites.

## 9. Solução de problemas

| Sintoma | Causa provável | Solução |
| --- | --- | --- |
| 404 na raiz | `index.html` fora de `public/` | garantir `public/index.html` |
| Função não roda | `functions/` fora da raiz ou `_routes.json` incorreto | conferir estrutura |
| Imagens 502 | origem bloqueou o IP da Cloudflare | placeholder; opcional R2/cache próprio |
| JSON 404 | `public/data/` não commitado | rodar atualizador e commitar |
| Deploy antigo | cache do navegador/CDN | aguardar 5 min ou purgar cache |
| Build falha | build command preenchido | deixar vazio |
| CSV grande | >25 MiB | aumentar número de blocos / dividir CSV |

## 10. Rollback

- Pages → Deployments → escolha um deploy anterior → **Rollback**.
- No Git, reverta o commit de dados e faça push.
- O site continua servindo a versão anterior enquanto o novo deploy não
  termina.
