"""Unit tests for quality gates."""

from __future__ import annotations

from typing import Any

from swarmline.pipeline.gate import CallbackGate, CompositeGate
from swarmline.pipeline.protocols import QualityGate


class TestCallbackGate:
    def test_protocol_compliance(self) -> None:
        async def always_pass(phase_id: str, results: dict) -> bool:
            return True

        gate = CallbackGate("test", always_pass)
        assert isinstance(gate, QualityGate)

    async def test_callback_pass(self) -> None:
        async def checker(phase_id: str, results: dict) -> bool:
            return True

        gate = CallbackGate("test", checker)
        result = await gate.check("p1", {})
        assert result.passed is True
        assert result.gate_name == "test"

    async def test_callback_fail(self) -> None:
        async def checker(phase_id: str, results: dict) -> bool:
            return False

        gate = CallbackGate("test", checker)
        result = await gate.check("p1", {})
        assert result.passed is False

    async def test_callback_receives_context(self) -> None:
        received: dict[str, Any] = {}

        async def checker(phase_id: str, results: dict) -> bool:
            received["phase_id"] = phase_id
            received["results"] = results
            return True

        gate = CallbackGate("test", checker)
        await gate.check("my_phase", {"key": "val"})
        assert received["phase_id"] == "my_phase"
        assert received["results"]["key"] == "val"

    async def test_callback_exception_returns_fail(self) -> None:
        async def checker(phase_id: str, results: dict) -> bool:
            raise RuntimeError("boom")

        gate = CallbackGate("test", checker)
        result = await gate.check("p1", {})
        assert result.passed is False
        assert "boom" in result.details


class TestCompositeGate:
    async def test_all_pass(self) -> None:
        async def pass_fn(phase_id: str, results: dict) -> bool:
            return True

        gates = [CallbackGate("g1", pass_fn), CallbackGate("g2", pass_fn)]
        composite = CompositeGate(gates)
        result = await composite.check("p1", {})
        assert result.passed is True

    async def test_first_fails(self) -> None:
        async def fail_fn(phase_id: str, results: dict) -> bool:
            return False

        async def pass_fn(phase_id: str, results: dict) -> bool:
            return True

        composite = CompositeGate(
            [CallbackGate("g1", fail_fn), CallbackGate("g2", pass_fn)]
        )
        result = await composite.check("p1", {})
        assert result.passed is False
        assert "g1" in result.details

    async def test_second_fails(self) -> None:
        async def pass_fn(phase_id: str, results: dict) -> bool:
            return True

        async def fail_fn(phase_id: str, results: dict) -> bool:
            return False

        composite = CompositeGate(
            [CallbackGate("g1", pass_fn), CallbackGate("g2", fail_fn)]
        )
        result = await composite.check("p1", {})
        assert result.passed is False
        assert "g2" in result.details

    async def test_empty_gates_pass(self) -> None:
        composite = CompositeGate([])
        result = await composite.check("p1", {})
        assert result.passed is True

    def test_composite_protocol_compliance(self) -> None:
        composite = CompositeGate([])
        assert isinstance(composite, QualityGate)
