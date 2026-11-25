"""BL-82: secrets must not settle in durable checkpoint state.

Stage 4 (tool-result offload) and Stage 6 (compaction) both persist raw tool
output into checkpoint state: offload projections keep a head+tail slice of the
body, write-failure fallbacks keep the WHOLE body, and compression summaries
keep model-written prose about it. Whatever a tool printed -- an API key echoed
by a curl, a token in an error message -- lands in the host's durable store and
stays there long after the run ends.

``CheckpointWriter.after_tool_call`` is the single chokepoint every checkpoint
write in the react loop goes through, so redaction belongs there: no state key
can bypass it, and no host store has to remember to do it. Redaction is applied
to the PERSISTED copy only -- the live in-memory state keeps the real bytes, so
the running agent still sees what its tool actually returned.
"""

from __future__ import annotations

import json

from swarmline.resilience.checkpoint import CheckpointWriter

_SECRET = "sk-ant-api03-AAAABBBBCCCCDDDDEEEEFFFFGGGGHHHHIIIIJJJJKKKKLLLL"


class _DurableStore:
    """Serializes on save, exactly like a real DB-backed store — so the tests
    assert on what actually reaches disk, not on a dict held by reference."""

    def __init__(self) -> None:
        self.rows: dict[str, str] = {}

    def save_checkpoint(self, run_id: str, state: dict[str, object]) -> None:
        self.rows[run_id] = json.dumps(state, sort_keys=True)

    def load_checkpoint(self, run_id: str) -> dict[str, object] | None:
        raw = self.rows.get(run_id)
        return json.loads(raw) if raw is not None else None

    def clear_checkpoint(self, run_id: str) -> None:
        self.rows.pop(run_id, None)


async def _persist(state: dict[str, object]) -> tuple[_DurableStore, str]:
    store = _DurableStore()
    writer = CheckpointWriter(store, namespace="sw:")
    await writer.after_tool_call(run_id="run-1", step=1, total_steps=3, state=state)
    return store, store.rows["sw:run-1"]


class TestCheckpointSecretRedaction:
    async def test_offload_fallback_body_is_redacted_on_disk(self) -> None:
        """Write-failure fallbacks carry the FULL tool body — the worst case."""
        _, persisted = await _persist(
            {
                "_tool_result_offload_fallbacks": {
                    "call-1": f"export ANTHROPIC_API_KEY={_SECRET}"
                }
            }
        )

        assert _SECRET not in persisted
        assert "[REDACTED]" in persisted

    async def test_offload_projection_is_redacted_on_disk(self) -> None:
        _, persisted = await _persist(
            {
                "_tool_result_offload": {
                    "call-1": {"head": f"token={_SECRET}", "tail": "...done"}
                }
            }
        )

        assert _SECRET not in persisted

    async def test_compaction_summary_is_redacted_on_disk(self) -> None:
        _, persisted = await _persist(
            {
                "_compaction_compression_history": [
                    {"summary": f"The build used ANTHROPIC_API_KEY={_SECRET}"}
                ]
            }
        )

        assert _SECRET not in persisted

    async def test_inline_tool_output_in_messages_is_redacted_too(self) -> None:
        """A SMALL tool result never gets offloaded — it stays inline in
        ``lm_messages`` and would otherwise persist verbatim. Redaction walks the
        whole payload rather than a list of known keys, so this is covered, and
        so is every state key swarmline adds later."""
        _, persisted = await _persist(
            {"lm_messages": [{"role": "user", "content": f"here is my key: {_SECRET}"}]}
        )

        assert _SECRET not in persisted

    async def test_live_state_keeps_the_real_bytes(self) -> None:
        """Only the durable COPY is redacted. Mutating the caller's state would
        blind the running agent to what its own tool returned."""
        live_state: dict[str, object] = {
            "_tool_result_offload_fallbacks": {"call-1": _SECRET}
        }

        await _persist(live_state)

        assert live_state == {"_tool_result_offload_fallbacks": {"call-1": _SECRET}}

    async def test_secret_free_state_round_trips_unchanged(self) -> None:
        """Redaction is a no-op on ordinary content — restorability, and every
        byte-equality assertion the crash-recovery suite makes, are unaffected."""
        state: dict[str, object] = {
            "_tool_result_offload": {
                "call-1": {"head": "Reading file...", "tail": "42 rows"}
            },
            "_compaction_compression_history": [{"summary": "Refactored the parser."}],
            "lm_messages": [{"role": "user", "content": "hello"}],
            "iterations": 7,
            "_tool_schema_snapshot": None,
        }

        store, _ = await _persist(state)
        loaded = store.load_checkpoint("sw:run-1")

        assert loaded is not None
        assert {key: loaded[key] for key in state} == state

    async def test_step_and_total_are_still_injected(self) -> None:
        """The writer's existing contract must survive the redaction pass."""
        store, _ = await _persist({"iterations": 2})
        loaded = store.load_checkpoint("sw:run-1")

        assert loaded is not None
        assert loaded["_step"] == 1
        assert loaded["_total_steps"] == 3
