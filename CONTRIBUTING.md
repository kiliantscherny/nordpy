# Contributing to nordpy

Thanks for your interest in contributing to nordpy. This guide will help you get set up and familiar with the project's workflow.

> [!NOTE]
> This is a hobby project and I'm still figuring out the best way to structure and manage it. Your feedback and contributions are welcome.

## Getting Started

### Prerequisites

- Python 3.10–3.13
- [uv](https://docs.astral.sh/uv/) package manager
- [prek](https://github.com/j178/prek) (pre-commit in Rust) — optional but recommended

### Setup

```bash
git clone https://github.com/kiliantscherny/nordpy.git
cd nordpy
uv sync --dev
```

### Install pre-commit hooks

```bash
prek install
```

This will run ruff, ty, and uv-lock checks automatically before each commit.

## Project Structure

```
src/nordpy/
├── app.py                  # Main Textual app and CLI entry point
├── auth.py                 # MitID/Signicat OIDC authentication
├── client.py               # Nordnet API client
├── export.py               # CSV, XLSX, and DuckDB exporters
├── http.py                 # HTTP session factory
├── models.py               # Pydantic models for API responses
├── session.py              # Session persistence (.nordnet_session.json)
├── screens/                # Textual screens (accounts, holdings, etc.)
├── services/               # Business logic (price history, charts)
├── styles/                 # Textual CSS
├── widgets/                # Reusable Textual widgets
└── BrowserClient/          # MitID browser client (vendored)

tests/
└── unit/                   # Unit tests
```

## Running Checks

```bash
# Run everything (tests on Python 3.10–3.13, lint, type check)
uv run tox

# Run tests only
uv run pytest

# Run tests with coverage
uv run pytest --cov=nordpy --cov-report=term-missing

# Lint
uv run ruff check .

# Type check
uv run ty check
```

## Commit Conventions

This project uses [Commitizen](https://commitizen-tools.github.io/commitizen/) with [Conventional Commits](https://www.conventionalcommits.org/). All commit messages should follow the format:

```
<type>(<scope>): <description>
```

**Types:**

| Type | Description | SemVer |
|------|-------------|--------|
| `fix` | A bug fix | PATCH |
| `feat` | A new feature | MINOR |
| `docs` | Documentation only changes | — |
| `style` | Formatting, whitespace, semicolons (no logic change) | — |
| `refactor` | Code change that neither fixes a bug nor adds a feature | — |
| `perf` | A code change that improves performance | — |
| `test` | Adding or correcting tests | — |
| `build` | Changes to build system or dependencies (uv, pip, docker) | — |
| `ci` | Changes to CI configuration files and scripts | — |

**Examples:**

```
feat(export): add DuckDB export format
fix(auth): handle relative redirect URLs in OIDC flow
docs: update README with pip install instructions
test(models): add coverage for MoneyAmount validation
```

You can use `cz commit` instead of `git commit` to get an interactive prompt that guides you through the format.

### Version Bumping

```bash
cz bump --increment MINOR   # 0.2.0 → 0.3.0
cz bump --increment PATCH   # 0.2.0 → 0.2.1
```

This updates the version in `pyproject.toml`, `src/nordpy/__init__.py`, and generates a changelog entry.

## Code Style

- **Linter:** [ruff](https://docs.astral.sh/ruff/) — runs automatically via pre-commit
- **Type checker:** [ty](https://docs.astral.sh/ty/) — runs automatically via pre-commit
- **Formatting:** ruff handles formatting; no need for a separate formatter
- Use `from __future__ import annotations` in all modules
- Use Pydantic models for API response validation
- Use `@work(thread=True)` for sync HTTP calls in Textual screens
- Use `self.app.call_from_thread()` to update the UI from worker threads

## Pull Requests

1. Create a feature branch from `main`
2. Make your changes
3. Ensure `uv run tox` passes
4. Open a pull request with a clear description of what changed and why

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
