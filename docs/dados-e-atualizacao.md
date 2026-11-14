# Dados e atualização

## 1. Fontes e arquivos brutos

| Fonte | Arquivo canônico | Encoding | Coleta |
| --- | --- | --- | --- |
| Caixa | `data/raw/caixa/Lista_imoveis_geral.csv` | latin1, `;`, título antes do cabeçalho | HTTPS |
| Banco do Brasil | `data/raw/bb/imoveis_bb_geral.csv` | UTF-8 BOM, `;` | Playwright + detalhes HTTP |
| Santander | `data/raw/santander/santander_imoveis_geral.csv` | UTF-8 BOM, `;` | Playwright + API do portal |
| Itaú | `data/raw/itau/itau_imoveis_geral.csv` | UTF-8 BOM, `;` | Playwright (SPA) |

Colunas lógicas: `Nº do imóvel`, `UF`, `Cidade`, `Bairro`, `Endereço`,
`Preço`, `Valor de avaliação`, `Desconto`, `Financiamento`, `Descrição`,
`Modalidade de venda`, `Link de acesso`, `Imagem` (opcional).

## 2. Item publicado

Cada item em `public/data/imoveis-<hash>-NNN.json` contém:

| Campo | Tipo | Observação |
| --- | --- | --- |
| `id` | string | único; Caixa usa o ID bruto, demais `<fonte>:<id>` |
| `id_fonte` | string | ID bruto |
| `fonte` | string | `caixa`, `bb`, `santander`, `itau` |
| `fonte_nome` | string | nome de exibição |
| `uf`, `cidade`, `bairro`, `endereco` | string | localização |
| `preco` | number | preço pedido; `0` = oferta/sob consulta |
| `preco_label` | string/null | “Faça sua oferta” / “Sob consulta” |
| `valor_avaliacao` | number/null | avaliação da fonte |
| `valor_ajustado` | number/null | avaliação ou override manual |
| `ajustado` | bool | override aplicado |
| `sem_avaliacao` | bool | não há valor para calcular desconto |
| `sem_preco` | bool | preço zero/sob consulta |
| `desconto` | number/null | % |
| `lucro` | number/null | R$ |
| `lucro_pct` | number/null | % |
| `financiamento` | string | `Sim`/`Não`/vazio |
| `descricao` | string | texto da fonte |
| `modalidade` | string | leilão/venda direta/etc. |
| `link` | string | URL da oferta |
| `imagem` | string/null | URL da imagem |
| `arquivo` | string | CSV de origem |
| `excluido` | bool | regra de exclusão aplicada |
| `motivo_exclusao` | string/null | motivo legível |
| `lat`, `lng` | number/null | coordenadas aproximadas |
| `geo_precisao` | `bairro`/`cidade`/`estado`/null | precisão |
| `geo_fonte` | string/null | `municipios`, `estados`, `nominatim`, `photon` |
| `primeira_visao` | ISO string | primeira vez visto pelo robô |
| `atualizado_em` | ISO string | última mudança de conteúdo |

Nenhum campo do projeto original foi descartado.

## 3. Fórmulas

```text
desconto   = (valor_ajustado - preco) / valor_ajustado * 100
fator      = 1 se modalidade ∈ {VENDA ONLINE, VENDA DIRETA ONLINE}
             senão fator_preco (padrão 1.05)
custo_fixo = custo_fixo (modo fixo)
             ou valor_ajustado * custo_fixo / 100 (modo percentual)
lucro      = (valor_ajustado - valor_ajustado * taxa_venda - custo_fixo)
             - preco * fator
lucro_pct  = lucro / valor_ajustado * 100
```

`taxa_venda=0.06`, `custo_fixo=40000`, `custo_fixo_modo=fixo`,
`fator_preco=1.05` por padrão. Valores nulos nunca são inventados.

## 4. Fluxo de atualização

```text
1. coleta por fonte em diretório temporário
2. validação: existe? cabeçalho? linhas mínimas? queda > min_rows_ratio?
3. se falhou: mantém CSV anterior e inclui os itens anteriores no dataset
4. constrói itens das fontes que responderam
5. deduplica por id (última ocorrência vence)
6. geocodifica locais novos (se habilitado)
7. aplica exclusões e valores manuais
8. compara com a versão anterior:
   - novo → primeira_visao = atualizado_em = agora
   - igual → preserva timestamps
   - alterado → atualizado_em = agora
   - ausente em fonte bem-sucedida → histórico de removidos
9. valida todos os itens
10. publica blocos + auxiliares + manifest (manifest por último)
11. grava histórico e resumo somente se mudou
```

### Falha de fonte

Se o portal bloquear, retornar HTML/CAPTCHA, estourar timeout ou entregar
menos que `min_rows_ratio` da coleta anterior:

- o CSV anterior daquela fonte permanece;
- os itens anteriores dela entram no dataset (não são tratados como removidos);
- o status da fonte fica com `last_error`;
- as outras fontes seguem normalmente.

