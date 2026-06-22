"""Tests for PipelineContext — the shared artifact/message side-channel.

The context is the per-run carrier the engine threads into every stage handler (via the
(value, context) / (value, context, params) arity). It is deliberately mutable so handlers can
publish artifacts (e.g. the per-turn seams/ports) and compact messages for later stages. It is the
single ``PipelineContext`` for the whole pipeline package (re-exported by ``swarmline.pipeline.typed``).
"""

from __future__ import annotations

from swarmline.pipeline.dataflow_core import PipelineContext


def test_write_then_read_artifact_roundtrips() -> None:
    """An artifact written under a key is read back unchanged."""
    ctx = PipelineContext()
    ctx.write_artifact("seam", {"call": 1})

    assert ctx.read_artifact("seam") == {"call": 1}


def test_read_missing_artifact_returns_default() -> None:
    """A missing key yields the supplied default (None when omitted)."""
    ctx = PipelineContext()

    assert ctx.read_artifact("absent") is None
    assert ctx.read_artifact("absent", "fallback") == "fallback"


def test_add_message_appends_with_from_and_metadata() -> None:
    """add_message records a compact dict carrying the sender (``"from"``), content and metadata."""
    ctx = PipelineContext()
    ctx.add_message("gather", "8 candidates", phase="search")

    assert ctx.messages == [
        {"from": "gather", "content": "8 candidates", "phase": "search"}
    ]


def test_context_is_re_exported_from_typed() -> None:
    """The legacy ``swarmline.pipeline.typed`` path resolves to the same single class."""
    from swarmline.pipeline.typed import PipelineContext as TypedPipelineContext

    assert TypedPipelineContext is PipelineContext


def test_independent_contexts_do_not_share_state() -> None:
    """Each context has its own artifacts dict (no shared mutable default)."""
    first = PipelineContext()
    second = PipelineContext()
    first.write_artifact("x", 1)

    assert second.read_artifact("x") is None
