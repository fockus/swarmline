"""Deprecation contract for the long ``*PipelineStage`` aliases (M3).

The verbose ``TypedPipelineStage`` / ``ParallelPipelineStage`` / ``LoopPipelineStage`` names predate
the canonical short stage names and are deprecated since 1.6.0. Accessing a long name — from either
``swarmline.pipeline`` or ``swarmline.pipeline.typed`` — must emit a ``DeprecationWarning`` and return
the IDENTICAL canonical class (so ``type(stage)`` stays canonical and the engine's type→runner
registry still dispatches). Importing the package itself must stay warning-free, the canonical names
must never warn, and a pipeline built with the deprecated alias must still build and run.
"""

from __future__ import annotations

import subprocess
import sys
import warnings

import pytest

from swarmline.pipeline import LoopStage, ParallelStage, TypedPipeline, TypedStage

_DEPRECATED = [
    ("TypedPipelineStage", "TypedStage"),
    ("ParallelPipelineStage", "ParallelStage"),
    ("LoopPipelineStage", "LoopStage"),
]
_CANONICAL = {
    "TypedStage": TypedStage,
    "ParallelStage": ParallelStage,
    "LoopStage": LoopStage,
}


@pytest.fixture(autouse=True)
def _reset_deprecation_memo() -> None:
    """Clear the once-per-process warn memo so each test observes a fresh DeprecationWarning."""
    import swarmline.pipeline.typed as typed_mod

    typed_mod._warned_aliases.clear()


@pytest.mark.parametrize(("alias", "canonical"), _DEPRECATED)
def test_alias_on_typed_module_warns_and_returns_canonical(
    alias: str, canonical: str
) -> None:
    """Accessing a long alias on ``swarmline.pipeline.typed`` warns and yields the canonical class."""
    import swarmline.pipeline.typed as typed_mod

    with pytest.warns(DeprecationWarning, match=f"{alias} is deprecated"):
        obj = getattr(typed_mod, alias)
    assert obj is _CANONICAL[canonical]


@pytest.mark.parametrize(("alias", "canonical"), _DEPRECATED)
def test_alias_on_package_warns_and_returns_canonical(
    alias: str, canonical: str
) -> None:
    """Accessing a long alias on the ``swarmline.pipeline`` package warns and yields the canonical class."""
    import swarmline.pipeline as pkg

    with pytest.warns(DeprecationWarning, match=f"{alias} is deprecated"):
        obj = getattr(pkg, alias)
    assert obj is _CANONICAL[canonical]


def test_unknown_attribute_still_raises_attribute_error() -> None:
    """A genuinely missing attribute still raises ``AttributeError`` (the deprecation hook is narrow)."""
    import swarmline.pipeline as pkg
    import swarmline.pipeline.typed as typed_mod

    with pytest.raises(AttributeError):
        _ = pkg.DefinitelyNotAThing  # type: ignore[attr-defined]
    with pytest.raises(AttributeError):
        _ = typed_mod.DefinitelyNotAThing  # type: ignore[attr-defined]


def test_canonical_names_do_not_warn() -> None:
    """The canonical short names resolve with zero deprecation noise (``-W error`` proof, in-process)."""
    import swarmline.pipeline as pkg

    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        assert pkg.TypedStage is TypedStage
        assert pkg.ParallelStage is ParallelStage
        assert pkg.LoopStage is LoopStage
        assert pkg.TypedPipeline is TypedPipeline


async def test_deprecated_alias_still_builds_and_runs_pipeline() -> None:
    """A pipeline built via the deprecated alias runs identically — the alias IS the canonical class."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        from swarmline.pipeline import TypedPipelineStage  # noqa: PLC0415 — exercise the deprecated path

    pipeline = TypedPipeline(stages=[TypedPipelineStage("double", lambda v: v * 2)])
    result = await pipeline.run(21)

    assert result.status == "completed"
    assert result.output == 42


def test_from_import_emits_exactly_one_warning() -> None:
    """`from swarmline.pipeline import <Alias>` warns exactly once (the import machinery probes twice)."""
    with warnings.catch_warnings(record=True) as records:
        warnings.simplefilter("always", DeprecationWarning)
        from swarmline.pipeline import LoopPipelineStage  # noqa: F401,PLC0415 — deprecated path

    dep = [
        r
        for r in records
        if issubclass(r.category, DeprecationWarning)
        and "LoopPipelineStage" in str(r.message)
    ]
    assert len(dep) == 1, [str(r.message) for r in dep]


@pytest.mark.parametrize(
    "stmt", ["import swarmline.pipeline", "from swarmline.pipeline import *"]
)
def test_imports_are_warning_free_under_w_error(stmt: str) -> None:
    """Plain import AND star-import must exit 0 under ``-W error::DeprecationWarning`` (no eager warn)."""
    proc = subprocess.run(
        [sys.executable, "-W", "error::DeprecationWarning", "-c", stmt],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
