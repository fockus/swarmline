"""Contract tests for the public `CodeAgent` surface (code-agent-facade plan, Stage 1).

These tests pin the durable ergonomic contract only (constructor + `.model`/`.cwd`
properties + `run`/`stream` shape as async iterator factories) and must pass for
ANY correct implementation — including the real thin-runtime wiring Stage 2 adds.
Skeleton-only behavior (the Stage 1 `NotImplementedError` bodies) is pinned
separately in `test_stage1_skeleton_temporary.py`, which Stage 2 replaces.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import Any

from swarmline.code_agent import CodeAgent


class TestCodeAgentConstruction:
    def test_code_agent_constructs_with_model_and_cwd_only(self, tmp_path: Any) -> None:
        agent = CodeAgent(model="sonnet", cwd=str(tmp_path))

        assert agent.model == "sonnet"
        assert agent.cwd == str(tmp_path)

    def test_code_agent_falls_back_to_sonnet_when_model_empty(self) -> None:
        agent = CodeAgent(model="")

        assert agent.model == "sonnet"

    def test_code_agent_defaults_cwd_to_os_getcwd_when_none(self) -> None:
        agent = CodeAgent(model="sonnet", cwd=None)

        assert agent.cwd == os.getcwd()


class TestCodeAgentTopLevelExport:
    def test_code_agent_top_level_import_exposes_codeagent(self) -> None:
        import swarmline
        from swarmline import CodeAgent as TopLevelCodeAgent

        assert TopLevelCodeAgent is CodeAgent
        assert "CodeAgent" in swarmline.__all__


class TestCodeAgentPackageInvariants:
    def test_code_agent_package_introduces_no_protocols(self) -> None:
        import importlib
        import inspect
        import pkgutil
        from typing import Protocol

        import swarmline.code_agent as pkg

        modules = [pkg] + [
            importlib.import_module(f"{pkg.__name__}.{m.name}")
            for m in pkgutil.iter_modules(pkg.__path__)
        ]
        for module in modules:
            for name, obj in inspect.getmembers(module, inspect.isclass):
                if obj.__module__.startswith(pkg.__name__):
                    assert Protocol not in obj.__mro__, (
                        f"{obj.__module__}.{name} is a Protocol — "
                        "plan constraint: NEW Protocols in code_agent/ = 0"
                    )


class TestCodeAgentRunStreamShape:
    async def test_code_agent_run_returns_async_iterator(self, tmp_path: Any) -> None:
        agent = CodeAgent(model="sonnet", cwd=str(tmp_path))

        stream = agent.run("hello")

        assert isinstance(stream, AsyncIterator)

    async def test_code_agent_stream_returns_async_iterator(
        self, tmp_path: Any
    ) -> None:
        agent = CodeAgent(model="sonnet", cwd=str(tmp_path))

        stream = agent.stream("hello")

        assert isinstance(stream, AsyncIterator)
