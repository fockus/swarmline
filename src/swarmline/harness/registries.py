"""Composition / infra registry seam — resolves ``HarnessSpec`` blocks by name.

harness-composition spec, Task 2 (REQ-002 mechanism for the composition and
infra layers). There is currently no supervisor-composition or
observability-infra registry anywhere in the repository: the H6 supervisor
(``swarmline.orchestration.supervisor``) is opt-in application code and the
observability-events block is an unwritten spec. Rather than hardcode an
if/elif on ``CompositionSpec.mode`` / ``InfraSpec`` flags (which would block
adding blocks without editing this module every time), this module defines a
small, generic, dict-based resolver — deliberately mirroring the shape of
:class:`swarmline.runtime.thin.kernels.registry.KernelRegistry`
(``register``/``get``/``names``) — and exposes two process-wide singleton
instances, one for composition modes and one for infra blocks.

Nothing is registered here in Task 2: :meth:`HarnessBuilder.build` only
*asks* these registries "is this block available?" — the common,
``composition=None``/``infra=None`` minimal path never touches them at all
(REQ-008/009, zero overhead). When a block IS requested (e.g.
``composition.mode="supervisor"`` or ``infra.checkpoint=True``) but has no
registered resolver, ``get()`` raises a clear, named error listing whatever
IS available — the same shape ``KernelNotFound`` uses, and the foundation
Task 5 (REQ-003) builds full spec validation on.

Backlog (tracked, not part of this task): wire the H6 supervisor and the
future observability-events blocks into these two registries once they are
built — a caller would then do
``get_composition_registry().register("supervisor", supervisor_factory)``
without touching this module or ``HarnessBuilder``.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any


class CompositionBlockNotFound(LookupError):
    """Raised when ``CompositionSpec.mode`` has no registered resolver."""

    def __init__(self, mode: str, available: frozenset[str]) -> None:
        self.mode = mode
        self.available = available
        listed = ", ".join(sorted(available)) or "(none registered yet)"
        super().__init__(
            f"Unknown composition mode {mode!r}. Available: {listed}. "
            "The supervisor/graph composition layer is not wired into the "
            "harness registry seam yet (see swarmline.harness.registries "
            "module docstring)."
        )


class InfraBlockNotFound(LookupError):
    """Raised when a requested ``InfraSpec`` flag has no registered resolver."""

    def __init__(self, block: str, available: frozenset[str]) -> None:
        self.block = block
        self.available = available
        listed = ", ".join(sorted(available)) or "(none registered yet)"
        super().__init__(
            f"Unknown infra block {block!r}. Available: {listed}. "
            "Infrastructure blocks (checkpoint/event_record/replay) are not "
            "wired into the harness registry seam yet (see "
            "swarmline.harness.registries module docstring)."
        )


class _BlockRegistry:
    """Thread-safe name -> zero-arg resolver registry.

    Mirrors ``KernelRegistry``'s ``register``/``get``/``modes`` shape (renamed
    ``names`` here since "modes" is kernel-specific vocabulary). A resolver is
    intentionally opaque (``Callable[[], Any]``) — this module never
    constructs a concrete composition/infra object itself; it only proves
    "was this name registered", which is all Task 2 needs.
    """

    def __init__(self, not_found: type[LookupError]) -> None:
        self._lock = threading.Lock()
        self._resolvers: dict[str, Callable[[], Any]] = {}
        self._not_found = not_found

    def register(self, name: str, resolver: Callable[[], Any]) -> None:
        """Register a zero-argument resolver for *name*. Overwrites if present."""
        with self._lock:
            self._resolvers[name] = resolver

    def get(self, name: str) -> Any:
        """Resolve *name*, raising ``self._not_found(name, self.names())`` if unknown."""
        with self._lock:
            resolver = self._resolvers.get(name)
        if resolver is None:
            raise self._not_found(name, self.names())
        return resolver()

    def names(self) -> frozenset[str]:
        """Return a snapshot of all registered names."""
        with self._lock:
            return frozenset(self._resolvers.keys())


_composition_registry = _BlockRegistry(CompositionBlockNotFound)
_infra_registry = _BlockRegistry(InfraBlockNotFound)


def get_composition_registry() -> _BlockRegistry:
    """Return the process-wide composition-mode registry seam."""
    return _composition_registry


def get_infra_registry() -> _BlockRegistry:
    """Return the process-wide infra-block registry seam."""
    return _infra_registry
