"""Pluggable execution-kernel layer for ThinRuntime.

Importing this package triggers ``get_default_kernel_registry()``, which
self-initializes the default singleton with the built-in kernels — six
kernel classes over seven modes: react / planner / plan-execute /
conversational / adapt / reflection / sgr (``planner`` and ``plan-execute``
share the one ``PlanExecuteKernel`` class) AND any ``swarmline.kernels``
entry-point plugins (FINDING 1).  This module-import call is a convenience
only — it is NOT the mechanism of correctness: ``get_default_kernel_registry()``
performs the same self-init on ANY first call, including the first call
after ``reset_default_kernel_registry()`` (FINDING 2), so callers never
depend on this package having been imported first.

Tree-search kernels (ToT/LATS/RAP) are OUT OF SCOPE for the kernel-patterns
spec — deferred, backlog I-002 (Task 6, REQ-013).

Public API
----------
KernelRegistry            -- registry class (application layer)
KernelNotFound            -- raised by registry.get() for unknown modes
get_default_kernel_registry -- singleton accessor (self-initializing)
reset_default_kernel_registry -- test isolation helper
ReactKernelAdapter        -- adapter wrapping run_react
PlanExecuteKernel         -- formalized plan-and-execute kernel (wraps run_planner)
PlannerKernelAdapter      -- backward-compat alias of PlanExecuteKernel
ConversationalKernelAdapter -- adapter wrapping run_conversational
ADaPTKernel               -- adaptive decompose-on-failure kernel (mode "adapt")
ReflectionKernel          -- external-signal-grounded critique/refine kernel
ReflectionKernelAdapter   -- reads ctx.external_signal per-run (mode "reflection")
SGRKernel                 -- typed-NextStep-driven kernel with ReAct fallback (mode "sgr")
"""

from __future__ import annotations

from swarmline.runtime.thin.kernels.adapt import ADaPTKernel
from swarmline.runtime.thin.kernels.builtins import (
    ConversationalKernelAdapter,
    PlanExecuteKernel,
    PlannerKernelAdapter,
    ReactKernelAdapter,
    ReflectionKernelAdapter,
)
from swarmline.runtime.thin.kernels.errors import KernelNotFound
from swarmline.runtime.thin.kernels.reflection import ReflectionKernel
from swarmline.runtime.thin.kernels.registry import (
    KernelRegistry,
    get_default_kernel_registry,
    reset_default_kernel_registry,
)

# NOTE: SGRKernel is deliberately NOT imported eagerly above (unlike
# ADaPTKernel/ReflectionKernel).  ``kernels/sgr.py`` imports
# ``swarmline.orchestration.nextstep``, and the ``swarmline.orchestration``
# PACKAGE's own ``__init__`` transitively imports
# ``swarmline.runtime.thin.runtime`` (ThinTeamOrchestrator ->
# ThinSubagentOrchestrator -> ThinRuntime) -- which itself imports THIS
# package to reach ``get_default_kernel_registry``.  Whenever
# ``swarmline.runtime.thin.runtime`` is the FIRST module imported in a
# process (a common, realistic entrypoint), an eager top-level
# ``from swarmline.runtime.thin.kernels.sgr import SGRKernel`` here would
# cycle back into that PARTIALLY-INITIALIZED module and raise ImportError --
# see the identical reasoning documented next to ``_register_builtins``'s own
# lazy SGRKernel import in ``kernels/builtins.py``.  ``__getattr__`` below
# (PEP 562) resolves ``SGRKernel`` lazily on first access instead, which is
# safe unconditionally: attribute access only ever happens once this module
# has already finished executing.

# Trigger the singleton's self-initialization (built-ins + entry points;
# REQ-009) so importing this package continues to leave the default registry
# ready, matching the historical contract.  Correctness no longer depends on
# this call happening (see module docstring) — it is retained for the
# side effect of "importing this package warms up the default registry".
get_default_kernel_registry()

__all__ = [
    "ADaPTKernel",
    "ConversationalKernelAdapter",
    "KernelNotFound",
    "KernelRegistry",
    "PlanExecuteKernel",
    "PlannerKernelAdapter",
    "ReactKernelAdapter",
    "ReflectionKernel",
    "ReflectionKernelAdapter",
    "SGRKernel",
    "get_default_kernel_registry",
    "reset_default_kernel_registry",
]


def __getattr__(name: str) -> object:
    """PEP 562 lazy re-export of ``SGRKernel`` — see the NOTE above."""
    if name == "SGRKernel":
        from swarmline.runtime.thin.kernels.sgr import SGRKernel

        return SGRKernel
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
