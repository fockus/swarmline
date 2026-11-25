"""Configuration for the Temporal durable runtime."""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from swarmline.runtime.types import RuntimeConfig


@dataclass(frozen=True)
class TemporalRuntimeOptions:
    """Connection and execution options for ``TemporalAgentRuntime``.

    Attributes:
      address: Temporal server address (``host:port`` or Temporal Cloud endpoint).
      namespace: Temporal namespace.
      task_queue: Task queue the agent workflows/activities run on.
      workflow_id_prefix: Prefix for generated workflow ids.
      tls: Enable TLS for the client connection (Temporal Cloud requires it).
      api_key: Temporal Cloud API key (implies TLS).
      stream_events: When True, activities publish RuntimeEvents through the
        event-bus relay (``stream.py``) so the client streams them live.
        Requires an EventBus reachable from both workers and the client
        (Redis/NATS in production). When False, events are returned with the
        workflow result and replayed at completion (buffered mode — no extra
        infrastructure).
      llm_timeout_seconds: start-to-close timeout for the LLM activity.
      tool_timeout_seconds: start-to-close timeout for the tool activity.
      llm_retry_attempts: Temporal retry attempts for the LLM activity
        (transient provider failures).
      tool_retry_attempts: Temporal retry attempts for the tool activity.
        Default 1 (no retry) — tools may be non-idempotent.
      approval_timeout_seconds: Durable expiry timer for HITL approvals —
        a tool call still pending after this long is auto-denied. Default
        24 hours; ``0`` waits indefinitely. Only relevant when workers run
        with an approval policy.
      use_reference_history: When True, the conversation lives in the
        workers' shared ``HistoryStore`` and workflow payloads carry only
        revision numbers — required for long runs that would otherwise hit
        Temporal's payload/history limits. Workers must be configured with
        a ``history_store``.
      continue_as_new_after_iterations: Roll the workflow over via
        continue-as-new after this many loop iterations per segment
        (fresh workflow history; run id and state preserved). ``0``
        disables. Requires ``use_reference_history=True``.
      redact_payloads: Run secret-pattern redaction over every payload
        before it reaches the Temporal server's history (default True —
        history is stored server-side). Decode is passthrough, so mixed
        deployments degrade safely.
      otel_interceptor: Attach temporalio's OpenTelemetry
        ``TracingInterceptor`` to the connection so client → workflow →
        activity spans join one trace. Requires ``swarmline[otel]`` and
        the ``opentelemetry`` packages on both client and workers.
    """

    address: str = "localhost:7233"
    namespace: str = "default"
    task_queue: str = "swarmline-agents"
    workflow_id_prefix: str = "swarmline-agent-"
    tls: bool = False
    api_key: str | None = None
    stream_events: bool = False
    llm_timeout_seconds: float = 300.0
    tool_timeout_seconds: float = 120.0
    llm_retry_attempts: int = 3
    tool_retry_attempts: int = 1
    approval_timeout_seconds: float = 86400.0
    use_reference_history: bool = False
    continue_as_new_after_iterations: int = 0
    redact_payloads: bool = True
    otel_interceptor: bool = False

    def __post_init__(self) -> None:
        if self.continue_as_new_after_iterations > 0 and not self.use_reference_history:
            raise ValueError(
                "continue_as_new_after_iterations requires "
                "use_reference_history=True — without a history store the "
                "conversation cannot survive the workflow rollover."
            )

    @classmethod
    def from_config(cls, config: RuntimeConfig | None) -> TemporalRuntimeOptions:
        """Build options from ``config.extra["temporal"]`` (unknown keys ignored)."""
        raw: dict[str, Any] = {}
        if config is not None and config.extra:
            candidate = config.extra.get("temporal")
            if isinstance(candidate, dict):
                raw = candidate
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in raw.items() if k in known})
