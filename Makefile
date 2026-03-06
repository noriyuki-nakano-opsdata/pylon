.PHONY: install test lint fmt clean

install:
	pip install -e ".[dev]"
	cd src/gateway && npm install

test:
	python -m pytest tests/ -v
	cd src/gateway && npm test

lint:
	ruff check src/ tests/
	cd src/gateway && npx eslint .

fmt:
	ruff format src/ tests/
	cd src/gateway && npx prettier --write .

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	rm -rf dist/ build/ *.egg-info/
