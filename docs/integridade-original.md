# Comprovação de integridade do projeto original

## 1. Regra aplicada

O projeto original em `/home/nmneto/github/imoveis-radar` foi tratado como
**somente leitura**:

- nenhum arquivo foi editado;
- nenhum banco/configuração/dependência foi alterado;
- nenhum commit/push foi feito nele;
- nenhum servidor/DNS foi tocado;
- o diretório original nunca foi usado como `cwd` do atualizador;
- nenhum arquivo temporário/log/cache foi criado nele;
- nenhum link simbólico foi usado entre os projetos.

O novo projeto está em `/home/nmneto/github/imoveis-radar-static`, irmão do
original, fora da árvore dele.

## 2. Baseline de hashes

Antes do desenvolvimento foi gerado um baseline SHA-256 de **131 arquivos** do
original, excluindo apenas:

- `.git/`;
- `web/.venv/`;
- diretórios `__pycache__/`.

O baseline está versionado em
[`docs/integridade-original.sha256`](integridade-original.sha256).

## 3. Verificação final

Comando executado no diretório original:

```bash
cd /home/nmneto/github/imoveis-radar
sha256sum -c /caminho/para/original-files.sha256
```

Resultado:

```text
131/131 arquivos: SUCESSO
exit code: 0
```

Também foram verificados:

```text
git status --porcelain   → vazio
git rev-parse HEAD       → 67490efaae7c3df9b5875ec80ada9fd7ef0f14ba
branch                   → main
```

O arquivo de dados original manteve tamanho e data:

```text
web/data/Lista_imoveis_geral.csv   8.650.868 bytes   2026-11-13 14:54:52 -0300
web/app.py                        22.877 bytes      2026-11-13 22:43:03 -0300
README.md                          6.602 bytes      2026-11-13 22:43:03 -0300
```

Nenhum `last_update.json`, log ou cache novo foi criado no original.

## 4. Como reverificar

```bash
cd /home/nmneto/github/imoveis-radar
sha256sum -c /home/nmneto/github/imoveis-radar-static/docs/integridade-original.sha256
git status --porcelain
git rev-parse HEAD
```

O comando deve terminar com código 0, todas as linhas `SUCESSO`/`OK` e
`git status` vazio.

## 5. Escopo do baseline

O baseline cobre código, documentação, configurações, CSVs, sementes e cache
de geocode do original. Ficaram de fora, de forma intencional:

- `.git/` (histórico; verificado separadamente por `git status` e HEAD);
- `web/.venv/` (ambiente virtual, não é código do projeto);
- `__pycache__/` (artefatos Python que podem ser recriados).

Se o seu ambiente usar outra exclusão, ajuste o comando de geração do
baseline, mas mantenha a mesma filosofia: comparar todos os arquivos de
trabalho e ignorar apenas artefatos reproduzíveis.

## 6. Observação sobre a cópia de análise

Para rodar o site original e tirar screenshots, o código e os dados foram
copiados para `/tmp/opencode/original-preview`. O Flask foi iniciado com
`DISABLE_BACKGROUND_JOBS=1`, `RUN_COLLECTORS=0` e `DATA_DIR` apontando para a
cópia. Portanto, qualquer escrita de runtime ocorreu **na cópia temporária**,
nunca no original.
