"""Docs/examples consistency checks for public user-facing guides."""

from __future__ import annotations

import contextlib
import io
import re
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES_DIR = ROOT / "examples"


def _example_names() -> list[str]:
    return sorted(
        path.name for path in EXAMPLES_DIR.glob("*.py") if path.name != "__init__.py"
    )


def test_docs_examples_catalog_references_all_runnable_examples() -> None:
    docs_examples = (ROOT / "docs" / "examples.md").read_text(encoding="utf-8")

    for example_name in _example_names():
        assert f"`{example_name}`" in docs_examples


def test_user_facing_docs_do_not_reference_nonexistent_cost_tracker_api() -> None:
    tracked_files = [
        ROOT / "docs" / "getting-started.md",
        ROOT / "docs" / "agent-facade.md",
    ]

    for path in tracked_files:
        text = path.read_text(encoding="utf-8")
        assert "budget_exceeded" not in text


def test_examples_docs_live_mode_claim_matches_current_surface() -> None:
    examples_readme = (ROOT / "examples" / "README.md").read_text(encoding="utf-8")
    docs_examples = (ROOT / "docs" / "examples.md").read_text(encoding="utf-8")

    assert "Examples 24 and 27 also expose optional `--live` modes" in examples_readme
    assert "`ANTHROPIC_API_KEY` or `OPENROUTER_API_KEY`" in examples_readme
    assert "25 and 26 are mock-only demos" in examples_readme
    assert "`ANTHROPIC_API_KEY` or `OPENROUTER_API_KEY`" in docs_examples

    live_mentions = re.findall(r"`(\d{2}_[^`]+\.py)`", examples_readme)
    assert "24_deep_research.py" in live_mentions
    assert "27_nano_claw.py" in live_mentions


def test_readme_does_not_advertise_nonexistent_cli_extra() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "`swarmline[cli]`" not in readme


def _readme_quickstart_python_blocks() -> list[str]:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    start = readme.index("## Quick Start")
    end = readme.index("## Features", start)
    quickstart = readme[start:end]
    blocks = re.findall(r"```python\n(.*?)\n```", quickstart, flags=re.S)
    return [block.strip() for block in blocks if block.strip()]


async def _fake_dispatch_runtime(runtime_name: str, claude_handler, portable_handler):
    del runtime_name, claude_handler, portable_handler

    async def _events():
        yield SimpleNamespace(type="text_delta", text="Paris")
        yield SimpleNamespace(
            type="done",
            text="Paris",
            total_cost_usd=0.0,
            usage={"input_tokens": 1, "output_tokens": 1},
            structured_output={"name": "John", "age": 30},
            new_messages=[],
        )

    async for event in _events():
        yield event


@pytest.mark.asyncio
async def test_readme_quickstart_code_fences_execute_offline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from swarmline.agent import agent as agent_module
    from swarmline.agent import conversation as conversation_module

    blocks = _readme_quickstart_python_blocks()
    assert blocks, "Expected at least one Python quickstart block in README.md"

    monkeypatch.setattr(agent_module, "dispatch_runtime", _fake_dispatch_runtime)
    monkeypatch.setattr(conversation_module, "dispatch_runtime", _fake_dispatch_runtime)

    namespace: dict[str, object] = {"__name__": "__readme_quickstart__"}
    with contextlib.redirect_stdout(io.StringIO()):
        for block in blocks:
            wrapped = "async def __readme_quickstart_snippet__():\n"
            wrapped += textwrap.indent(block, "    ")
            exec(wrapped, namespace)
            await namespace["__readme_quickstart_snippet__"]()


def test_cli_runtime_docs_use_stream_json_claude_command() -> None:
    cli_docs = (ROOT / "docs" / "cli-runtime.md").read_text(encoding="utf-8")
    assert 'command=["claude", "--print", "-"]' not in cli_docs
    assert (
        'command=["claude", "--print", "--output", "stream-json", "-"]' not in cli_docs
    )
    assert (
        'command=["claude", "--print", "--verbose", "--output-format", "stream-json", "-"]'
        in cli_docs
    )
    assert "registry.create(" not in cli_docs


def test_agent_facade_docs_match_current_middleware_api() -> None:
    agent_docs = (ROOT / "docs" / "agent-facade.md").read_text(encoding="utf-8")

    assert "tracker.total_cost)" not in agent_docs
    assert "budget_exceeded" not in agent_docs
    assert "on_blocked" not in agent_docs
    assert "| `budget_usd` | `float` | `0.0` |" in agent_docs
    assert "reverse order for `after_result`" not in agent_docs


def test_credentials_docs_cover_runtime_env_matrix() -> None:
    credentials = (ROOT / "docs" / "credentials.md").read_text(encoding="utf-8")

    for runtime_name in ("thin", "claude_sdk", "deepagents", "cli"):
        assert f"`{runtime_name}`" in credentials

    for variable in (
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "GOOGLE_API_KEY",
        "OPENROUTER_API_KEY",
    ):
        assert variable in credentials

    assert (
        "AgentConfig.env` is currently used by the `claude_sdk` runtime path"
        in credentials
    )
    assert "does **not** accept `openrouter:*`" in credentials


def test_entry_docs_link_to_credentials_reference() -> None:
    tracked_files = [
        ROOT / "README.md",
        ROOT / "docs" / "getting-started.md",
        ROOT / "docs" / "configuration.md",
        ROOT / "docs" / "runtimes.md",
        ROOT / "docs" / "cli-runtime.md",
    ]

    for path in tracked_files:
        text = path.read_text(encoding="utf-8")
        assert "credentials.md" in text
