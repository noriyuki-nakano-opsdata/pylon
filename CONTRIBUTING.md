# Contributing to Pylon

Thank you for your interest in contributing to Pylon!

## Development Setup

```bash
git clone https://github.com/noriyuki-nakano-opsdata/pylon.git
cd pylon
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Pull Request Process

1. Fork and create a feature branch from `main`
2. Write tests for new functionality
3. Ensure all tests pass: `make test`
4. Follow conventional commits: `type(scope): description`
5. Submit PR with clear description

## Code Style

- Python: ruff (formatting + linting)
- TypeScript: eslint + prettier
- Max file length: 500 lines

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
