# Validação dos dados

## 1. Equivalência com o projeto original

Foi gerado o dataset estático a partir dos mesmos quatro CSVs usados pelo
projeto original e comparado item a item com
`caixa_data.load_dataset()`.

Resultado (14/11/2026):

```text
itens no original .....: 26.317
itens no estático .....: 26.317
somente no original ...: 0
somente no estático ...: 0
campos divergentes ....: 0
```

A comparação ignorou apenas `primeira_visao` e `atualizado_em`, campos novos
de auditoria que o original não possui. Todos os demais campos — incluindo
`id`, localização, preços, desconto, lucro, exclusão, imagem, link,
coordenadas e precisão geográfica — eram idênticos **com a configuração
original**.

Depois, a pedido, a configuração pública foi limpa: cada lista
(`exclude_ids`, `exclude_locations`, `market_value`) ficou com **um exemplo
sem correspondência real**. Isso altera intencionalmente apenas os campos
derivados de exclusão/valor ajustado: agora há **0 imóveis excluídos** e
**0 overrides de valor**. Os campos de origem continuam idênticos e o total
segue em 26.317.

Script de comparação usado (executado fora do projeto original, com
`PYTHONDONTWRITEBYTECODE=1`):

```python
import sys, json, glob
sys.path.insert(0, "/home/nmneto/github/imoveis-radar/web")
import caixa_data as cd

orig = cd.load_dataset("/home/nmneto/github/imoveis-radar/web/data")["items"]
ours = []
for path in sorted(glob.glob("public/data/imoveis-*.json")):
    ours.extend(json.load(open(path, encoding="utf-8")))

O = {item["id"]: item for item in orig}
N = {item["id"]: item for item in ours}
assert set(O) == set(N)
for key in O:
    for field in set(O[key]) | set(N[key]):
        if field in ("primeira_visao", "atualizado_em"):
            continue
        assert O[key].get(field) == N[key].get(field), (key, field)
print("OK", len(ours))
```

## 2. Composição do dataset

| Fonte | Total | Excluídos | Com imagem | Com coordenadas |
| --- | ---: | ---: | ---: | ---: |
| Caixa | 23.782 | 0 | 23.782 | 23.782 |
| Banco do Brasil | 892 | 0 | 888 | 892 |
| Santander | 1.300 | 0 | 1.296 | 1.300 |
| Itaú | 343 | 0 | 309 | 343 |
| **Total** | **26.317** | **0** | **26.275** | **26.317** |

Na configuração original havia 7.160 excluídos (171 IDs, 141 locais e 153
valores manuais). A versão pública agora mostra um exemplo em cada lista, sem
correspondência real, para servir de modelo de uso sem esconder imóveis.

Precisão geográfica: 845 bairro, 25.370 cidade, 102 estado.
UFs: 27. Modalidades: 9.

## 3. Validação estrutural

O comando abaixo valida o manifesto, os blocos, a contagem, IDs únicos,
campos obrigatórios, tipos numéricos, URLs, coordenadas e limites de tamanho:

```bash
python scripts/atualizar_imoveis.py --validate-only
```

Saída esperada:

```text
JSON válido: 26317 imóveis, 5 bloco(s), 10 arquivo(s); maior arquivo 6.0 MiB
```

Regras aplicadas:

- `id`, `id_fonte`, `fonte`, `uf`, `cidade`, `modalidade` não vazios;
- `fonte` ∈ {caixa, bb, santander, itau};
- nenhum ID duplicado;
- números finitos (sem NaN/Infinity);
- `lat` em [-90, 90], `lng` em [-180, 180];
- `link`/`imagem` em http(s) quando presentes;
- `manifest.total` = soma dos blocos = `meta.total_properties`;
- cada arquivo ≤ 25 MiB; total de arquivos ≤ 20.000.

## 4. Idempotência

Teste automatizado (`tests/test_publish.py`):

1. publica o dataset;
2. publica novamente o mesmo conteúdo;
3. verifica `changed == False` e `files_written == []`.

O hash SHA-256 dos itens (sem timestamps voláteis) é a chave. Se a origem não
mudou, os arquivos não são regravados. `ultima_atualizacao.json` só é
atualizado quando o hash muda.

## 5. Preservação em falha

Testes automatizados cobrem:

- CAPTCHA/HTML da Caixa: o CSV anterior permanece e o status registra erro;
- coletor que não produz CSV: a versão anterior da fonte é mantida;
- queda de linhas abaixo de `min_rows_ratio`: a fonte é considerada suspeita
  e a versão anterior prevalece;
- fonte que falha não gera itens removidos (o histórico só recebe ausências de
  fontes que responderam com sucesso);
- gravação atômica: arquivo temporário + `os.replace`;
- manifesto escrito por último e blocos com nome versionado por hash.

## 6. Testes automatizados

```bash
python -m pytest -q
```

Cobertura atual: **38 testes**, todos passando. Incluem:

- `test_text.py` — dinheiro brasileiro, acentos, normalização;
- `test_csv_sources.py` — cabeçalho da Caixa, encoding, colunas, queda;
- `test_model.py` — pontuação, overrides, exclusões, filtros, ordenação;
- `test_geo.py` — sementes, fallback bairro→cidade→estado, jitter, misses;
- `test_history.py` — novos/alterados/removidos, histórico, poda;
- `test_collect.py` — modo offline, download atômico, CAPTCHA;
- `test_publish.py` — publicação, idempotência, chunks versionados, dry-run;
- `test_cli.py` — fluxo completo e `--validate-only`;
- `test_importar_config.py` — importação e dry-run;
- `test_security.py` — cabeçalhos, CSP sem `unsafe-eval/inline`, ausência de
  source maps, CORS sem curinga, handlers inline e segredos óbvios.

## 7. Tamanhos e limites

| Arquivo | Tamanho |
| --- | ---: |
| 5 blocos JSON | 2,9–6,2 MB cada |
| `busca_imoveis.csv` | ~14,3 MB |
| `meta.json` | ~205 KB |
| `config.json` | ~16 KB |
| total `public/data` | ~41 MB |

Todos abaixo de 25 MiB por arquivo e muito abaixo de 20.000 arquivos.

## 8. Dados ausentes

Nenhum dado ausente foi inventado:

- BB sem avaliação mantém `valor_avaliacao=null`, `desconto=null`,
  `lucro=null`;
- Itaú sem preço mantém `preco=0` e `preco_label="Sob consulta"`;
- bairro ausente é preservado vazio;
- geocodificação sem resultado não vira coordenada falsa; o item cai para
  cidade/estado ou fica sem ponto;
- falha de rede não vira "não encontrado".

## 9. Como reproduzir

```bash
# 1) reconstruir a partir dos CSVs versionados
python scripts/atualizar_imoveis.py --skip-collect --no-geocode

# 2) validar
python scripts/atualizar_imoveis.py --validate-only

# 3) testar
python -m pytest -q
```
