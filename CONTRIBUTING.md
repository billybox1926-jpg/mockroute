# Contributing to mockroute

Thank you for your interest in contributing! Here are some guidelines.

## Development Setup

```bash
git clone https://github.com/billybox1926-jpg/mockroute.git
cd mockroute
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -e .
pip install pytest ruff pre-commit
pre-commit install
```

## Running Tests

```bash
pytest tests/ -v
```

## Linting and Formatting

```bash
ruff check mockroute.py tests/
ruff format mockroute.py tests/
```

## Pull Request Guidelines

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Add tests for new features
4. Ensure all tests pass (`pytest tests/ -v`)
5. Update documentation if needed
6. Submit a PR with a clear description

## Code Style

- Follow PEP 8
- Use type hints where appropriate
- Keep functions focused and small
- Add docstrings for public APIs

## Reporting Issues

Please use the GitHub issue tracker. Include:
- Steps to reproduce
- Expected behavior
- Actual behavior
- Python version and OS
