"""KernelRegistry — maps mode names to ExecutionKernel factories.

Mirrors RuntimeRegistry (runtime/registry.py) API and entry-point discovery
mechanics.  Application layer: no domain-protocol imports at runtime (only
under TYPE_CHECKING; see FINDING 3 below for the one deliberate, lazily
imported exception used for the ``isinstance`` sanity check in ``get()``).

REQ-004: kernel registry mapping mode name to kernel factory.
REQ-006: kernels registered programmatically at any time (not just at
    import) must be dispatchable — enforced by ``get_default_kernel_registry``
    self-initializing exactly once and staying live thereafter; no
    import-time-frozen snapshot gates dispatch.
REQ-007: entry-point discovery under 'swarmline.kernels' group, run as part
    of the SAME single init path as the built-ins (see ``_init_default_registry``)
    — not an optional, separately-wired step.
REQ-008: KernelNotFound when mode is unknown.
REQ-011: modes() drives VALID_MODES — open/closed to new kernels.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from importlib.metadata import entry_points
from typing import TYPE_CHECKING

from swarmline.runtime.thin.kernels.errors import KernelNotFound

if TYPE_CHECKING:
    from swarmline.protocols.kernel import ExecutionKernel

logger = logging.getLogger(__name__)


class KernelRegistry:
    """Thread-safe registry mapping mode names to ExecutionKernel factories.

    Each factory is ``Callable[[], ExecutionKernel]`` — a zero-argument
    callable.  REQ-002 requires every kernel to receive its inputs through a
    single normalized ``KernelContext`` object (passed later to ``run(ctx)``),
    so factories never take mode-specific constructor kwargs; anything a
    kernel needs at run-time (e.g. ``session_dispatcher``) is read from the
    ``KernelContext`` instead.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._factories: dict[str, Callable[[], ExecutionKernel]] = {}

    def register(self, mode: str, factory: Callable[[], ExecutionKernel]) -> None:
        """Register a kernel factory for *mode*.  Overwrites if already present."""
        with self._lock:
            self._factories[mode] = factory

    def get(self, mode: str) -> ExecutionKernel:
        """Instantiate and return the kernel for *mode*.

        Parameters
        ----------
        mode:
            The execution mode key (e.g. ``"react"``, ``"planner"``).

        Raises
        ------
        KernelNotFound
            When *mode* has no registered factory; the exception message
            names the unknown mode and lists all available modes.
        TypeError
            When the factory returns an object that does not implement the
            ``ExecutionKernel`` protocol (missing a callable ``run`` method)
            — catches a misbehaving third-party/entry-point plugin at
            dispatch time with a clear error instead of an obscure
            ``AttributeError`` deep inside the runtime loop.
        """
        with self._lock:
            factory = self._factories.get(mode)
        if factory is None:
            raise KernelNotFound(mode, self.modes())
        kernel = factory()

        # Lazy import (function scope): keeps this application-layer module
        # free of a module-level domain-protocol import while still allowing
        # a runtime structural check.  No import cycle currently exists
        # (swarmline.protocols never imports swarmline.runtime), but scoping
        # the import here is defensive and matches the TYPE_CHECKING-only
        # import above used for static typing.
        from swarmline.protocols.kernel import ExecutionKernel as _ExecutionKernel

        if not isinstance(kernel, _ExecutionKernel):
            raise TypeError(
                f"Kernel factory registered for mode {mode!r} returned "
                f"{type(kernel).__name__!r}, which does not implement the "
                "ExecutionKernel protocol (missing a callable 'run' method)."
            )
        return kernel

    def modes(self) -> frozenset[str]:
        """Return a snapshot of all registered mode names."""
        with self._lock:
            return frozenset(self._factories.keys())

    def load_entry_points(self, group: str = "swarmline.kernels") -> None:
        """Discover and register kernels declared under *group*.

        Each entry point must be a zero-argument callable returning an
        ``ExecutionKernel`` instance.  Bad plugins are logged and skipped;
        they never crash the process.
        """
        try:
            eps = entry_points(group=group)
        except Exception:
            return

        for ep in eps:
            try:
                factory = ep.load()
                if not callable(factory):
                    logger.warning(
                        "Kernel entry point '%s' is not callable, skipping.",
                        ep.name,
                    )
                    continue
                self.register(ep.name, factory)
            except Exception:
                logger.warning(
                    "Failed to load kernel entry point '%s', skipping.",
                    ep.name,
                    exc_info=True,
                )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_default_registry: KernelRegistry | None = None
_default_lock = threading.Lock()


def _init_default_registry() -> KernelRegistry:
    """Build a fully-initialized default KernelRegistry.

    FINDING 1 / FINDING 2: this is the SINGLE init path — built-ins and
    'swarmline.kernels' entry-point plugins are registered together, in one
    place, so every consumer of ``get_default_kernel_registry()`` (including
    the first call after ``reset_default_kernel_registry()``) observes a
    complete, ready-to-dispatch registry.  Nothing else may register the
    built-ins; the historical import-side-effect in ``kernels/__init__.py``
    now merely triggers this same path rather than duplicating it.

    ``builtins`` is imported lazily (function scope, not module scope) so
    that this module never has to import ``kernels/builtins.py`` at import
    time — avoiding any risk of an import cycle regardless of how
    ``builtins.py``'s own dependencies evolve.
    """
    from swarmline.runtime.thin.kernels.builtins import _register_builtins

    registry = KernelRegistry()
    _register_builtins(registry)
    registry.load_entry_points()
    return registry


def get_default_kernel_registry() -> KernelRegistry:
    """Return the process-wide default KernelRegistry (double-checked locking).

    Self-initializes on first access — and again on the first access after
    ``reset_default_kernel_registry()`` — via ``_init_default_registry()``,
    so the three built-in kernels and any ``swarmline.kernels`` entry-point
    plugins are already registered.  Callers never observe an empty or
    partially-initialized registry (FINDING 1 / FINDING 2).
    """
    global _default_registry
    if _default_registry is not None:
        return _default_registry
    with _default_lock:
        if _default_registry is not None:
            return _default_registry
        _default_registry = _init_default_registry()
        return _default_registry


def reset_default_kernel_registry() -> None:
    """Reset the singleton registry (test isolation only).

    The NEXT call to ``get_default_kernel_registry()`` re-runs the full init
    path (built-ins + entry points) — the registry is never left empty or
    unusable after a reset (FINDING 2).
    """
    global _default_registry
    with _default_lock:
        _default_registry = None
