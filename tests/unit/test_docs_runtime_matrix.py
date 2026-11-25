"""CI drift gate: docs/runtimes.md capability matrix matches the code matrix.

Imports the generator (scripts/gen_runtime_matrix.py) and runs its check
logic directly — no subprocess. If this fails, regenerate with:

    python scripts/gen_runtime_matrix.py
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "gen_runtime_matrix.py"
_DOCS_PATH = _REPO_ROOT / "docs" / "runtimes.md"


def _load_generator():  # noqa: ANN202 - dynamic module
    spec = importlib.util.spec_from_file_location("gen_runtime_matrix", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_docs_matrix_matches_code_matrix() -> None:
    generator = _load_generator()
    docs_text = _DOCS_PATH.read_text(encoding="utf-8")
    assert generator.BEGIN_MARKER in docs_text, "generated-matrix markers missing"
    assert generator.END_MARKER in docs_text, "generated-matrix markers missing"
    assert generator.docs_are_current(_DOCS_PATH), (
        "docs/runtimes.md capability matrix is stale — run "
        "`python scripts/gen_runtime_matrix.py` to regenerate"
    )


def test_matrix_covers_all_public_runtimes_and_dimensions() -> None:
    """The rendered table must list every dimension and public runtime."""
    from swarmline.runtime.capabilities import CAPABILITY_DIMENSIONS

    generator = _load_generator()
    table = generator.render_matrix()
    for runtime in generator.PUBLIC_RUNTIMES:
        assert f"`{runtime}`" in table
    for dimension in CAPABILITY_DIMENSIONS:
        assert f"| `{dimension}` |" in table
    assert "headless" not in table


def test_check_mode_detects_drift(tmp_path: Path) -> None:
    """--check exits non-zero when the docs section is stale."""
    generator = _load_generator()
    stale = tmp_path / "runtimes.md"
    stale.write_text(
        f"# Runtimes\n\n{generator.BEGIN_MARKER}\nstale content\n"
        f"{generator.END_MARKER}\n",
        encoding="utf-8",
    )
    assert not generator.docs_are_current(stale)
    assert generator.main(["--check", "--docs", str(stale)]) == 1
    # write mode repairs it, after which check passes
    assert generator.main(["--docs", str(stale)]) == 0
    assert generator.docs_are_current(stale)
    assert generator.main(["--check", "--docs", str(stale)]) == 0
