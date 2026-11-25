"""Unit: I-020 — supervisor package stays import-light (Task 5 additions).

Importing `swarmline.orchestration.supervisor` necessarily first imports
its parent package `swarmline.orchestration`, whose (pre-existing, unrelated
to H6) `__init__.py` already eagerly imports `ThinRuntime`,
`swarmline.verification`, and the base `swarmline.multi_agent` package (plus
several of its submodules — `agent_registry`/`agent_tool`/`task_queue`/etc.,
verified empirically below). None of that is new, and this test does not
assert it away — it is out of Task 5's control.

What Task 5's own new modules DO control, and what this test isolates, is
the ONE dependency edge that `orchestration/__init__.py`'s existing imports
do NOT already pull in: `swarmline.multi_agent.graph_orchestrator` (the
`DefaultGraphOrchestrator`/`DelegationRequest` surface `handoff.py` targets).
`handoff.py` must keep importing `DelegationRequest` LAZILY, inside
`handoff()`, so that merely importing `orchestration.supervisor` does not
newly add that edge on top of the pre-existing baseline.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Baseline: what `swarmline.orchestration` (the unavoidable parent package)
# already pulls in on its own, BEFORE any supervisor code runs.
_BASELINE_CHECK_CODE = (
    "import sys\n"
    "import swarmline.orchestration\n"
    "mods = sys.modules\n"
    "assert 'swarmline.multi_agent.graph_orchestrator' not in mods, ("
    "'graph_orchestrator is part of the baseline — the invariant below "
    "would be vacuous')\n"
    "print('BASELINE-OK')\n"
)

# The invariant Task 5 controls: importing the supervisor package on top of
# that same baseline must not add `graph_orchestrator`.
_SUPERVISOR_IMPORT_CHECK_CODE = (
    "import sys\n"
    "import swarmline.orchestration\n"
    "import swarmline.orchestration.supervisor\n"
    "mods = sys.modules\n"
    "assert 'swarmline.multi_agent.graph_orchestrator' not in mods, "
    "'graph_orchestrator pulled eagerly by importing orchestration.supervisor'\n"
    "assert 'swarmline.multi_agent.graph_orchestrator_types' not in mods, "
    "'graph_orchestrator_types pulled eagerly by importing orchestration.supervisor'\n"
    "print('OK')\n"
)


def test_baseline_orchestration_import_does_not_pull_graph_orchestrator() -> None:
    """Confirms the invariant checked below is meaningful (not vacuously
    true because `graph_orchestrator` was already loaded by the unrelated
    parent-package baseline)."""
    result = subprocess.run(
        [sys.executable, "-c", _BASELINE_CHECK_CODE],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "BASELINE-OK" in result.stdout


def test_importing_supervisor_package_does_not_eagerly_pull_graph_orchestrator() -> (
    None
):
    result = subprocess.run(
        [sys.executable, "-c", _SUPERVISOR_IMPORT_CHECK_CODE],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


def test_handoff_module_has_no_module_level_multiagent_import() -> None:
    """Lexical guard, belt-and-suspenders alongside the runtime check above:
    `handoff.py` never imports `swarmline.multi_agent` at module (top)
    level — only inside the `handoff()` function body."""
    handoff_path = (
        REPO_ROOT / "src" / "swarmline" / "orchestration" / "supervisor" / "handoff.py"
    )
    text = handoff_path.read_text(encoding="utf-8")
    module_level_lines = [
        line for line in text.splitlines() if not line.startswith((" ", "\t"))
    ]
    for line in module_level_lines:
        assert not line.startswith("from swarmline.multi_agent"), (
            f"handoff.py: module-level multi_agent import: {line!r}"
        )
        assert not line.startswith("import swarmline.multi_agent"), (
            f"handoff.py: module-level multi_agent import: {line!r}"
        )
