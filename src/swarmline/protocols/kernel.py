"""ExecutionKernel Protocol — domain contract for pluggable loop strategies.

Domain layer: zero external dependencies (stdlib + swarmline.domain_types only).
ISP: exactly 1 method (run).

Usage::

    class MyKernel:
        def run(self, ctx: KernelContext) -> AsyncIterator[RuntimeEvent]:
            async def _gen():
                yield RuntimeEvent.final(text="done")
            return _gen()

    from swarmline.protocols import ExecutionKernel
    assert isinstance(MyKernel(), ExecutionKernel)
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from swarmline.domain_types import RuntimeEvent

if TYPE_CHECKING:
    from swarmline.types import KernelContext


@runtime_checkable
class ExecutionKernel(Protocol):
    """Single loop-cycle contract for any kernel strategy.

    Implementations: react / planner / conversational / custom.
    ISP: exactly 1 method — the loop is one behaviour; everything else
    lives in KernelContext or the KernelRegistry.
    """

    def run(self, ctx: KernelContext) -> AsyncIterator[RuntimeEvent]:
        """Run the agent loop, yielding streaming events."""
        ...  # pragma: no cover
