"""TDD tests for Stage C1.5 — durable-agent vendor wrappers (DBOS / Prefect).

Temporal is SUPERSEDED by the native ``swarmline.runtime.temporal`` runtime
(plan "Scope review 2026-07-04") — no ``TemporalDurableRuntime`` wrapper, so
no tests for it here.

Offline (default run): a fake engine callable stands in for the real
``dbos``/``prefect`` SDK — zero vendor installs required, matching the
project's default ``pytest -m "not live"`` posture. ``live`` tests skip
unless the real SDK is importable AND a service connection string is set via
env var (``DBOS_DATABASE_URL`` / ``PREFECT_API_URL``); neither is available
here, so they always skip in this sandbox.

Fakes reused from ``tests/unit/_durable_fakes.py`` (``ScriptedRuntime``) —
loaded by file path (not a bare ``from _durable_fakes import ...``): no
shared package ``__init__.py`` with ``tests/unit/``, so pytest's "prepend"
sys.path insertion doesn't reliably expose it when this file runs alone.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Any

import pytest

from swarmline.domain_types import Message, RuntimeErrorData, RuntimeEvent
from swarmline.durable.dbos import DbosDurableRuntime
from swarmline.durable.prefect import PrefectDurableRuntime
from swarmline.protocols.runtime import AgentRuntime

_fakes_path = Path(__file__).resolve().parents[1] / "unit" / "_durable_fakes.py"
_fakes_spec = importlib.util.spec_from_file_location("_durable_fakes", _fakes_path)
assert _fakes_spec is not None and _fakes_spec.loader is not None
_durable_fakes = importlib.util.module_from_spec(_fakes_spec)
_fakes_spec.loader.exec_module(_durable_fakes)

ScriptedRuntime = _durable_fakes.ScriptedRuntime


async def _passthrough_engine(activity: Any) -> Any:
    return await activity()


async def _failing_engine(activity: Any) -> Any:
    raise RuntimeError("engine boom")


# ---------------------------------------------------------------------------
# DBOS
# ---------------------------------------------------------------------------


def test_dbos_durable_runtime_is_agent_runtime() -> None:
    fake = ScriptedRuntime([RuntimeEvent.final("hi")])
    runtime = DbosDurableRuntime(fake, dbos=_passthrough_engine)
    assert isinstance(runtime, AgentRuntime)


async def test_dbos_durable_runtime_runs_inner_via_fake_engine() -> None:
    final_event = RuntimeEvent.final(
        "hi", new_messages=[Message(role="assistant", content="hi")]
    )
    fake = ScriptedRuntime([final_event])
    runtime = DbosDurableRuntime(fake, dbos=_passthrough_engine)

    events = [
        event
        async for event in runtime.run(messages=[], system_prompt="s", active_tools=[])
    ]

    assert len(events) == 1
    assert events[0].type == "final"
    assert events[0].data == final_event.data


def test_dbos_durable_runtime_missing_sdk_raises_helpful_error() -> None:
    if importlib.util.find_spec("dbos") is not None:
        pytest.skip("dbos SDK is installed in this environment")
    fake = ScriptedRuntime([RuntimeEvent.final("hi")])
    with pytest.raises(ImportError, match="dbos"):
        DbosDurableRuntime(fake)


async def test_dbos_durable_runtime_engine_error_surfaces_as_error_event() -> None:
    fake = ScriptedRuntime([RuntimeEvent.final("hi")])
    runtime = DbosDurableRuntime(fake, dbos=_failing_engine)

    events = [
        event
        async for event in runtime.run(messages=[], system_prompt="s", active_tools=[])
    ]

    assert len(events) == 1
    assert events[0].type == "error"
    assert "engine boom" in events[0].data.get("message", "")


async def test_dbos_durable_runtime_inner_error_only_preserves_message() -> None:
    inner_error = RuntimeEvent.error(
        RuntimeErrorData(kind="tool_error", message="tool exploded", recoverable=True)
    )
    fake = ScriptedRuntime([inner_error])
    runtime = DbosDurableRuntime(fake, dbos=_passthrough_engine)

    events = [
        event
        async for event in runtime.run(messages=[], system_prompt="s", active_tools=[])
    ]

    assert len(events) == 1
    assert events[0].type == "error"
    assert events[0].data["kind"] == "tool_error"
    assert events[0].data["message"] == "tool exploded"


async def test_dbos_durable_runtime_no_events_at_all_surfaces_missing_final_error() -> (
    None
):
    fake = ScriptedRuntime([])
    runtime = DbosDurableRuntime(fake, dbos=_passthrough_engine)

    events = [
        event
        async for event in runtime.run(messages=[], system_prompt="s", active_tools=[])
    ]

    assert len(events) == 1
    assert events[0].type == "error"
    assert "without a final" in events[0].data["message"]


async def test_dbos_durable_runtime_non_json_safe_final_surfaces_as_error_event() -> (
    None
):
    bad_final = RuntimeEvent(
        type="final",
        data={"text": "hi", "new_messages": [], "metrics": {"weird": {1, 2, 3}}},
    )
    fake = ScriptedRuntime([bad_final])
    runtime = DbosDurableRuntime(fake, dbos=_passthrough_engine)

    events = [
        event
        async for event in runtime.run(messages=[], system_prompt="s", active_tools=[])
    ]

    assert len(events) == 1
    assert events[0].type == "error"


def test_dbos_durable_runtime_sdk_present_no_engine_raises_value_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name: object(),  # noqa: ARG005
    )
    fake = ScriptedRuntime([RuntimeEvent.final("hi")])
    with pytest.raises(ValueError, match="inject"):
        DbosDurableRuntime(fake)


@pytest.mark.live
async def test_dbos_durable_runtime_live_roundtrip() -> None:
    pytest.importorskip("dbos")
    if not os.environ.get("DBOS_DATABASE_URL"):
        pytest.skip("no DBOS service configured (DBOS_DATABASE_URL unset)")

    from dbos import DBOS  # type: ignore[import-not-found]

    DBOS(config={"name": "swarmline-durable-test"})
    DBOS.launch()

    @DBOS.step()
    async def _step(activity: Any) -> Any:
        return await activity()

    # A step is only checkpointed inside an ENCLOSING workflow (r2 finding) --
    # the workflow, not the bare step, is the durable unit.
    @DBOS.workflow()
    async def _workflow(activity: Any) -> Any:
        return await _step(activity)

    async def engine(activity: Any) -> Any:
        return await _workflow(activity)

    fake = ScriptedRuntime([RuntimeEvent.final("hi")])
    runtime = DbosDurableRuntime(fake, dbos=engine)
    events = [
        event
        async for event in runtime.run(messages=[], system_prompt="s", active_tools=[])
    ]
    assert events[-1].type == "final"
    # Best-effort only: no handle/status assertion -- the exact API
    # (`DBOS.start_workflow`/`get_workflow_status`, etc.) is unconfirmed
    # here, and this test always skips without a real DBOS_DATABASE_URL.


# ---------------------------------------------------------------------------
# Prefect
# ---------------------------------------------------------------------------


def test_prefect_durable_runtime_is_agent_runtime() -> None:
    fake = ScriptedRuntime([RuntimeEvent.final("hi")])
    runtime = PrefectDurableRuntime(fake, flow=_passthrough_engine)
    assert isinstance(runtime, AgentRuntime)


async def test_prefect_durable_runtime_runs_inner_via_fake_engine() -> None:
    final_event = RuntimeEvent.final(
        "hi", new_messages=[Message(role="assistant", content="hi")]
    )
    fake = ScriptedRuntime([final_event])
    runtime = PrefectDurableRuntime(fake, flow=_passthrough_engine)

    events = [
        event
        async for event in runtime.run(messages=[], system_prompt="s", active_tools=[])
    ]

    assert len(events) == 1
    assert events[0].type == "final"
    assert events[0].data == final_event.data


def test_prefect_durable_runtime_missing_sdk_raises_helpful_error() -> None:
    if importlib.util.find_spec("prefect") is not None:
        pytest.skip("prefect SDK is installed in this environment")
    fake = ScriptedRuntime([RuntimeEvent.final("hi")])
    with pytest.raises(ImportError, match="prefect"):
        PrefectDurableRuntime(fake)


async def test_prefect_durable_runtime_engine_error_surfaces_as_error_event() -> None:
    fake = ScriptedRuntime([RuntimeEvent.final("hi")])
    runtime = PrefectDurableRuntime(fake, flow=_failing_engine)

    events = [
        event
        async for event in runtime.run(messages=[], system_prompt="s", active_tools=[])
    ]

    assert len(events) == 1
    assert events[0].type == "error"
    assert "engine boom" in events[0].data.get("message", "")


async def test_prefect_durable_runtime_inner_error_only_preserves_message() -> None:
    inner_error = RuntimeEvent.error(
        RuntimeErrorData(kind="tool_error", message="tool exploded", recoverable=True)
    )
    fake = ScriptedRuntime([inner_error])
    runtime = PrefectDurableRuntime(fake, flow=_passthrough_engine)

    events = [
        event
        async for event in runtime.run(messages=[], system_prompt="s", active_tools=[])
    ]

    assert len(events) == 1
    assert events[0].type == "error"
    assert events[0].data["kind"] == "tool_error"
    assert events[0].data["message"] == "tool exploded"


async def test_prefect_durable_runtime_no_events_at_all_surfaces_missing_final_error() -> (
    None
):
    fake = ScriptedRuntime([])
    runtime = PrefectDurableRuntime(fake, flow=_passthrough_engine)

    events = [
        event
        async for event in runtime.run(messages=[], system_prompt="s", active_tools=[])
    ]

    assert len(events) == 1
    assert events[0].type == "error"
    assert "without a final" in events[0].data["message"]


def test_prefect_durable_runtime_sdk_present_no_engine_raises_value_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name: object(),  # noqa: ARG005
    )
    fake = ScriptedRuntime([RuntimeEvent.final("hi")])
    with pytest.raises(ValueError, match="inject"):
        PrefectDurableRuntime(fake)


@pytest.mark.live
async def test_prefect_durable_runtime_live_roundtrip() -> None:
    pytest.importorskip("prefect")
    if not os.environ.get("PREFECT_API_URL"):
        pytest.skip("no Prefect service configured (PREFECT_API_URL unset)")

    from prefect import flow  # type: ignore[import-not-found]

    async def engine(activity: Any) -> Any:
        @flow
        async def _flow() -> Any:
            return await activity()

        return await _flow()

    fake = ScriptedRuntime([RuntimeEvent.final("hi")])
    runtime = PrefectDurableRuntime(fake, flow=engine)
    events = [
        event
        async for event in runtime.run(messages=[], system_prompt="s", active_tools=[])
    ]
    assert events[-1].type == "final"


# ---------------------------------------------------------------------------
# Malformed envelope -- parametrized across both vendors (reclaims lines vs.
# 6 near-identical per-vendor functions; r3 review added the hostile-repr
# case on top of the r2 bogus-kind/missing-payload cases).
# ---------------------------------------------------------------------------


class _HostileRepr:
    """An object whose ``repr()`` raises -- proves the malformed-envelope
    error path never crashes formatting a hostile outcome (r3 finding)."""

    def __repr__(self) -> str:
        raise RuntimeError("repr boom")


class _HostileHashKind:
    """Not a ``str`` at all; ``__hash__`` raises (r4 residual)."""

    def __hash__(self) -> int:
        raise RuntimeError("hash boom")


class _EvilStrKind(str):
    """``str`` SUBCLASS, ``__hash__`` raises -- ``isinstance(x, str)`` is
    True but ``type(x) is str`` is False (judge blocker 1: vetting must use
    exact types, not ``isinstance``, or this sails through into
    ``RuntimeErrorData.__post_init__``'s frozenset membership check)."""

    def __hash__(self) -> int:
        raise RuntimeError("evil str subclass hash boom")


_MALFORMED_ENVELOPE_CASES: list[Any] = [
    {"kind": "bogus", "payload": {}},
    {"kind": "final"},  # payload missing
    _HostileRepr(),
    # Envelope is well-formed; the nested error-payload "kind" field is poisoned.
    {"kind": "error", "payload": {"kind": _HostileHashKind(), "message": "x"}},
    {"kind": "error", "payload": {"kind": _EvilStrKind("error"), "message": "x"}},
]
_MALFORMED_ENVELOPE_IDS = [
    "bogus_kind",
    "missing_payload",
    "hostile_repr",
    "poisoned_error_kind_field",
    "evil_str_subclass_kind_field",
]

_VENDOR_RUNTIMES: list[tuple[type, str]] = [
    (DbosDurableRuntime, "dbos"),
    (PrefectDurableRuntime, "flow"),
]


@pytest.mark.parametrize(
    "runtime_cls,engine_kwarg", _VENDOR_RUNTIMES, ids=["dbos", "prefect"]
)
@pytest.mark.parametrize(
    "malformed_outcome", _MALFORMED_ENVELOPE_CASES, ids=_MALFORMED_ENVELOPE_IDS
)
async def test_durable_runtime_malformed_envelope_surfaces_as_error_not_raise(
    malformed_outcome: Any, runtime_cls: type, engine_kwarg: str
) -> None:
    async def malformed_engine(activity: Any) -> Any:
        return malformed_outcome

    fake = ScriptedRuntime([RuntimeEvent.final("hi")])
    runtime = runtime_cls(fake, **{engine_kwarg: malformed_engine})

    events = [
        event
        async for event in runtime.run(messages=[], system_prompt="s", active_tools=[])
    ]

    assert len(events) == 1
    assert events[0].type == "error"
    assert "malformed" in events[0].data["message"]
