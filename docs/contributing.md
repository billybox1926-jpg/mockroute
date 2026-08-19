# Contributing

## Development Setup

```bash
git clone https://github.com/billybox1926-jpg/mockroute.git
cd mockroute
uv venv
uv pip install pytest mkdocs-material
```

## Running Tests

```bash
uv run pytest tests/ -v
```

## Linting

```bash
python -m ruff check mockroute.py tests/test_mockroute.py
python -m ruff format --check mockroute.py tests/test_mockroute.py
```

## Building Docs Locally

```bash
mkdocs serve
# or
mkdocs build
```

## Pull Request Guidelines

1. Fork the repository
2. Create a feature branch
3. Add tests for new features
4. Ensure all tests pass
5. Update documentation if needed
6. Submit a PR with a clear description

## Code Style

- Follow PEP 8
- Use type hints where appropriate
- Keep functions focused and small
- Add docstrings for public APIs

## Release Process

1. Update version in `pyproject.toml` and `mockroute.py`
2. Update `CHANGELOG.md` (if present)
3. Create a git tag: `git tag vX.Y.Z`
4. Push to main
5. Create a GitHub Release with notes
