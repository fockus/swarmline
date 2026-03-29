"""cognitia init — scaffold a new Cognitia agent project.

Usage:
    cognitia init my-agent
    cognitia init my-agent --runtime claude --memory sqlite
    cognitia init my-agent --full
    cognitia init my-agent --output ./projects
    cognitia init my-agent --force
"""

from __future__ import annotations

import shutil
from pathlib import Path
from string import Template

import click

# ---------------------------------------------------------------------------
# Template strings (stdlib string.Template — no external deps)
# ---------------------------------------------------------------------------

_AGENT_PY = Template(
    '''\
"""$project_name — Cognitia AI Agent.

Quick start:
    python agent.py                         # interactive chat
    python agent.py "What is the capital of France?"  # one-shot query
"""

from __future__ import annotations

import asyncio
import sys

from cognitia.agent import Agent
from cognitia.bootstrap import CognitiaStack

# Build the agent from config.yaml
stack = CognitiaStack.from_config("config.yaml")
agent: Agent = stack.agent


async def main() -> None:
    if len(sys.argv) > 1:
        prompt = " ".join(sys.argv[1:])
        result = await agent.query(prompt)
        if result.ok:
            print(result.text)
        else:
            print(f"Error: {result.error}", file=sys.stderr)
            sys.exit(1)
    else:
        print("$project_name ready. Type your message (Ctrl-C to quit).")
        while True:
            try:
                user_input = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\\nBye!")
                break
            if not user_input:
                continue
            result = await agent.query(user_input)
            if result.ok:
                print(f"Agent: {result.text}")
            else:
                print(f"Error: {result.error}", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
'''
)

_CONFIG_YAML_MINIMAL = Template(
    """\
# Cognitia Agent Configuration — $project_name
# Docs: https://cognitia.readthedocs.io/

name: $project_name
description: "AI agent built with Cognitia"

runtime:
  type: $runtime

memory:
  enabled: $memory_enabled
  backend: $memory_backend
"""
)

_CONFIG_YAML_FULL = Template(
    """\
# Cognitia Agent Configuration — $project_name (full)
# Docs: https://cognitia.readthedocs.io/

name: $project_name
description: "AI agent built with Cognitia"

runtime:
  type: $runtime
  model: auto         # resolved via COGNITIA_MODEL or runtime default
  max_tokens: 4096

memory:
  enabled: true
  backend: sqlite
  path: ./$project_slug.db

tools:
  enabled: true
  builtin:
    - web_search
    - code_sandbox
    - thinking

planning:
  enabled: true
  max_steps: 20

guardrails:
  max_tokens_per_turn: 8192
  max_cost_usd: 1.0

observability:
  log_level: INFO
  structured: true
"""
)

_TEST_AGENT_PY = Template(
    '''\
"""Tests for $project_name agent."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from cognitia.agent import Agent
from cognitia.agent.result import Result


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_agent() -> MagicMock:
    """Return a mock agent that returns a canned response."""
    agent = MagicMock(spec=Agent)
    agent.query = AsyncMock(return_value=Result(text="Hello from agent"))
    return agent


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAgentBasic:

    async def test_agent_returns_text_response(self, mock_agent: MagicMock) -> None:
        result = await mock_agent.query("Hello")
        assert result.ok
        assert isinstance(result.text, str)

    async def test_agent_error_propagates(self, mock_agent: MagicMock) -> None:
        mock_agent.query = AsyncMock(return_value=Result(text="", error="LLM timeout"))
        result = await mock_agent.query("Hello")
        assert not result.ok
        assert result.error == "LLM timeout"
'''
)

_ENV_EXAMPLE = Template(
    """\
# Environment variables for $project_name
# Copy to .env and fill in your API keys

# LLM Provider (pick one)
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GOOGLE_API_KEY=...

# Optional: override default model
# COGNITIA_MODEL=claude-3-5-sonnet-latest

# Memory (only needed for sqlite backend)
# COGNITIA_DB_PATH=./$project_slug.db
"""
)

_PYPROJECT_TOML = Template(
    """\
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "$project_slug"
version = "0.1.0"
description = "AI agent built with Cognitia"
requires-python = ">=3.10"
dependencies = [
    "cognitia>=1.0",
$extra_deps
]

[project.scripts]
$project_slug = "$project_slug.agent:main"

[tool.pytest.ini_options]
asyncio_mode = "auto"

[tool.ruff]
line-length = 100
"""
)

_README_MD = Template(
    """\
# $project_name

AI agent built with [Cognitia](https://cognitia.readthedocs.io/).

## Quick Start

```bash
# Install dependencies
pip install -e .

# Set your API key
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY (or OPENAI_API_KEY)

# Run the agent
python agent.py "Hello!"
```

## Configuration

Edit `config.yaml` to adjust:
- **runtime**: `thin` (built-in) | `claude` (Claude Agent SDK) | `deepagents` (LangChain)
- **memory**: `inmemory` (ephemeral) | `sqlite` (persistent)
- **tools**: enable/disable built-in tools

## Project Structure

```
$project_name/
├── agent.py          ← main entry point
├── config.yaml       ← agent configuration
├── tests/
│   └── test_agent.py ← starter tests
├── .env.example      ← API key template
└── pyproject.toml    ← project metadata
```

## Running Tests

```bash
pip install pytest pytest-asyncio
pytest tests/ -v
```

## Docs

- [Cognitia Documentation](https://cognitia.readthedocs.io/)
- [Examples](https://cognitia.readthedocs.io/examples/)
"""
)

_DOCKERFILE = Template(
    """\
# syntax=docker/dockerfile:1
FROM python:3.11-slim AS builder

WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

FROM python:3.11-slim AS runtime
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY . .

ENV PYTHONUNBUFFERED=1

CMD ["python", "agent.py"]
"""
)

