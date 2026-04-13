# Contributing to Swarmline

Thank you for your interest in contributing to Swarmline!

## Development Setup

```bash
# Clone the repository
git clone https://github.com/fockus/swarmline.git
cd swarmline

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows

# Install with dev dependencies and all extras
pip install -e ".[dev,all]"

# Verify installation
python -c "import swarmline; print(swarmline.__version__)"
```

## Running Tests

```bash
# All offline tests (default)
pytest

# Include tests that require Claude Agent SDK
pytest -m "requires_claude_sdk or not requires_claude_sdk"

# Include live/network tests
pytest -m live

# With coverage
pytest --cov=swarmline --cov-report=term-missing

# Specific test file
pytest tests/unit/test_agent_tool.py -v
```

## Code Style

We use [Ruff](https://docs.astral.sh/ruff/) for linting and formatting:

```bash
# Check
ruff check src/ tests/
ruff format --check src/ tests/

# Auto-fix
ruff check --fix src/ tests/
ruff format src/ tests/
```

Type checking with [ty](https://docs.astral.sh/ty/):

```bash
ty check src/swarmline/
```

## Architecture Principles

- **Clean Architecture** — dependencies point inward: Infrastructure -> Application -> Domain
- **Protocol-first** — define `Protocol` interfaces before implementations
- **TDD** — write tests before implementation (Red -> Green -> Refactor)
- **SOLID** — SRP (<300 lines per module), ISP (<=5 methods per protocol), DIP (depend on abstractions)
- **Domain-agnostic** — swarmline must not contain any domain-specific logic (finance, medical, etc.)

## Pull Request Process

1. Fork the repository
2. Create a feature branch: `git checkout -b feat/my-feature`
3. Write tests first (TDD)
4. Implement the feature
5. Ensure all tests pass: `pytest`
6. Ensure code style: `ruff check && ruff format --check`
7. Submit a pull request with a clear description

### Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add new middleware for rate limiting
fix: handle empty tool parameters in @tool decorator
docs: update runtime switching guide
test: add integration tests for SQLite provider
refactor: extract common logic from runtime ports
```

## Optional Dependencies

Swarmline uses optional dependency groups. When adding features that require new packages:

1. Add the dependency to the appropriate extra in `pyproject.toml`
2. Use lazy imports (inside functions/methods) for optional packages
3. Never import optional packages at module top-level
4. Add a smoke test in `tests/unit/test_import_isolation.py`
5. Mark tests that require the extra with the appropriate marker:
   - `@pytest.mark.requires_claude_sdk`
   - `@pytest.mark.requires_anthropic`
   - `@pytest.mark.requires_langchain`
   - `@pytest.mark.live` (for network-dependent tests)

## Questions?

Open an issue on GitHub for questions, bug reports, or feature requests.
