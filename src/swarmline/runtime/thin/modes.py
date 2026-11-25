"""Mode constants for the thin runtime.

Execution mode is resolved by ``ThinRuntime.run`` from the explicit
``mode_hint`` and the structural fact of whether tools are present — never by
regex on the user's wording. The former ``detect_mode`` heuristic (with its
react/planner keyword patterns) was removed: it silently denied tools to
tool-equipped agents and hijacked plain questions containing «план»/«plan»
into the multi-step planner. This module now only enumerates the valid modes.

REQ-011: VALID_MODES is derived from the KernelRegistry so adding a kernel
never requires editing a hardcoded constant.  Importing this module triggers
the kernels package import which auto-registers the three built-in kernels
(and any 'swarmline.kernels' entry-point plugins present at that time).

NOTE (FINDING 1): VALID_MODES is an import-time snapshot kept for
backward-compat convenience only.  It does NOT reflect kernels registered
programmatically after this module was first imported.  The production
dispatch path (``ThinRuntime.run`` in ``runtime.py``) does NOT use this
constant — it validates ``mode_hint`` against
``get_default_kernel_registry().modes()`` live, at call time, so
runtime-registered kernels (REQ-006) and entry-point kernels (REQ-007) are
always dispatchable regardless of when they were registered.
"""

from __future__ import annotations

# Importing the kernels package auto-registers react / planner / conversational.
from swarmline.runtime.thin.kernels import get_default_kernel_registry

VALID_MODES: frozenset[str] = get_default_kernel_registry().modes()
