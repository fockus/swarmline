"""``PrefectDurableRuntime`` — Prefect-backed durable-agent wrapper (Stage C1.5).

Optional extra (``swarmline[prefect]``); this module never imports
``prefect`` at module level, so ``import swarmline.durable`` (and even
``from swarmline.durable import PrefectDurableRuntime``) succeeds with the
SDK absent -- only *constructing* the wrapper raises.

Collected-run v1 (Decision Point C-DP4): ``AgentRuntime.run`` is a streaming
async generator, but Prefect orchestrates flows/tasks, not streams. This
wrapper drains the inner run into ONE collected, JSON-safe outcome envelope
(``{"kind": "final"|"error", "payload": {...}}`` -- a ``final`` event wins if
the inner stream ever produced one; otherwise the last ``error`` event's
payload is used; a stream with neither is treated as a failure, NOT a clean
empty success, since the thin runtime's ``error`` events are terminal but
non-raising and would otherwise be silently swallowed), hands a callable
producing that envelope to the injected ``flow=`` engine, and re-exposes the
outcome as a single ``final`` or ``error`` ``RuntimeEvent`` (so the decorator
still satisfies ``AgentRuntime``). Streaming-through-durable is a documented
follow-up, not built here.

DI seam: ``flow`` is any async callable ``async def engine(activity) ->
dict`` that awaits ``activity()`` under Prefect's durability guarantees, e.g.
wrapping ``activity`` in an async ``@flow``-decorated function and awaiting
it, on a running Prefect server/API (deployment-specific -- left to the
caller, not guessed here; the Risk-table concern this stage documents, not
solves). Construction FAILS FAST without an injected engine: SDK absent ->
``ImportError`` naming the extra; SDK present -> ``ValueError`` (installing
the SDK alone is not enough -- a real engine must still be wired and
injected; there is deliberately NO silent pass-through default, which would
otherwise run with zero actual Prefect durability guarantees).

Retry-safety (documented, not solved here): if the injected engine retries
the activity, the inner run re-executes from scratch. Compose with C1.1's
``DurableRuntime`` (checkpoint-after-step) for transcript-backed idempotency
across retries.
"""

from __future__ import annotations

import importlib.util
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TYPE_CHECKING, Any, NoReturn

from swarmline.domain_types import Message, RuntimeErrorData, RuntimeEvent, ToolSpec
from swarmline.protocols.runtime import AgentRuntime

if TYPE_CHECKING:
    from swarmline.runtime.types import RuntimeConfig

Engine = Callable[[Callable[[], Awaitable[dict[str, Any]]]], Awaitable[dict[str, Any]]]

_VENDOR = "PrefectDurableRuntime"


def _safe_repr(obj: object) -> str:
    """``repr(obj)`` for an error message, never itself raising.

    The durable outcome envelope crosses an untrusted boundary (an engine
    can return anything); even formatting it for a "malformed envelope"
    error must not raise a SECOND exception (a hostile/broken ``__repr__``
    would otherwise escape the generator). ``type(obj).__name__`` is safe --
    metaclass ``__name__`` weirdness is out of trust scope here.
    """
    try:
        return repr(obj)[:200]
    except Exception:
        return f"<unreprable {type(obj).__name__}>"


def _require_injected_engine() -> NoReturn:
    """No ``flow=`` seam was injected -- always raises (fail-fast)."""
    if importlib.util.find_spec("prefect") is None:
        raise ImportError(
            "The `prefect` package is required for PrefectDurableRuntime "
            "without an injected `flow=` engine. Install `swarmline[prefect]`."
        )
    raise ValueError(
        "PrefectDurableRuntime requires a configured `flow=` engine to be "
        "injected -- installing `prefect` alone is not enough. Wire a real "
        "engine (e.g. an async `@flow`-decorated function wrapping the "
        "activity, on a running Prefect server) and inject it as "
        "`flow=<engine>`."
    )


async def _run_collected(
    inner: AgentRuntime,
    *,
    messages: list[Message],
    system_prompt: str,
    active_tools: list[ToolSpec],
    config: RuntimeConfig | None,
    mode_hint: str | None,
) -> dict[str, Any]:
    """Drain ``inner.run`` and return an explicit outcome envelope.

    A ``final`` event wins if seen at all (even after an earlier ``error``);
    otherwise the LAST ``error`` event's payload is used; a stream with
    neither yields a synthetic error naming the missing terminal event.
    Asserts the envelope is JSON-safe here (the activity/durable-boundary
    side) so a non-serializable payload fails before crossing into the
    engine, surfacing as an ``error`` event rather than an unhandled crash.
    """
    final_payload: dict[str, Any] | None = None
    error_payload: dict[str, Any] | None = None
    async for event in inner.run(
        messages=messages,
        system_prompt=system_prompt,
        active_tools=active_tools,
        config=config,
        mode_hint=mode_hint,
    ):
        if event.type == "final":
            final_payload = dict(event.data)
        elif event.type == "error":
            error_payload = dict(event.data)

    if final_payload is not None:
        outcome: dict[str, Any] = {"kind": "final", "payload": final_payload}
    elif error_payload is not None:
        outcome = {"kind": "error", "payload": error_payload}
    else:
        outcome = {
            "kind": "error",
            "payload": {
                "kind": "runtime_crash",
                "message": f"{_VENDOR}: inner run ended without a final event",
                "recoverable": False,
            },
        }
    json.dumps(outcome)  # assert JSON-safe -- fail before crossing the engine
    return outcome


