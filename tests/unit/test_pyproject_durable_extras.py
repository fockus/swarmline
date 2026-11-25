"""Stage C1.4 — durable-backend extras declared in ``pyproject.toml``.

Scope (plan §Scope review п.1, narrowed at execution): ``[temporal]`` already
shipped (native temporal-runtime feature) and is legitimately in ``[all]`` --
untouched here. This stage's delta is exactly two new opt-in extras,
``dbos``/``prefect``, each a single lower-bound-pinned dependency, kept OUT
of ``[all]`` and any umbrella extra (C-DP1: heavyweight durable orchestrators
stay opt-in). ``tomllib`` + ``pathlib`` only -- no new deps.
"""

from __future__ import annotations

import pathlib
import re
import tomllib

_PYPROJECT_PATH = pathlib.Path(__file__).resolve().parents[2] / "pyproject.toml"


def _load_optional_dependencies() -> dict[str, list[str]]:
    data = tomllib.loads(_PYPROJECT_PATH.read_text())
    return data["project"]["optional-dependencies"]


def test_pyproject_declares_durable_extras() -> None:
    extras = _load_optional_dependencies()

    assert {"temporal", "dbos", "prefect"} <= set(extras)

    # Exact pins are the business contract of this stage (C1.4): a wrong
    # distribution (dbos-transact) or floor (dbos>=1.0) must fail here.
    assert extras["dbos"] == ["dbos>=2.0"]
    assert extras["prefect"] == ["prefect>=3.0"]
    assert extras["temporal"] == ["temporalio>=1.8"]


def test_durable_orchestrator_extras_not_in_all() -> None:
    extras = _load_optional_dependencies()
    all_extra = extras["all"]
    assert len(all_extra) == 1
    # `all` is a single self-referencing "swarmline[a,b,c,...]" entry.
    match = re.fullmatch(r"swarmline\[([^\]]+)\]", all_extra[0].strip())
    assert match is not None, f"unexpected [all] format: {all_extra[0]!r}"
    names_in_all = {name.strip() for name in match.group(1).split(",")}

    # `temporal` IS legitimately in [all] -- it shipped as a native runtime
    # extra (temporal-runtime feature), not merely a durable orchestrator;
    # out of scope for this stage, intentionally NOT asserted absent here.
    assert "dbos" not in names_in_all
    assert "prefect" not in names_in_all
