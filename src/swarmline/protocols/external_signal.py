"""ExternalSignal Protocol — grounds Reflection in a signal outside the model.

kernel-patterns spec, Task 4 (REQ-003, REQ-009), Scenario 3. ADR "Reflection
заземлён на внешний сигнал" (design.md; arxiv 2310.01798): intrinsic
self-correction WITHOUT an external signal does not reliably work — a model
critiquing its own output is not a trustworthy stop condition. ``evaluate``
is therefore the ONLY way ``ReflectionKernel`` decides pass/fail; the model
itself never gets to declare "I'm done" — see
``swarmline.runtime.thin.kernels.reflection.ReflectionKernel``.

Domain layer: zero external dependencies (stdlib + swarmline domain types
only). ISP: exactly 1 method (evaluate).

Usage::

    class TestSuiteSignal:
        async def evaluate(self, output: str, ctx: KernelContext) -> SignalResult:
            passed = run_tests(output)
            return SignalResult(passed=passed, feedback="..." if not passed else "")

    from swarmline.protocols import ExternalSignal
    assert isinstance(TestSuiteSignal(), ExternalSignal)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from swarmline.types import SignalResult

if TYPE_CHECKING:
    from swarmline.types import KernelContext


@runtime_checkable
class ExternalSignal(Protocol):
    """Grounds a Reflection critique in something OTHER than the model itself.

    Implementations: a test suite, a schema validator, a distinct verifier
    model/service — anything that is not the same generation asking itself
    "was I right?". ISP: exactly 1 method — the verdict is one behaviour;
    everything else (retry bounds, prompt construction) lives in the kernel.
    """

    async def evaluate(self, output: str, ctx: KernelContext) -> SignalResult:
        """Judge *output* and return a grounded pass/fail verdict + feedback."""
        ...  # pragma: no cover
