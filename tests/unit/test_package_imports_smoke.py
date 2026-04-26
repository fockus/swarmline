"""Smoke tests for package-level public imports.

Гарантируем, что canonical package entry points импортируются в чистом
subprocess и экспортируют ключевые публичные символы.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC_ROOT = _REPO_ROOT / "src"


def _subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    src = str(_SRC_ROOT)
    env["PYTHONPATH"] = src if not existing else src + os.pathsep + existing
    return env


@pytest.mark.parametrize(
    ("module_name", "expected_symbols"),
    [
        (
            "swarmline.daemon",
            [
                "DaemonRunner",
                "Scheduler",
                "RoutineBridge",
                "Routine",
                "RoutineRun",
                "RoutineStatus",
                "RunStatus",
                "RoutineManager",
            ],
        ),
        (
            "swarmline.multi_agent",
            [
                "AgentToolResult",
                "create_agent_tool_spec",
                "execute_agent_tool",
                "ExecutionWorkspace",
                "LocalWorkspace",
                "WorkspaceHandle",
                "WorkspaceSpec",
                "WorkspaceStrategy",
            ],
        ),
        (
            "swarmline.observability",
            [
                "EventBus",
                "InMemoryEventBus",
                "ActivityLog",
                "InMemoryActivityLog",
                "SqliteActivityLog",
                "ActivityLogSubscriber",
                "ActivityEntry",
                "ActivityFilter",
                "ActorType",
            ],
        ),
        (
            "swarmline.pipeline",
            [
                "PipelineBuilder",
                "BudgetPolicy",
                "PersistentBudgetStore",
                "InMemoryPersistentBudgetStore",
                "SqlitePersistentBudgetStore",
                "BudgetScope",
                "BudgetThreshold",
                "ThresholdResult",
            ],
        ),
        (
            "swarmline.plugins",
            [
                "PluginRunner",
                "SubprocessPluginRunner",
                "PluginHandle",
                "PluginManifest",
                "PluginState",
            ],
        ),
        (
            "swarmline.session",
            [
                "DefaultSessionRehydrator",
                "InMemorySessionManager",
                "SessionKey",
                "SessionState",
                "TaskSessionStore",
                "InMemoryTaskSessionStore",
                "SqliteTaskSessionStore",
                "TaskSessionParams",
            ],
        ),
    ],
)
def test_package_import_exports_in_clean_subprocess(
    module_name: str,
    expected_symbols: list[str],
) -> None:
    code = (
        "import importlib; "
        f"module = importlib.import_module({module_name!r}); "
        f"expected = {expected_symbols!r}; "
        "missing = [name for name in expected if getattr(module, name, None) is None]; "
        "assert not missing, f'Missing exports: {missing}'"
    )

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=_REPO_ROOT,
        env=_subprocess_env(),
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, (
        f"Import smoke failed for {module_name}:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
