"""Tests for thin-runtime mode constants.

Execution mode is resolved by ``ThinRuntime.run`` from the explicit
``mode_hint`` and the structural fact of whether tools are present — never by
regex on the user's wording. The former ``detect_mode`` heuristic (and its
react/planner keyword patterns) was removed; this module now only enumerates
the valid modes.
"""

from swarmline.runtime.thin.modes import VALID_MODES


class TestValidModes:
    """The three execution strategies the runtime can dispatch to."""

    def test_all_modes(self) -> None:
        assert {"conversational", "react", "planner"} == VALID_MODES
