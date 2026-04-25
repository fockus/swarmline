"""Architectural meta-test enforcing the ty strict-mode CI gate.

This test runs `ty check src/swarmline/` as a subprocess and asserts that the
diagnostic count does not exceed the recorded baseline. The baseline is stored
in `tests/architecture/ty_baseline.txt` next to this file. As Sprint 1A reduces
ty diagnostics, the baseline file must be updated downward — the test fails
loudly on regressions and warns when the baseline is outdated.

Marked `slow` because `ty check` over the entire codebase takes 30-90 seconds.
Excluded from default `pytest` runs (default addopts = `-m "not live"` + this
test is registered under `slow`). Run explicitly via:

    pytest tests/architecture/ -v -m slow

Or include in CI via the `Run ty type-check` step in `.github/workflows/ci.yml`.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ARCH_DIR = Path(__file__).resolve().parent
BASELINE_FILE = ARCH_DIR / "ty_baseline.txt"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"

_FOUND_DIAGNOSTICS_RE = re.compile(r"Found (\d+) diagnostic")


def _run_ty() -> int:
    """Run `ty check` and return the diagnostic count (or fail with reason)."""
    if shutil.which("ty") is None:
        pytest.skip("`ty` not installed; install via `pip install ty`")

    proc = subprocess.run(
        ["ty", "check", "src/swarmline/"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    combined = proc.stdout + proc.stderr
    # ty prints "All checks passed!" when there are zero diagnostics,
    # otherwise "Found N diagnostics". Recognize both shapes.
    if "All checks passed" in combined:
        return 0
    match = _FOUND_DIAGNOSTICS_RE.search(combined)
    if match is None:
        pytest.fail(
            f"Could not parse `ty` output for diagnostic count.\n"
            f"stdout: {proc.stdout[-500:]}\nstderr: {proc.stderr[-500:]}"
        )
    return int(match.group(1))


@pytest.mark.slow
def test_ty_baseline_file_exists() -> None:
    """`ty_baseline.txt` exists and contains a parseable non-negative int."""
    assert BASELINE_FILE.is_file(), (
        f"Missing {BASELINE_FILE}. Create it with the current ty diagnostic "
        f"count (run `ty check src/swarmline/` and write the `Found N` value)."
    )
    raw = BASELINE_FILE.read_text(encoding="utf-8").strip()
    assert raw.isdigit(), (
        f"{BASELINE_FILE} must contain a single non-negative integer, got: {raw!r}"
    )
    value = int(raw)
    assert value >= 0
    assert value < 1000, (
        f"Baseline {value} suspiciously high — sanity-check or recreate it"
    )


@pytest.mark.slow
def test_ty_diagnostics_at_or_below_baseline() -> None:
    """`ty check` count must not exceed recorded baseline.

    Hard fail on regression. Soft warning when current is significantly below
    baseline (the baseline file should be updated downward to lock in the gain).
    """
    if not BASELINE_FILE.is_file():
        pytest.fail(
            f"Run test_ty_baseline_file_exists first to confirm baseline setup. "
            f"Missing: {BASELINE_FILE}"
        )

    baseline = int(BASELINE_FILE.read_text(encoding="utf-8").strip())
    current = _run_ty()

    assert current <= baseline, (
        f"REGRESSION: ty diagnostics increased from {baseline} to {current}.\n"
        f"Either fix the new errors OR (if baseline was wrong) update "
        f"{BASELINE_FILE} to {current}.\n"
        f"Run locally: ty check src/swarmline/"
    )

    if current < baseline - 2:
        pytest.fail(
            f"BASELINE OUTDATED: current ty diagnostics = {current}, "
            f"baseline = {baseline}. Update {BASELINE_FILE} to {current} "
            f"to lock in the improvement and prevent silent regressions."
        )


@pytest.mark.slow
def test_ci_workflow_has_ty_step() -> None:
    """`.github/workflows/ci.yml` runs `ty check` as a fail-on-error step.

    Without this CI gate, ty regressions would only be caught when a developer
    runs the meta-test locally. The workflow must exist and contain a step that
    invokes `ty check src/swarmline/` (or equivalent).
    """
    assert CI_WORKFLOW.is_file(), (
        f"Missing CI workflow: {CI_WORKFLOW}. Create it with steps for "
        f"`ruff check`, `ty check src/swarmline/`, and `pytest`."
    )

    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
    jobs = workflow.get("jobs", {})
    assert jobs, f"{CI_WORKFLOW} has no jobs defined"

    found_ty_step = False
    for _job_name, job_def in jobs.items():
        for step in job_def.get("steps", []):
            run_cmd = step.get("run", "") or ""
            if "ty check" in run_cmd and "src/swarmline" in run_cmd:
                found_ty_step = True
                break
        if found_ty_step:
            break

    assert found_ty_step, (
        f"{CI_WORKFLOW} does not contain a step running "
        f"`ty check src/swarmline/`. Add it after the ruff step so type "
        f"errors block PRs alongside lint failures."
    )
