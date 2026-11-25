"""KernelNotFound — raised when a requested mode has no registered kernel.

REQ-008: IF a requested mode has no registered kernel THEN THE SYSTEM SHALL
raise an error that names the unknown mode and lists the available kernels.
"""

from __future__ import annotations


class KernelNotFound(Exception):
    """Raised by KernelRegistry.get() for an unregistered mode.

    Attributes
    ----------
    mode:
        The mode string that was requested but not found.
    available:
        frozenset of mode names currently in the registry.
    """

    def __init__(self, mode: str, available: frozenset[str]) -> None:
        available_str = ", ".join(sorted(available)) if available else "(none)"
        super().__init__(
            f"No kernel registered for mode '{mode}'. Available modes: {available_str}"
        )
        self.mode = mode
        self.available = available
