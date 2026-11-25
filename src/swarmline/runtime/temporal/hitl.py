"""Durable HITL plumbing — resolve pending approvals from any process.

A tool call gated by the worker's approval policy parks its workflow on a
Temporal signal. Anything holding a Temporal client — the streaming client
app, a `serve` API handler, an ops script — resolves it by ``run_id`` +
``correlation_id`` (both carried in the ``approval_requested`` event and in
the pending-approvals query)::

    from swarmline.runtime.temporal.hitl import TemporalApprovalClient

    approvals = TemporalApprovalClient(options=options)
    print(await approvals.pending(run_id))
    await approvals.approve(run_id, correlation_id, reason="looks safe")
    # or: await approvals.deny(run_id, correlation_id, reason="too risky")

The pending approval survives worker deploys, restarts, and weekends —
durability comes from the workflow, not from this client.
"""

from __future__ import annotations

from typing import Any

from swarmline.runtime.temporal.client import connect_client, workflow_id_for_run
from swarmline.runtime.temporal.options import TemporalRuntimeOptions
from swarmline.runtime.temporal.payloads import (
    APPROVAL_SIGNAL,
    PENDING_APPROVALS_QUERY,
    ApprovalDecision,
)

__all__ = ["TemporalApprovalClient"]


class TemporalApprovalClient:
    """Sends approval decisions into running agent workflows.

    Parameters
    ----------
    client:
        Pre-connected ``temporalio.client.Client`` (or a duck-typed stand-in
        exposing ``get_workflow_handle``). When ``None``, connected lazily
        from ``options``.
    options:
        Connection options; also provide the ``workflow_id_prefix`` used to
        address workflows by ``run_id``.
    """

    def __init__(
        self,
        *,
        client: Any = None,
        options: TemporalRuntimeOptions | None = None,
    ) -> None:
        self._client = client
        self._options = options or TemporalRuntimeOptions()

    async def _handle(self, run_id: str) -> Any:
        if self._client is None:
            self._client = await connect_client(self._options)
        return self._client.get_workflow_handle(
            workflow_id_for_run(self._options, run_id)
        )

    async def approve(
        self,
        run_id: str,
        correlation_id: str,
        *,
        reason: str = "",
        modifications: dict[str, Any] | None = None,
    ) -> None:
        """Approve a pending tool call (optionally with modified args)."""
        await self._signal(
            run_id,
            ApprovalDecision(
                correlation_id=correlation_id,
                approved=True,
                reason=reason,
                modifications=dict(modifications or {}),
            ),
        )

    async def deny(self, run_id: str, correlation_id: str, *, reason: str = "") -> None:
        """Deny a pending tool call; the model sees the reason."""
        await self._signal(
            run_id,
            ApprovalDecision(
                correlation_id=correlation_id, approved=False, reason=reason
            ),
        )

    async def _signal(self, run_id: str, decision: ApprovalDecision) -> None:
        handle = await self._handle(run_id)
        await handle.signal(APPROVAL_SIGNAL, decision)

    async def pending(self, run_id: str) -> list[dict[str, Any]]:
        """Tool calls of the run currently parked on human approval."""
        handle = await self._handle(run_id)
        return await handle.query(PENDING_APPROVALS_QUERY)
