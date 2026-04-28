"""Smoke tests for runnable examples."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


ROOT = Path(__file__).resolve().parents[2]
EXAMPLES_DIR = ROOT / "examples"
EXAMPLE_FILES = sorted(
    path.name for path in EXAMPLES_DIR.glob("*.py") if path.name != "__init__.py"
)


def _offline_env() -> dict[str, str]:
    env = dict(os.environ)
    for key in (
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
        "DEEPSEEK_API_KEY",
    ):
        env.pop(key, None)
    return env


def _run_example(
    example_name: str,
    *args: str,
    env_overrides: dict[str, str | None] | None = None,
) -> subprocess.CompletedProcess[str]:
    example = EXAMPLES_DIR / example_name
    env = _offline_env()
    if env_overrides:
        for key, value in env_overrides.items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value
    return subprocess.run(
        [sys.executable, str(example), *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def _load_example_module(example_name: str, module_name: str) -> object:
    example = EXAMPLES_DIR / example_name
    spec = importlib.util.spec_from_file_location(module_name, example)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("example_name", EXAMPLE_FILES)
def test_examples_run_offline_without_stderr(example_name: str) -> None:
    proc = _run_example(example_name)

    assert proc.returncode == 0, proc.stderr
    assert proc.stderr == ""
    assert proc.stdout.strip() != ""


def test_example_01_agent_basics_runs_offline_without_api_key() -> None:
    proc = _run_example("01_agent_basics.py")

    assert proc.returncode == 0, proc.stderr
    assert proc.stderr == ""
    assert "Query result: Paris." in proc.stdout
    assert "Turn 2: Your name is Alice." in proc.stdout
    assert "Math: 391." in proc.stdout


def test_example_19_cli_runtime_uses_stream_json_command() -> None:
    proc = _run_example("19_cli_runtime.py")

    assert proc.returncode == 0, proc.stderr
    assert (
        "['claude', '--print', '--verbose', '--output-format', 'stream-json', '-']"
        in proc.stdout
    )


def test_example_24_deep_research_live_requires_api_key_and_fails_fast() -> None:
    proc = _run_example(
        "24_deep_research.py",
        "--live",
        env_overrides={"ANTHROPIC_API_KEY": None, "OPENROUTER_API_KEY": None},
    )

    assert proc.returncode == 1
    assert (
        "Either ANTHROPIC_API_KEY or OPENROUTER_API_KEY is required for --live mode"
        in proc.stderr
    )
    assert "Mock Pipeline" not in proc.stdout


def test_example_27_nano_claw_live_requires_api_key_and_fails_fast() -> None:
    proc = _run_example(
        "27_nano_claw.py",
        "--live",
        env_overrides={"ANTHROPIC_API_KEY": None, "OPENROUTER_API_KEY": None},
    )

    assert proc.returncode == 1
    assert (
        "Either ANTHROPIC_API_KEY or OPENROUTER_API_KEY is required for --live mode"
        in proc.stderr
    )


def test_example_24_deep_research_live_accepts_openrouter_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_example_module("24_deep_research.py", "example_24_live_provider")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")

    model = module._resolve_live_model()

    assert model == "openrouter:anthropic/claude-3.5-haiku"
    assert os.environ["OPENAI_API_KEY"] == "or-test"


def test_example_27_nano_claw_live_accepts_openrouter_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_example_module("27_nano_claw.py", "example_27_live_provider")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")

    model = module._resolve_live_model()

    assert model == "openrouter:anthropic/claude-3.5-haiku"
    assert os.environ["OPENAI_API_KEY"] == "or-test"


@pytest.mark.asyncio
async def test_example_27_nano_claw_demo_turn_executes_mock_tools() -> None:
    module = _load_example_module("27_nano_claw.py", "example_27_demo_tools")
    original_fs = dict(module._MOCK_FS)
    agent = module.NanoClaw(runtime="mock")

    try:
        reply = await agent.run_turn(
            "Write a new file /project/utils.py with a helper function"
        )
        assert "written the new file" in reply.lower()
        assert "/project/utils.py" in module._MOCK_FS
        assert "helper" in module._MOCK_FS["/project/utils.py"].lower()
    finally:
        module._MOCK_FS.clear()
        module._MOCK_FS.update(original_fs)
        await agent.close()


@pytest.mark.asyncio
async def test_example_27_nano_claw_streaming_turn_preserves_cost_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_example_module("27_nano_claw.py", "example_27_stream_cost")
    agent = module.NanoClaw(runtime="mock")

    async def fake_stream(_prompt: str):
        yield SimpleNamespace(type="text_delta", text="hello ")
        yield SimpleNamespace(
            type="done",
            total_cost_usd=1.25,
            usage={"input_tokens": 10, "output_tokens": 5},
        )

    monkeypatch.setattr(agent._conv, "stream", fake_stream)

    try:
        reply = await agent.run_turn("hello")
        assert reply == "hello "
        assert agent._cost_tracker.total_cost_usd == 1.25
    finally:
        await agent.close()


@pytest.mark.asyncio
async def test_example_27_nano_claw_streaming_turn_uses_final_text_for_json_envelope(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_example_module("27_nano_claw.py", "example_27_json_envelope")
    agent = module.NanoClaw(runtime="mock")

    async def fake_stream(_prompt: str):
        yield SimpleNamespace(
            type="text_delta", text='{"type":"final","final_message":"'
        )
        yield SimpleNamespace(type="text_delta", text='Files in /project"}')
        yield SimpleNamespace(
            type="done",
            text="Files in /project",
            total_cost_usd=0.25,
            usage={"input_tokens": 8, "output_tokens": 3},
        )

    monkeypatch.setattr(agent._conv, "stream", fake_stream)

    try:
        reply = await agent.run_turn("List the files in /project")
        captured = capsys.readouterr()
        assert reply == "Files in /project"
        assert '"type":"final"' not in captured.out
        assert "Files in /project" in captured.out
        assert agent._cost_tracker.total_cost_usd == 0.25
    finally:
        await agent.close()