_DOCKER_COMPOSE_YML = Template(
    """\
version: "3.9"

services:
  agent:
    build: .
    env_file: .env
    volumes:
      - ./data:/app/data
    environment:
      - COGNITIA_DB_PATH=/app/data/$project_slug.db
    restart: unless-stopped
"""
)

_SKILLS_README = Template(
    """\
# Skills

Place MCP skill YAML files here.

Example: `web_search.yaml`

```yaml
name: web_search
description: Search the web for current information
server:
  command: npx
  args: ["-y", "@modelcontextprotocol/server-brave-search"]
  env:
    BRAVE_API_KEY: "$$BRAVE_API_KEY"
```

See: https://cognitia.readthedocs.io/skills/
"""
)


# ---------------------------------------------------------------------------
# Scaffolding logic
# ---------------------------------------------------------------------------


def _slugify(name: str) -> str:
    """Convert project name to Python-friendly slug."""
    return name.replace("-", "_").replace(" ", "_").lower()


def _render(template: Template, **kwargs: str) -> str:
    return template.substitute(**kwargs)


def _scaffold_project(
    project_dir: Path,
    project_name: str,
    runtime: str,
    memory: str,
    full: bool,
) -> None:
    """Create all project files in *project_dir*."""
    project_slug = _slugify(project_name)

    # Determine memory config values
    if full:
        memory_effective = "sqlite"
        memory_enabled = "true"
    elif memory == "inmemory":
        memory_effective = "inmemory"
        memory_enabled = "false"
    else:
        memory_effective = memory
        memory_enabled = "true"

    # Extra pyproject deps based on options
    extra_deps: list[str] = []
    if runtime == "claude":
        extra_deps.append('    "cognitia[claude]",')
    elif runtime == "deepagents":
        extra_deps.append('    "cognitia[deepagents]",')
    if memory_effective == "sqlite":
        extra_deps.append('    "cognitia[sqlite]",')
    extra_deps_str = "\n".join(extra_deps)

    tpl_vars = dict(
        project_name=project_name,
        project_slug=project_slug,
        runtime=runtime,
        memory_backend=memory_effective,
        memory_enabled=memory_enabled,
        extra_deps=extra_deps_str,
    )

    # core files
    project_dir.mkdir(parents=True, exist_ok=True)

    (project_dir / "agent.py").write_text(_render(_AGENT_PY, **tpl_vars))

    if full:
        (project_dir / "config.yaml").write_text(_render(_CONFIG_YAML_FULL, **tpl_vars))
    else:
        (project_dir / "config.yaml").write_text(_render(_CONFIG_YAML_MINIMAL, **tpl_vars))

    (project_dir / ".env.example").write_text(_render(_ENV_EXAMPLE, **tpl_vars))
    (project_dir / "pyproject.toml").write_text(_render(_PYPROJECT_TOML, **tpl_vars))
    (project_dir / "README.md").write_text(_render(_README_MD, **tpl_vars))

    # tests/
    tests_dir = project_dir / "tests"
    tests_dir.mkdir(exist_ok=True)
    (tests_dir / "__init__.py").write_text("")
    (tests_dir / "test_agent.py").write_text(_render(_TEST_AGENT_PY, **tpl_vars))

    # full-mode extras
    if full:
        (project_dir / "Dockerfile").write_text(_render(_DOCKERFILE, **tpl_vars))
        (project_dir / "docker-compose.yml").write_text(
            _render(_DOCKER_COMPOSE_YML, **tpl_vars)
        )
        skills_dir = project_dir / "skills"
        skills_dir.mkdir(exist_ok=True)
        (skills_dir / "README.md").write_text(_render(_SKILLS_README, **tpl_vars))


# ---------------------------------------------------------------------------
# Click command
# ---------------------------------------------------------------------------


@click.command("init")
@click.argument("name")
@click.option(
    "--runtime",
    type=click.Choice(["thin", "claude", "deepagents"]),
    default="thin",
    show_default=True,
    help="Agent runtime engine",
)
@click.option(
    "--memory",
    type=click.Choice(["inmemory", "sqlite"]),
    default="inmemory",
    show_default=True,
    help="Memory backend",
)
@click.option(
    "--full",
    is_flag=True,
    default=False,
    help="Enable all features: tools, planning, sqlite, Docker",
)
@click.option(
    "--output",
    "-o",
    default=None,
    type=click.Path(file_okay=False, resolve_path=True),
    help="Parent directory for the new project (default: cwd)",
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Overwrite existing directory",
)
def init_command(
    name: str,
    runtime: str,
    memory: str,
    full: bool,
    output: str | None,
    force: bool,
) -> None:
    """Scaffold a new Cognitia agent project.

    NAME is the project directory name (e.g. my-agent).

    Examples:

    \b
        cognitia init my-agent
        cognitia init my-agent --runtime claude --memory sqlite
        cognitia init my-agent --full
    """
    base_dir = Path(output) if output else Path.cwd()
    project_dir = base_dir / name

    if project_dir.exists():
        if not force:
            raise click.ClickException(
                f"Directory '{project_dir}' already exists. "
                "Use --force to overwrite."
            )
        shutil.rmtree(project_dir)

    click.echo(f"Creating project '{name}'...")
    _scaffold_project(
        project_dir=project_dir,
        project_name=name,
        runtime=runtime,
        memory=memory,
        full=full,
    )

    # Summary
    click.echo(click.style(f"\n✓ Project '{name}' created at {project_dir}", fg="green"))
    click.echo("\nNext steps:")
    click.echo(f"  cd {name}")
    click.echo("  cp .env.example .env  # add your API key")
    click.echo("  pip install -e .")
    click.echo("  python agent.py 'Hello!'")