class PrefectDurableRuntime:
    """Collected-run Prefect wrapper — implements ``AgentRuntime`` (5 methods)."""

    def __init__(self, inner: AgentRuntime, *, flow: Engine | None = None) -> None:
        if flow is None:
            _require_injected_engine()
        self._inner = inner
        self._engine: Engine = flow

    async def run(
        self,
        *,
        messages: list[Message],
        system_prompt: str,
        active_tools: list[ToolSpec],
        config: RuntimeConfig | None = None,
        mode_hint: str | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        async def _activity() -> dict[str, Any]:
            return await _run_collected(
                self._inner,
                messages=messages,
                system_prompt=system_prompt,
                active_tools=active_tools,
                config=config,
                mode_hint=mode_hint,
            )

        try:
            outcome = await self._engine(_activity)
        except Exception as exc:
            yield RuntimeEvent.error(
                RuntimeErrorData(
                    kind="runtime_crash",
                    message=f"{_VENDOR} engine failed: {exc}",
                    recoverable=False,
                )
            )
            return

        # The durable boundary round-trips through storage/the engine -- a
        # corrupted/version-mismatched envelope, or an engine that RETURNS a
        # hostile object (broken `__repr__`, a dict subclass whose `.get()`
        # raises), is a real path, not a hypothetical. ALL envelope
        # inspection -- validation, EXACT-type vetting, and field extraction
        # for either branch -- happens inside this one try, so any raise
        # from a hostile value is caught here and routed to `problem`. The
        # `RuntimeErrorData(...)` construction below happens AFTER the try,
        # but by then `error_kind`/`error_message`/`error_recoverable`/
        # `error_details` only ever hold exact-type-vetted primitives (never
        # a hostile subclass), so that construction cannot itself raise.
        problem: str | None = None
        final_data: dict[str, Any] | None = None
        error_kind = "runtime_crash"
        error_message = ""
        error_recoverable = False
        error_details: dict[str, Any] | None = None
        try:
            if (
                not isinstance(outcome, dict)
                or outcome.get("kind") not in ("final", "error")
                or not isinstance(outcome.get("payload"), dict)
            ):
                problem = (
                    f"{_VENDOR}: malformed durable outcome envelope: "
                    f"{_safe_repr(outcome)}"
                )
            elif outcome["kind"] == "error":
                payload = outcome["payload"]
                kind_val = payload.get("kind", "runtime_crash")
                message_val = payload.get("message", "")
                recoverable_val = payload.get("recoverable", False)
                details_val = payload.get("details")
                # Type-vet with EXACT types (`type(x) is T`), NOT
                # `isinstance` -- `isinstance` admits a hostile SUBCLASS
                # (e.g. a `str` subclass with a poisoned `__hash__`/`__eq__`/
                # `__repr__`), which would sail through here and then blow
                # up downstream: `error_kind` feeds `RuntimeErrorData(kind=
                # ...)`, whose `__post_init__` does `self.kind not in
                # RUNTIME_ERROR_KINDS` (a frozenset membership check -- it
                # HASHES the value). A field present-but-wrong-type (or a
                # right-type-but-subclassed value) must fail closed
                # (malformed), never be silently defaulted -- only an ABSENT
                # key gets the `.get(..., default)` fallback above. `json`
                # deserialization never produces subclasses, so no
                # legitimate envelope is ever rejected by this exactness.
                if (
                    type(kind_val) is not str
                    or type(message_val) is not str
                    or type(recoverable_val) is not bool
                    or (details_val is not None and type(details_val) is not dict)
                ):
                    problem = (
                        f"{_VENDOR}: malformed durable outcome envelope: "
                        f"{_safe_repr(outcome)}"
                    )
                else:
                    error_kind = kind_val
                    error_message = message_val
                    error_recoverable = recoverable_val
                    error_details = details_val
            else:
                final_data = outcome["payload"]
        except Exception:
            problem = (
                f"{_VENDOR}: malformed durable outcome envelope: {_safe_repr(outcome)}"
            )

        if problem is not None:
            yield RuntimeEvent.error(
                RuntimeErrorData(
                    kind="runtime_crash", message=problem, recoverable=False
                )
            )
            return

        if final_data is not None:
            yield RuntimeEvent(type="final", data=final_data)
            return

        yield RuntimeEvent.error(
            RuntimeErrorData(
                kind=error_kind,
                message=error_message,
                recoverable=error_recoverable,
                details=error_details,
            )
        )

    async def cleanup(self) -> None:
        await self._inner.cleanup()

    def cancel(self) -> None:
        self._inner.cancel()

    async def __aenter__(self) -> PrefectDurableRuntime:
        await self._inner.__aenter__()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self._inner.__aexit__(*args)
