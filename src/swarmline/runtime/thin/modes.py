"""Mode constants for the thin runtime.

Execution mode is resolved by ``ThinRuntime.run`` from the explicit
``mode_hint`` and the structural fact of whether tools are present — never by
regex on the user's wording. The former ``detect_mode`` heuristic (with its
react/planner keyword patterns) was removed: it silently denied tools to
tool-equipped agents and hijacked plain questions containing «план»/«plan»
into the multi-step planner. This module now only enumerates the valid modes.
"""

from __future__ import annotations


VALID_MODES = frozenset({"conversational", "react", "planner"})
