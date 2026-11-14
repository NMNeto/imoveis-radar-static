PYTHON ?= python3
VENV ?= .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

.PHONY: help instalar instalar-dev dados dados-offline simular testes validar servir formatar limpar-logs

help:
	@echo "Alvos disponíveis:"
	@echo "  make instalar       cria .venv e instala dependências de runtime"
	@echo "  make instalar-dev   instala também pytest"
	@echo "  make dados          atualização completa (Caixa + coletores + geo)"
	@echo "  make dados-offline  usa os CSVs existentes, sem rede"
	@echo "  make simular        dry-run completo"
	@echo "  make testes         pytest"
	@echo "  make validar        valida os JSONs publicados"
	@echo "  make servir         pré-visualiza em http://127.0.0.1:8080"
	@echo "  make limpar-logs    remove logs locais (não versionados)"

instalar:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install -q --upgrade pip
	$(PIP) install -q -r requirements.txt

instalar-dev: instalar
	$(PIP) install -q -r requirements-dev.txt

dados:
	$(PY) scripts/atualizar_imoveis.py

dados-offline:
	$(PY) scripts/atualizar_imoveis.py --skip-collect

simular:
	$(PY) scripts/atualizar_imoveis.py --dry-run

testes:
	$(PY) -m pytest -q

validar:
	$(PY) scripts/atualizar_imoveis.py --validate-only

servir:
	$(PY) scripts/dev_server.py --port 8080

limpar-logs:
	rm -rf data/logs/*
