.PHONY: all venv install test test-integration test-all lint format typecheck clean build

PYTHON ?= python3
VENV ?= .venv
VENV_PYTHON := $(VENV)/bin/python
ACTIVE_PYTHON := $(if $(wildcard $(VENV_PYTHON)),$(VENV_PYTHON),$(PYTHON))
PIP := $(ACTIVE_PYTHON) -m pip
PYTEST := $(ACTIVE_PYTHON) -m pytest
RUFF := $(ACTIVE_PYTHON) -m ruff
MYPY := $(ACTIVE_PYTHON) -m mypy
BUILD := $(ACTIVE_PYTHON) -m build

all: lint test

venv:
	$(PYTHON) -m venv $(VENV)
	$(VENV_PYTHON) -m pip install --upgrade pip

install:
	$(PIP) install -e ".[dev]"

test:
	$(PYTEST) tests/unit/ -v

test-integration:
	$(PYTEST) tests/integration/ -v

test-all:
	$(PYTEST) tests/ -v

lint:
	$(RUFF) check src/ tests/

format:
	$(RUFF) format src/ tests/

typecheck:
	$(MYPY) src/pylon/ --ignore-missing-imports

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache dist/ build/ *.egg-info

build: clean
	$(BUILD)
