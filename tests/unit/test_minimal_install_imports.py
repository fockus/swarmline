"""Regression tests for minimal wheel import behavior."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_top_level_import_without_httpx_succeeds() -> None:
    """`import swarmline` must not require thin/runtime optional deps."""
    repo_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root / "src")
    code = r"""
import importlib.abc
import sys

class BlockHttpx(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname == "httpx" or fullname.startswith("httpx."):
            raise ModuleNotFoundError("blocked httpx")
        return None

sys.meta_path.insert(0, BlockHttpx())
sys.modules.pop("httpx", None)

from swarmline import Agent, AgentConfig
import swarmline

assert AgentConfig.__name__ == "AgentConfig"
assert Agent.__name__ == "Agent"
assert isinstance(swarmline.__version__, str)
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
