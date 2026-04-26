"""Stage 15 (H-4) — verify all custom swarmline exceptions inherit from SwarmlineError."""

from __future__ import annotations

import importlib

import pytest

from swarmline.errors import SwarmlineError


# (module_path, class_name, secondary_parent)
# secondary_parent is a stdlib base preserved through multiple inheritance,
# or None if the class only inherits from SwarmlineError.
_EXCEPTION_TARGETS: list[tuple[str, str, type | None]] = [
    ("swarmline.multi_agent.graph_governance", "GovernanceError", None),
    ("swarmline.pipeline.budget", "BudgetExceededError", RuntimeError),
    ("swarmline.a2a.client", "A2AClientError", None),
    ("swarmline.hitl.gate", "ApprovalDeniedError", None),
    ("swarmline.runtime.thin.errors", "ThinLlmError", RuntimeError),
    ("swarmline.runtime.deepagents_models", "DeepAgentsModelError", RuntimeError),
    ("swarmline.agent.structured", "StructuredOutputError", None),
    ("swarmline.agent.middleware", "BudgetExceededError", RuntimeError),
    ("swarmline.mcp._session", "HeadlessModeError", None),
    ("swarmline.daemon.pid", "DaemonAlreadyRunningError", RuntimeError),
]


@pytest.mark.parametrize(
    ("module_path", "class_name", "secondary_parent"),
    _EXCEPTION_TARGETS,
    ids=[f"{m}.{c}" for m, c, _ in _EXCEPTION_TARGETS],
)
def test_custom_exception_subclasses_swarmline_error(
    module_path: str, class_name: str, secondary_parent: type | None
) -> None:
    """Each custom swarmline exception must subclass SwarmlineError.

    Where the original parent was RuntimeError, that base is preserved via
    multiple inheritance so legacy `except RuntimeError:` keeps working.
    """
    module = importlib.import_module(module_path)
    exc_class = getattr(module, class_name)
    assert issubclass(exc_class, SwarmlineError), (
        f"{class_name} from {module_path} must subclass SwarmlineError"
    )
    if secondary_parent is not None:
        assert issubclass(exc_class, secondary_parent), (
            f"{class_name} must preserve {secondary_parent.__name__} "
            f"via multiple inheritance"
        )


def test_swarmline_error_is_exception_subclass() -> None:
    assert issubclass(SwarmlineError, Exception)


def test_swarmline_error_is_raisable() -> None:
    with pytest.raises(SwarmlineError, match="boom"):
        raise SwarmlineError("boom")


def test_subclass_can_be_caught_via_swarmline_error() -> None:
    """The whole point of the hierarchy: one except catches all."""
    from swarmline.runtime.thin.errors import ThinLlmError
    from swarmline.runtime.types import RuntimeErrorData

    err = ThinLlmError(
        RuntimeErrorData(kind="runtime_crash", message="x", recoverable=False)
    )
    with pytest.raises(SwarmlineError):
        raise err