Se **nenhuma** fonte responder e não houver dados anteriores, o script sai com
código 2 e não publica.

### Idempotência

O `manifest.json` guarda três hashes: `data_sha256` (itens, sem timestamps
voláteis), `meta_sha256` (facetas/config resumida) e `config_sha256`
(configuração pública). O `sha256` do manifesto combina os três. Assim:

- se só os itens mudam, os blocos são regravados;
- se só a configuração/meta muda, os blocos não são renomeados nem regravados,
  mas `config.json`/`meta.json`/manifesto são atualizados;
- se nada muda, nenhum JSON é regravado.

`ultima_atualizacao.json` também só muda quando os dados mudam. Executar duas
vezes com a mesma origem não produz alterações.

### Removidos

`data/history/removidos.json` guarda um snapshot enxuto dos itens que
desapareceram de uma fonte que respondeu com sucesso, com `removido_em` e
motivo. Se o item reaparece, sai do histórico. Entradas mais antigas que
`--history-days` (padrão 365) são podadas.

## 5. Comandos

```bash
# Atualização completa
python scripts/atualizar_imoveis.py

# Sem rede, usando os CSVs já existentes
python scripts/atualizar_imoveis.py --skip-collect

# Simulação completa (coleta, calcula, compara; não grava)
python scripts/atualizar_imoveis.py --dry-run

# Sem geocodificação
python scripts/atualizar_imoveis.py --no-geocode

# Só uma fonte
python scripts/atualizar_imoveis.py --sources caixa

# Forçar regravação
python scripts/atualizar_imoveis.py --force-publish

# Validar JSON publicado
python scripts/atualizar_imoveis.py --validate-only
```

## 6. Variáveis de ambiente

| Variável | Padrão | Uso |
| --- | --- | --- |
| `IMOVEIS_PROJECT_ROOT` | raiz do repo | diretório do projeto |
| `IMOVEIS_DATA_DIR` | `<root>/data` | dados brutos/config/cache |
| `IMOVEIS_PUBLIC_DIR` | `<root>/public` | saída publicada |
| `IMOVEIS_ORIGINAL_DIR` | vazio | trava de isolamento (opcional) |
| `IMOVEIS_CAIXA_URL` | URL oficial | override da origem Caixa |
| `IMOVEIS_HTTP_TIMEOUT` | `60` | timeout HTTP (s) |
| `IMOVEIS_HTTP_RETRIES` | `3` | tentativas HTTP |
| `IMOVEIS_COLLECTOR_TIMEOUT` | `1800` | timeout por coletor (s) |
| `IMOVEIS_MIN_ROWS_RATIO` | `0.5` | queda máxima aceitável por fonte |
| `IMOVEIS_MIN_ROWS_CAIXA/BB/SANTANDER/ITAU` | ver código | mínimo absoluto por fonte |
| `IMOVEIS_MIN_BYTES_CAIXA` | `100000` | sanidade do download da Caixa |
| `IMOVEIS_MAX_ITEMS_POR_ARQUIVO` | `6000` | itens por bloco JSON |
| `IMOVEIS_GEOCODE_MAX` | `200` | novas localidades por execução |
| `IMOVEIS_GEOCODE_INTERVAL` | `1.5` | intervalo entre requisições (s) |
| `IMOVEIS_GEOCODE_USER_AGENT` | projeto | User-Agent exigido pelas APIs |
| `IMOVEIS_HISTORY_DAYS` | `365` | retenção do histórico |

Nenhum token/senha é necessário para coletar. O único secret opcional é
`CLOUDFLARE_DEPLOY_HOOK_URL`.

## 7. Geocodificação

- Estados/cidades: sementes offline de `data/seeds/`.
- Bairros: Nominatim; se limitar (429/503), Photon; se ambos limitarem, para e
  mantém o cache.
- Falha de rede não vira “não encontrado”; apenas erro, para tentar de novo.
- “Não encontrado” fica em `misses` por 30 dias.
- O jitter determinístico por ID separa imóveis do mesmo bairro.
- O script limita a `IMOVEIS_GEOCODE_MAX` por execução para respeitar as
  políticas de uso.

## 8. CSV combinado

`public/data/busca_imoveis.csv` é gerado com as mesmas colunas do `/api/csv`
original (Fonte, ID, ID na fonte, localização, preços, desconto, lucro,
financiamento, modalidade, descrição, link, imagem, coordenadas, exclusão).
É UTF-8 com BOM e separador `;`, ideal para Excel/LibreOffice.

## 9. Configuração

- `data/config/settings.json`
- `data/config/exclude_ids.txt`
- `data/config/exclude_locations.csv`
- `data/config/market_value.csv`

Editar pela caixa **Configurações** do site (local) ou diretamente no
repositório. Para exportar do navegador e aplicar ao repositório:

```bash
python scripts/importar_config.py config-local.json
```

O script valida o JSON e grava apenas em `data/config/`.
