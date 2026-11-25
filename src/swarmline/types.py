"""Core Swarmline types - contracts from architecture section 17.

Contains the shared types used across modules:
TurnContext, ContextPack, SkillSet, KernelContext, SignalResult.

Domain layer: only stdlib + swarmline.domain_types dependencies.
Infrastructure types (RuntimeConfig, ToolExecutor, NativeToolCallAdapter,
HookDispatcher) are referenced via TYPE_CHECKING guards only so the domain
stays zero-dep.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from swarmline.domain_types import RuntimeEvent

if TYPE_CHECKING:
    from swarmline.hooks.dispatcher import HookDispatcher
    from swarmline.protocols.external_signal import ExternalSignal
    from swarmline.runtime.thin.executor import ToolExecutor
    from swarmline.runtime.thin.native_tools import NativeToolCallAdapter
    from swarmline.runtime.thin.round_context import RoundContextRefresher
    from swarmline.runtime.types import RuntimeConfig

# ---------------------------------------------------------------------------
# CheckpointFn — type alias (stdlib + domain only, safe to evaluate at runtime)
# ---------------------------------------------------------------------------

CheckpointFn = Callable[[], Awaitable[RuntimeEvent | None]]

__all__ = [
    "AcceptanceCriterion",
    "CheckpointFn",
    "ContextPack",
    "KernelContext",
    "RuntimeEvent",
    "SignalResult",
    "SkillSet",
    "TurnContext",
    "VerificationLedger",
    "VerificationOutcome",
]


@dataclass(frozen=True)
class TurnContext:
    """Unified turn context - passed between modules.

    Contains everything needed for decisions:
    model selection, tool policy, context assembly.
    """

    user_id: str
    topic_id: str
    role_id: str
    model: str
    active_skill_ids: tuple[str, ...]


@dataclass(frozen=True)
class ContextPack:
    """A context unit with priority and size estimation.

    Priorities (from architecture section 10.2):
    0 - Guardrails (never dropped)
    1 - Role instruction
    2 - Active goals
    3 - Phase
    4 - Tool hints
    5 - Memory recall
    6 - User profile
    """

    pack_id: str
    priority: int
    content: str
    tokens_estimate: int


@dataclass(frozen=True)
class SkillSet:
    """Named skill set (architecture section 5.1).

    The role selects a SkillSet -> the SkillSet defines the tool allowlist.
    """

    set_id: str
    skill_ids: tuple[str, ...] = ()
    local_tool_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class KernelContext:
    """Normalized input context for any execution kernel (REQ-002).

    Provides a single uniform call signature across all loop strategies
    (react / planner / conversational / custom) so ExecutionKernel can
    be a single-method Protocol.

    Required fields are mandatory for all kernels.
    Optional fields (default None) are used only where relevant:
    - conversational ignores executor, tools, native_adapter, session_dispatcher.
    - session_dispatcher is consumed by the react kernel to forward session
      events (e.g. file.edited) — REQ-002 requires it to flow through
      KernelContext rather than as a mode-specific kwarg on the registry.
    - external_signal grounds a "reflection" mode run (kernel-patterns H4
      Task 6): read by ReflectionKernelAdapter from ctx.external_signal
      rather than a mode-specific kwarg, mirroring session_dispatcher above.
    - round_refresher (Sprint 1ce CE-9) re-checks the context budget and
      recites the live plan before every model round of the react kernel;
      None (default) keeps the loop byte-identical.
    """

    llm_call: Callable
    messages: list
    system_prompt: str
    config: RuntimeConfig
    start_time: float
    checkpoint: CheckpointFn
    executor: ToolExecutor | None = None
    tools: list | None = None
    on_retry: Callable | None = None
    native_adapter: NativeToolCallAdapter | None = None
    session_dispatcher: HookDispatcher | None = None
    external_signal: ExternalSignal | None = None
    round_refresher: RoundContextRefresher | None = None


@dataclass(frozen=True)
class SignalResult:
    """Verdict from an :class:`~swarmline.protocols.ExternalSignal` (REQ-009).

    kernel-patterns spec, Task 4 (REQ-003, REQ-009). ``ReflectionKernel``
    grounds its refine decision in this result — NOT in the model's own
    self-judgement (ADR "Reflection заземлён на внешний сигнал", design.md;
    arxiv 2310.01798: intrinsic self-correction without an external signal
    does not work).

    Only the two fields the refine loop actually consumes are present
    (YAGNI): ``passed`` gates continue-vs-stop, ``feedback`` is the text
    injected into the next generation's context. No ``score`` field — no
    kernel behaviour compares or ranks scores, so one is not added
    speculatively.
    """

    passed: bool
    feedback: str = ""


@dataclass(frozen=True)
class AcceptanceCriterion:
    """A single contract item captured before execution (REQ-001/REQ-002).

    verify-before-done spec, Task 1. Criteria are recorded up front so
    "done" means the agreed contract is met, not the model's own
    self-assessment (mirrors the ``ExternalSignal``/``SignalResult``
    rationale above: verification is grounded outside the model).

    ``kind`` distinguishes the two verifier families defined by the spec:
    ``"code"`` (deterministic, primary — :class:`Verifier` resolvable by a
    ``CodeVerifier``, Task 2) and ``"judge"`` (LLM-scored, advisory-only —
    Task 3). ``check_ref`` is an opaque reference to the underlying
    predicate/command for ``"code"`` criteria; ``None`` for ``"judge"``.
    """

    id: str
    description: str
    kind: str
    check_ref: str | None = None


@dataclass(frozen=True)
class VerificationOutcome:
    """Outcome of verifying one :class:`AcceptanceCriterion` (REQ-003).

    ``advisory=True`` marks a judge-sourced result (REQ-007): it is
    recorded for visibility but never counted toward
    :attr:`VerificationLedger.gate_passed` — a judge can supplement the
    gate, never be the sole gate.
    """

    criterion_id: str
    passed: bool
    advisory: bool
    evidence: str


@dataclass(frozen=True)
class VerificationLedger:
    """Immutable ledger of acceptance criteria + their verification results.

    verify-before-done spec, Task 1 (REQ-001, REQ-003, REQ-007). A
    :class:`~swarmline.protocols.verification.Verifier` consumes a ledger
    and returns a NEW ledger with ``results`` populated (frozen-dataclass
    convention across swarmline — see :class:`SignalResult` above; the
    input is never mutated).

    Empty ledger (no criteria, no results) is the "nothing recorded"
    vacuous case: ``gate_passed`` is trivially ``True`` and ``failed`` is
    empty because there is nothing to fail. The opt-in no-op behaviour for
    an empty/disabled ledger at finalization time (REQ-008/REQ-009) is
    gate WIRING, implemented in Task 4 — not this property.
    """

    criteria: tuple[AcceptanceCriterion, ...] = ()
    results: tuple[VerificationOutcome, ...] = ()

    @property
    def gate_passed(self) -> bool:
        """True iff no recorded NON-advisory result has ``passed=False``.

        Per design.md: "все НЕ-advisory результаты passed" — advisory
        (judge) results are ignored entirely, they neither help nor block
        the gate (REQ-007). This is deliberately NOT a coverage check: a
        ledger where every criterion's only result is advisory (or has no
        result at all) reports ``gate_passed=True`` here, because there is
        no non-advisory *failure* to report. Ensuring every criterion
        actually received a non-advisory result (so a judge-only criterion
        cannot silently "pass" the gate — REQ-007 scenario 2) is enforced
        by the gate WIRING in Task 4, which always runs ``verify`` (and,
        for scenario 2, requires a deterministic check per criterion)
        before consulting this property. Do not read ``gate_passed=True``
        in isolation as "every criterion was deterministically verified" —
        that stronger guarantee lives in the wiring, not here.
        """
        return all(result.passed for result in self.results if not result.advisory)

    @property
    def failed(self) -> tuple[VerificationOutcome, ...]:
        """The NON-advisory results with ``passed=False``, advisory results excluded."""
        return tuple(
            result
            for result in self.results
            if not result.advisory and not result.passed
        )
