"""Quality gates — verification checkpoints between pipeline phases."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from swarmline.pipeline.types import GateResult


class CompositeGate:
    """Chain multiple quality gates — all must pass.

    Runs gates in order, stops on first failure.
    """

    def __init__(self, gates: list[Any]) -> None:
        self._gates = gates

    async def check(self, phase_id: str, results: dict[str, Any]) -> GateResult:
        """Run all gates. ALL must pass for composite to pass."""
        details_parts: list[str] = []
        for gate in self._gates:
            result = await gate.check(phase_id, results)
            details_parts.append(f"{result.gate_name}: {'PASS' if result.passed else 'FAIL'}")
            if not result.passed:
                return GateResult(
                    passed=False,
                    gate_name="composite",
                    details=f"Failed at {result.gate_name}: {result.details}",
                )
        return GateResult(
            passed=True,
            gate_name="composite",
            details="; ".join(details_parts),
        )


class CallbackGate:
    """Simple gate from an async callback function.

    Usage::

        gate = CallbackGate("tests_pass", my_async_checker)
    """

    def __init__(
        self,
        name: str,
        callback: Callable[[str, dict[str, Any]], Awaitable[bool]],
    ) -> None:
        self._name = name
        self._callback = callback

    async def check(self, phase_id: str, results: dict[str, Any]) -> GateResult:
        """Invoke the callback. True = passed."""
        try:
            passed = await self._callback(phase_id, results)
        except Exception as exc:  # noqa: BLE001
            return GateResult(
                passed=False,
                gate_name=self._name,
                details=f"Gate callback error: {exc}",
            )
        return GateResult(
            passed=passed,
            gate_name=self._name,
            details="passed" if passed else "failed",
        )
