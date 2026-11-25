"""Tests for thin-runtime mode constants.

Execution mode is resolved by ``ThinRuntime.run`` from the explicit
``mode_hint`` and the structural fact of whether tools are present — never by
regex on the user's wording. The former ``detect_mode`` heuristic (and its
react/planner keyword patterns) was removed; this module now only enumerates
the valid modes.
"""

from swarmline.runtime.thin.modes import VALID_MODES


class TestValidModes:
    """The execution strategies the runtime can dispatch to.

    ``plan-execute`` (kernel-patterns spec, Task 2) is the canonical mode
    name for the formalized PlanExecuteKernel; ``planner`` is kept as the
    pre-existing, backward-compatible mode for the same kernel (REQ-005
    additive, REQ-012 backward-compat).  ``adapt`` (kernel-patterns spec,
    Task 3) is the ADaPTKernel mode (REQ-002, REQ-005).  ``reflection``
    (Task 4, registered Task 6) is ReflectionKernelAdapter's mode; ``sgr``
    (Task 5, registered Task 6) is SGRKernel's mode — both additive, closing
    the full kernel-patterns spec kernel set (REQ-005, REQ-012).
    """

    def test_all_modes(self) -> None:
        assert {
            "conversational",
            "react",
            "planner",
            "plan-execute",
            "adapt",
            "reflection",
            "sgr",
        } == VALID_MODES
