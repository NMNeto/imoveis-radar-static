# Checklist de entrega

## 1. Relatório técnico do site original

- [docs/relatorio-tecnico-original.md](relatorio-tecnico-original.md)
- Rotas, componentes, dados, origem, atualização, filtros, volume e riscos.

## 2. Projeto estático completo

- `public/index.html`, `public/static/*`, `public/data/*`
- `functions/api/image.js` (proxy de imagens)
- `public/_headers`, `public/_routes.json`, `public/robots.txt`
- Modal **Sugestões** integrado ao Google Forms
  (`https://forms.gle/HnciJsM5Xzto8ATd6`), com fallback para nova aba.

## 3. Novo diretório isolado

- `/home/nmneto/github/imoveis-radar-static` (irmão do original, fora da
  árvore dele; sem symlinks).
- Travas em `scripts/imoveis_radar/safety.py`.

## 4. Novo repositório Git

- <https://github.com/NMNeto/imoveis-radar-static>
- Histórico novo, sem remote do original.
- Branch `main`, repositório público.

## 5. Script Python de atualização

- `scripts/atualizar_imoveis.py` (entrada)
- `scripts/imoveis_radar/` (coleta, modelo, geo, publicação, CLI)
- `scripts/imoveis_radar/collectors/` (BB, Santander, Itaú)
- Comandos: `--dry-run`, `--skip-collect`, `--validate-only`,
  `--force-publish`, `--no-geocode`, `--sources`, `--json`.

## 6. Arquivos JSON gerados

- `public/data/manifest.json`
- `public/data/imoveis-<hash>-000.json` … `-004.json`
- `public/data/meta.json`
- `public/data/estatisticas.json`
- `public/data/ultima_atualizacao.json`
- `public/data/config.json`
- `public/data/busca_imoveis.csv`

## 7. Workflow GitHub Actions

- `.github/workflows/atualizar-imoveis.yml` (cron + manual + commit + hook)
- `.github/workflows/validar.yml` (push/PR)
- Validação real: run `Validar projeto` passou; run manual de atualização
  em modo seguro (`dry_run=true`, `skip_collect=true`, `no_geocode=true`)
  passou todos os steps, incluindo testes e `--validate-only`.

## 8. Testes automatizados

- `tests/` — 38 testes.
- `python -m pytest -q` → todos passando.

## 9. Configuração Cloudflare Pages

- Instruções: [cloudflare-pages.md](cloudflare-pages.md)
- Build command: vazio; output: `public`; Functions: `functions/`.
- **Pendente:** criação do projeto no Cloudflare Pages. O ambiente desta
  execução não tem token/credencial Cloudflare. Para concluir, conecte o
  repositório pelo dashboard (Pages → Connect to Git) ou forneça um API token
  com permissão `Pages:Edit` + Account ID.

## 10. README

- [README.md](../README.md) — visão geral, comandos, deploy, configuração,
  limitações.

## 11. Relatório de comparação visual

- [comparacao-visual.md](comparacao-visual.md)
- Screenshots em `docs/screenshots/`.
- 99,58% de pixels idênticos no desktop; 98,25% no mobile **com a mesma
  configuração** (diferenças: botão “Atualizar agora” substituído por “Aviso”,
  status e timing de tiles).
- Depois da limpeza das listas, o site atual mostra 17.876 imóveis em vez de
  11.882; a diferença de conteúdo é intencional e está documentada.
- Aviso de primeira visita documentado em
  [aviso-e-privacidade.md](aviso-e-privacidade.md), com screenshots próprios.

## 12. Relatório de validação dos dados

- [validacao-dados.md](validacao-dados.md)
- 26.317 itens; 0 divergências de campo em relação ao original na comparação
  inicial; depois a configuração pública foi limpa para um exemplo por lista,
  resultando em 0 exclusões e 0 overrides intencionais. Idempotência e falhas
  cobertas por testes.

## 13. Comprovação de integridade do original

- [integridade-original.md](integridade-original.md)
- Baseline `docs/integridade-original.sha256` (131 arquivos).
- Verificação final: 131/131 SUCESSO; `git status` vazio; HEAD
  `67490efaae7c3df9b5875ec80ada9fd7ef0f14ba`.

## 14. Auditoria de segurança

- [security-audit.md](security-audit.md)
- CSP restritiva, headers, CORS, source maps, segredos, XSS e dependências.

## 15. Estimativa de franquias gratuitas

- [franquias-gratuitas.md](franquias-gratuitas.md)
- Pages, Workers/Functions, D1, KV, R2, Turnstile e GitHub Actions, com
  limites oficiais consultados em 14/11/2026 e estimativas de uso.

## Próximos passos

1. Conectar o repositório ao Cloudflare Pages (dashboard ou token).
2. Validar o endereço `*.pages.dev` com o checklist de
   [cloudflare-pages.md](cloudflare-pages.md).
3. Opcional: configurar `CLOUDFLARE_DEPLOY_HOOK_URL`.
4. Opcional: disparar uma atualização real em Actions → Atualizar imóveis.
5. Só depois de validar, configurar domínio personalizado/DNS.
