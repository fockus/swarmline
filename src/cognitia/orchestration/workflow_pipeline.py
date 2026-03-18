"""WorkflowPipeline - generic structured pipeline protocol."""

from __future__ import annotations

from typing import Protocol

from cognitia.orchestration.types import Plan
from cognitia.orchestration.verification_types import VerificationResult


class WorkflowPipeline(Protocol):
    """Generic structured pipeline: research -> plan -> execute -> review -> verify."""

    async def research(self, goal: str) -> str: ...

    async def plan(self, research: str) -> Plan: ...

    async def execute(self, plan: Plan) -> str: ...

    async def review(self, result: str) -> str: ...

    async def verify(self, result: str) -> VerificationResult: ...
