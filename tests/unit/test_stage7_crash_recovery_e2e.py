"""Stage 7 (context-engineering-manus-parity, FINAL) — e2e crash-recovery
verification through the PUBLIC ``ThinRuntime.run()`` API.

Stages 1-6 each built and unit-tested their own piece of the OSS-T4
checkpoint substrate in isolation: tool-schema pinning (Stage 3), tool-result
offload frozen projections (Stage 4), recitation cadence statelessness
(Stage 5), compaction's compression_history anti-thrashing window (Stage 6).
This file is the closing e2e proof that all of it composes correctly through
a REAL kill-mid-run -> reclaim -> resume cycle on the actual public entry
point a caller (taskloom) uses -- not just the individual pure functions.

Fix-cycle 1 (codex Stage 7 R1, BLOCKER): the original version compared
checkpoint state through ``InMemoryCheckpointStore`` (dict-by-reference) and
never genuinely exercised a write-failure fallback or non-empty
compression_history. Rewritten to force every save/load through a REAL
``json.dumps``/``json.loads`` round-trip, use a REAL disk-backed
``FileScratchpadProvider``, genuinely trigger both an offload success AND a
write-failure fallback plus a real Tier-2 compaction attempt, capture the
actual LLM payload to prove the pinned (not drifted) schema wins, and compare
via canonical JSON (never raw Python ``==`` on live objects).

Fix-cycle 2 (codex Stage 7 R2): fix-cycle 1's rewrite compared TWO
crash-then-resume scenarios against each other ("same live instances" vs
"fresh instances from durable bytes") -- which does prove instance-freshness
doesn't matter, but the plan's actual DoD (line 196) asks for resume to be
byte-equivalent to an ACCIDENT-FREE run, not to another resume. A
deterministic recovery defect that affects BOTH sides identically would have
stayed green under the old comparison. This cycle:

- adds a genuine CRASH-FREE baseline (ONE continuous ``ThinRuntime.run()``
  call, single process, no crash, no durable round-trip at all) compared
  against the crash -> fresh-instance-resume scenario, for every field that
  is legitimately 1:1 comparable regardless of how many ``run()``
  invocations were needed (``_tool_schema_snapshot``, offload maps,
  ``lm_messages``, ``iterations``/``tool_calls_count``, ``_step``/
  ``_total_steps``);
- documents (and tests via CONTAINMENT, not vacuous exact-count equality)
  why ``_compaction_compression_history`` is the ONE field that legitimately
  differs in ENTRY COUNT between a 1-call baseline and a 2-call
  crash+resume: compaction is invoked once PER ``ThinRuntime.run()`` call,
  not once per logical conversation turn -- a crash inherently forces one
  extra invocation to finish the same turn, and each invocation appends its
  own bookkeeping entry by design (this is not a masked bug: the SAME
  savings-ratio entry the baseline recorded is still present, verbatim,
  inside the resumed side's list);
- makes the crash-sanity check assert the SPECIFIC injected crash
  (``kind == "runtime_crash"`` and the injected message), not any ``error``;
- includes ``_step``/``_total_steps`` in the canonical comparison (the
  resume-position fields the report claims are proven equivalent);
- makes the recitation check GENUINE: Call 2 (resume) carries NO recitation
  filter at all, so the marker can ONLY appear via the checkpoint's
  ``lm_messages`` restore mechanism actually working -- not because a
  filter happened to still be configured. Red-first: mutating
  ``_read_lm_messages`` to always return ``None`` makes the marker vanish;
- uses the ``tmp_path`` pytest fixture (auto-cleaned) instead of leaking
  ``tempfile.mkdtemp()`` directories.

Fix-cycle 3 (codex Stage 7 R3): the ONE remaining vacuousness fix-cycle 2
left behind was the CONTAINMENT check itself. Because the pre-crash and
post-resume compaction attempts operated on IDENTICAL input
(``_COMPACTION_PRIME`` against the same ``_INITIAL_MESSAGES``), they produced
NUMERICALLY IDENTICAL records -- so even if the pre-crash entry were
completely LOST during restore, the resumed side's own independently
computed fresh entry would coincidentally satisfy containment. codex proved
this via mutation: deleting the pre-crash history entry from the checkpoint
before resume did NOT redden the old assertion. This cycle:

- introduces ``_COMPACTION_PRIME_RESUME``, a deliberately different summary
  text used ONLY for the resume-side's own from-scratch compaction attempt,
  so its resulting record is genuinely DISTINGUISHABLE from the pre-crash
  one (empirically confirmed: pre-crash ``{"tokens_after": 22, ...}`` vs
  resume's own fresh ``{"tokens_after": 35, ...}``);
- captures ``pre_crash_record`` from the checkpoint immediately after the
  genuine crash, BEFORE the fresh-process handoff (``_fresh_store_from_
  durable_bytes``);
- replaces containment with an exact PREFIX + APPEND proof: the resumed
  history must have exactly 2 entries; the FIRST must be byte-equal
  (canonical JSON) to the captured pre-crash record -- proving genuine
  RESTORATION from the durable checkpoint, not coincidental regeneration;
  the SECOND must be genuinely different from the first (the new
  post-resume attempt).

Also, a report-precision correction (codex R3): the crash-free baseline is
NOT "without any durable round-trip" -- it uses the SAME
``_DurableJsonCheckpointStore`` and therefore serializes through real
``json.dumps``/``json.loads`` on every save/load, exactly like the crash
side. What is genuinely absent on the baseline side is specifically the
MANUAL fresh-process hand-off (``_fresh_store_from_durable_bytes``), which
only happens on the crash+resume side.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from swarmline.compaction import CompactionConfig
from swarmline.context.recitation_input_filter import RecitationInputFilter
from swarmline.resilience.checkpoint import CheckpointPort, CheckpointWriter
from swarmline.runtime.thin.runtime import ThinRuntime
from swarmline.runtime.types import Message, RuntimeConfig, ToolSpec
from swarmline.scratchpad.file_provider import FileScratchpadProvider

_TOOLS = [
    ToolSpec(
        name="big_tool",
        description="original-big-tool-marker",
        parameters={"type": "object", "properties": {}},
    ),
    # Stage 4 (`_scratch_read_available`) requires "scratch_read" among the
    # PINNED tools for offload to ever engage -- see react_strategy.py.
    ToolSpec(
        name="scratch_read",
        description="read scratch",
        parameters={"type": "object", "properties": {}},
    ),
]

#: Above the 32k offload threshold, comfortably below any per-result ceiling.
_BIG_RESULT = "B" * 40_000

#: Enough content that Tier 2 (LLM summarization) genuinely attempts to fire
#: against a threshold_tokens=50 budget -- NOT a vacuous []==[] comparison.
_INITIAL_MESSAGES = [
    Message(role="user", content="old topic detail " * 80),
    Message(role="assistant", content="old reply detail " * 80),
    Message(role="user", content="latest question"),
]

#: Consumed by the compaction pre-step's OWN llm_call (runs BEFORE the react
#: loop even starts) -- content is irrelevant to the assertions below, it
#: just needs to exist so the compaction attempt completes (success or local
#: fallback, either way `_record_tier2_attempt` appends a REAL entry).
#: Sprint 1ce CE-15/19: all seven fixed sections, one per line, or the acceptance gate
#: rejects it and both sides fall back to the SAME deterministic digest.
_COMPACTION_PRIME = (
    "Goal: compaction summary marker words here. "
    "\nConstraints: none.\nProgress: p.\nKey Decisions: k.\nErrors: none.\nFiles: none.\nNext Steps: n."
)

#: codex R3 [1]: a DELIBERATELY DIFFERENT (longer) summary used ONLY for the
#: resume side's OWN compaction attempt, so its resulting
#: tokens_after/savings-ratio entry is DISTINGUISHABLE from the pre-crash
#: entry. Without this, both compaction attempts operate on the exact same
#: `_INITIAL_MESSAGES` and would produce IDENTICAL token counts -- making a
#: containment check pass VACUOUSLY even if the pre-crash entry were never
#: actually restored (the resume side's own fresh attempt would coincidentally
#: satisfy it on its own).
_COMPACTION_PRIME_RESUME = (
    "Goal: resume side compaction summary, a distinguishable longer text for testing purposes here. "
    "\nConstraints: none.\nProgress: p.\nKey Decisions: k.\nErrors: none.\nFiles: none.\nNext Steps: n."
)


async def _big_tool(**_: object) -> str:
    return _BIG_RESULT


def _tool_call_envelope(name: str, call_id: str) -> str:
    return json.dumps(
        {
            "type": "tool_call",
            "tool": {"name": name, "args": {}, "correlation_id": call_id},
            "assistant_message": "",
        }
    )


def _final_envelope(text: str) -> str:
    return json.dumps({"type": "final", "final_message": text})


class _DurableJsonCheckpointStore:
    """A ``CheckpointPort`` that forces every save/load through a REAL
    ``json.dumps``/``json.loads`` round-trip.

    Proves two things a plain dict-by-reference in-memory store (like
    ``InMemoryCheckpointStore``) CANNOT: (1) the full checkpoint state is
    genuinely JSON-serializable end to end -- if frozen offload projections,
    fallbacks, the tool-schema snapshot, or compression_history ever
    contained a non-JSON-safe value (e.g. a raw ``Message`` object), this
    would raise a ``TypeError`` at ``save_checkpoint`` time, a REAL
    production bug a reference-sharing store would silently mask; (2) a
    "fresh process" genuinely cannot see live Python objects from the
    pre-crash process -- only the serialized string. ``durable_snapshot()``
    returns exactly that string map: the ONLY thing a real durable backend
    (Postgres JSONB column, a file, redis) would actually persist.
    """

    def __init__(self, seed: dict[str, str] | None = None) -> None:
        self._store: dict[str, str] = dict(seed or {})

    def save_checkpoint(self, run_id: str, state: dict[str, object]) -> None:
        self._store[run_id] = json.dumps(state, sort_keys=True)

    def load_checkpoint(self, run_id: str) -> dict[str, object] | None:
        raw = self._store.get(run_id)
        return json.loads(raw) if raw is not None else None

    def clear_checkpoint(self, run_id: str) -> None:
        self._store.pop(run_id, None)

    def list_orphaned(self) -> list[str]:
        return list(self._store.keys())

    def durable_snapshot(self) -> dict[str, str]:
        """The genuinely-durable artifact: raw JSON strings, nothing else."""
        return dict(self._store)


def _fresh_store_from_durable_bytes(
    pre_crash_store: _DurableJsonCheckpointStore,
) -> _DurableJsonCheckpointStore:
    """Simulates a REAL cross-process hand-off: serialize the durable
    snapshot to actual ``bytes``, then build a BRAND NEW store instance by
    decoding those bytes -- never touching the pre-crash store's live
    Python dict or its ``CheckpointWriter``/``ThinRuntime`` objects."""
    durable_bytes = json.dumps(pre_crash_store.durable_snapshot()).encode("utf-8")
    return _DurableJsonCheckpointStore(seed=json.loads(durable_bytes.decode("utf-8")))


class _WriteFailureInjectingProvider:
    """Wraps a REAL ``ScratchpadProvider`` (``FileScratchpadProvider``,
    genuine disk I/O) and injects a controlled write failure for specific
    keys ONLY -- every other read/write goes through the real, durable,
    file-backed provider untouched. Lets a SINGLE pre-crash run genuinely
    produce BOTH a successful frozen offload projection AND a write-failure
    fallback (Stage 4's two separate maps), never a vacuous ``{}`` for
    either."""

    def __init__(self, inner: FileScratchpadProvider, fail_keys: set[str]) -> None:
        self._inner = inner
        self._fail_keys = fail_keys

    async def write(self, key: str, content: str, tags: tuple[str, ...] = ()) -> Any:
        if key in self._fail_keys:
            raise OSError("simulated disk-full write failure")
        return await self._inner.write(key, content, tags=tags)

    async def read(self, key: str) -> Any:
        return await self._inner.read(key)


class _CrashingLlm:
    """Returns each scripted response once, then RAISES -- simulates the
    process dying mid-run (an unhandled exception at the LLM-call boundary),
    after whatever checkpoint state the prior steps already wrote durably."""

    def __init__(self, raws: list[str]) -> None:
        self._raws = list(raws)
        self.received_prompts: list[str] = []

    async def __call__(self, messages: list, prompt: str, **kwargs: object) -> str:
        self.received_prompts.append(prompt)
        if not self._raws:
            raise RuntimeError("simulated crash mid-run")
        return self._raws.pop(0)


class _SequencedLlm:
    """Returns each scripted response once, then repeats the last forever."""

    def __init__(self, raws: list[str]) -> None:
        self._raws = list(raws)
        self.received_prompts: list[str] = []

    async def __call__(self, messages: list, prompt: str, **kwargs: object) -> str:
        self.received_prompts.append(prompt)
        return self._raws.pop(0) if len(self._raws) > 1 else self._raws[-1]


def _make_config(
    writer: CheckpointPort, run_id: str, provider: object
) -> RuntimeConfig:
    checkpoint_writer = (
        writer
        if isinstance(writer, CheckpointWriter)
        else CheckpointWriter(writer, namespace="sw:")
    )
    return RuntimeConfig(
        runtime_name="thin",
        model="openrouter:google/gemini-3.5-flash",
        max_iterations=6,
        max_tool_calls=8,
        # threshold_tokens=50 guarantees Tier 2 genuinely attempts to fire
        # against `_INITIAL_MESSAGES` -- compression_history ends up
        # non-empty, never a vacuous []==[].
        compaction=CompactionConfig(threshold_tokens=50, preserve_recent_pairs=0),
        checkpoint_writer=checkpoint_writer,
        run_id=run_id,
        native_config={
            "scratchpad_provider": provider,
            "context_window_tokens": 100_000,  # >= LARGE_WINDOW_TOKENS, enables offload
            "compaction_llm_model": "weak-model-for-compaction",  # Tier 2 works w/o coding_profile
        },
    )


def _make_backcompat_config(
    writer: CheckpointPort, run_id: str, provider: object
) -> RuntimeConfig:
    """Offload-enabled (same as ``_make_config``) but WITHOUT
    ``compaction_llm_model`` -- Tier 2 never fires (``_compaction_llm_call``
    stays ``None``), so ``_compaction_compression_history`` starts and stays
    ``[]`` for the backward-compat tests (their subject is tool-schema/
    offload graceful-degradation from an OLD checkpoint, not compaction)."""
    checkpoint_writer = (
        writer
        if isinstance(writer, CheckpointWriter)
        else CheckpointWriter(writer, namespace="sw:")
    )
    return RuntimeConfig(
        runtime_name="thin",
        model="openrouter:google/gemini-3.5-flash",
        max_iterations=6,
        max_tool_calls=8,
        compaction=CompactionConfig(threshold_tokens=50, preserve_recent_pairs=0),
        checkpoint_writer=checkpoint_writer,
        run_id=run_id,
        native_config={
            "scratchpad_provider": provider,
            "context_window_tokens": 100_000,
        },
    )


def _assert_genuine_crash(events: list) -> None:
    """codex R2 [MAJOR crash-specificity]: assert the SPECIFIC injected
    crash fired, not just ANY ``error`` event -- an unrelated early failure
    must not be silently accepted as "the expected crash"."""
    error_event = next(ev for ev in events if getattr(ev, "type", None) == "error")
    assert error_event.data["kind"] == "runtime_crash"
    assert "simulated crash mid-run" in error_event.data["message"]


class TestByteEquivalentCrashRecoveryGenuine:
    """DoD #1: kill mid-run (after offload+compaction genuinely happened,
    including a write-failure fallback) -> reclaim -> resume through
    COMPLETELY FRESH instances built from REAL durably-serialized bytes ->
    context is byte-equivalent to an ACCIDENT-FREE run (codex R2 [BLOCKER]:
    NOT to another resume -- a deterministic defect on both sides of a
    resume-vs-resume comparison would stay green), across ALL THREE Stage
    3/4/6 checkpoint components plus the LLM-facing message history."""

    @pytest.mark.asyncio
    async def test_crash_then_fresh_resume_matches_accident_free_baseline(
        self, tmp_path: Path
    ) -> None:
        baseline_dir = tmp_path / "baseline"
        crash_dir = tmp_path / "crash"

        # --- Baseline: ONE continuous ThinRuntime.run() call, single
        # process, NO crash, NO durable round-trip at any point -- the
        # accident-free reference the plan's DoD actually asks for.
        real_provider_baseline = FileScratchpadProvider(base_dir=baseline_dir)
        provider_baseline = _WriteFailureInjectingProvider(
            real_provider_baseline, fail_keys={"tool:c2"}
        )
        store_baseline = _DurableJsonCheckpointStore()
        run_id_baseline = "run-baseline"
        config_baseline = _make_config(
            store_baseline, run_id_baseline, provider_baseline
        )
        llm_baseline = _SequencedLlm(
            [
                _COMPACTION_PRIME,
                _tool_call_envelope("big_tool", "c1"),
                _tool_call_envelope("big_tool", "c2"),
                _final_envelope("done"),
            ]
        )
        runtime_baseline = ThinRuntime(
            config=config_baseline,
            llm_call=llm_baseline,
            local_tools={"big_tool": _big_tool},
        )
        baseline_events = [
            ev
            async for ev in runtime_baseline.run(
                messages=_INITIAL_MESSAGES,
                system_prompt="sys",
                active_tools=_TOOLS,
                config=config_baseline,
            )
        ]
        assert any(getattr(ev, "type", None) == "final" for ev in baseline_events), (
            "sanity: the accident-free baseline must genuinely reach final "
            "in a single continuous call"
        )
        baseline_state = store_baseline.load_checkpoint("sw:" + run_id_baseline)
        assert baseline_state is not None

        # --- Crash + fresh-instance resume: Call A crashes (GENUINE
        # unhandled exception, same 2 tool rounds -- c1 offloads, c2's
        # scratchpad write fails -> fallback); Call B uses COMPLETELY FRESH
        # instances built from real serialized bytes and a real fresh
        # FileScratchpadProvider pointed at the SAME real directory.
        real_provider_crash = FileScratchpadProvider(base_dir=crash_dir)
        provider_crash = _WriteFailureInjectingProvider(
            real_provider_crash, fail_keys={"tool:c2"}
        )
        store_crash = _DurableJsonCheckpointStore()
        run_id_crash = "run-crash"
        config_crash = _make_config(store_crash, run_id_crash, provider_crash)
        llm_crash = _CrashingLlm(
            [
                _COMPACTION_PRIME,
                _tool_call_envelope("big_tool", "c1"),
                _tool_call_envelope("big_tool", "c2"),
            ]
        )
        runtime_crash = ThinRuntime(
            config=config_crash, llm_call=llm_crash, local_tools={"big_tool": _big_tool}
        )
        crash_events = [
            ev
            async for ev in runtime_crash.run(
                messages=_INITIAL_MESSAGES,
                system_prompt="sys",
                active_tools=_TOOLS,
                config=config_crash,
            )
        ]
        _assert_genuine_crash(crash_events)

        # Capture the PRE-CRASH compression_history record BEFORE the
        # fresh-process handoff. This is the byte-equality anchor fix-cycle 3
        # needs: codex R3 proved that comparing the resumed side's history
        # via *containment* against the baseline's entry is vacuous here,
        # because both the pre-crash attempt and the resume-side's own
        # from-scratch compaction attempt operate on IDENTICAL input
        # (`_COMPACTION_PRIME` against the same `_INITIAL_MESSAGES`) and
        # therefore produce NUMERICALLY IDENTICAL records -- even if the
        # pre-crash entry were completely LOST during restore, the resumed
        # side's own fresh entry would coincidentally satisfy containment.
        # Capturing the exact pre-crash record here and later asserting
        # `resumed_history[0] == pre_crash_record` (byte-equal) plus
        # `len(resumed_history) == 2` proves genuine RESTORATION of that
        # specific record, not coincidental regeneration.
        pre_crash_state = store_crash.load_checkpoint("sw:" + run_id_crash)
        assert pre_crash_state is not None
        pre_crash_record = pre_crash_state["_compaction_compression_history"][0]

        resumed_store = _fresh_store_from_durable_bytes(store_crash)
        resumed_writer = CheckpointWriter(resumed_store, namespace="sw:")
        resumed_provider = FileScratchpadProvider(
            base_dir=crash_dir
        )  # genuine fresh instance, real disk

        # Adversarial: the "live" tool list ACTIVELY DIFFERS on resume
        # (reordered, one description changed, one new tool added) --
        # simulates a redeploy between the crash and the reclaim.
        drifted_tools = [
            ToolSpec(
                name="scratch_read",
                description="read scratch",
                parameters={"type": "object", "properties": {}},
            ),
            ToolSpec(
                name="big_tool",
                description="CHANGED DESCRIPTION AFTER REDEPLOY",
                parameters={"type": "object", "properties": {}},
            ),
            ToolSpec(
                name="new_tool_added_after_restart",
                description="only exists post-crash",
                parameters={"type": "object", "properties": {}},
            ),
        ]
        config_resume = _make_config(resumed_writer, run_id_crash, resumed_provider)
        # `_COMPACTION_PRIME_RESUME` (distinct text from `_COMPACTION_PRIME`)
        # makes the resume-side's OWN from-scratch compaction attempt produce
        # a record that is genuinely DIFFERENT from the restored pre-crash
        # one -- required so the byte-equality assertion below cannot be
        # satisfied by coincidence.
        llm_resume = _SequencedLlm([_COMPACTION_PRIME_RESUME, _final_envelope("done")])
        runtime_resume = ThinRuntime(
            config=config_resume,
            llm_call=llm_resume,
            local_tools={"big_tool": _big_tool},
        )
        async for _ in runtime_resume.run(
            messages=_INITIAL_MESSAGES,
            system_prompt="sys",
            active_tools=drifted_tools,
            config=config_resume,
        ):
            pass
        resumed_state = resumed_store.load_checkpoint("sw:" + run_id_crash)
        assert resumed_state is not None

        # --- Sanity: the recovery-critical fields are genuinely NON-EMPTY
        # (never a vacuous []==[]/{}=={} comparison).
        assert baseline_state["_compaction_compression_history"], (
            "sanity: compression_history must be genuinely non-empty -- "
            "Tier 2 must have actually attempted a compaction"
        )
        assert baseline_state["_tool_result_offload"], (
            "sanity: at least one successful frozen offload projection must exist"
        )
        assert baseline_state["_tool_result_offload_fallbacks"], (
            "sanity: the write-failure fallback map must be genuinely non-empty"
        )

        # --- Byte-equivalence (accident-free baseline vs crash+resume) via
        # CANONICAL JSON (never raw Python `==` on live objects), for every
        # field that is legitimately 1:1 comparable regardless of how many
        # `run()` invocations were needed to get there.
        for key in (
            "_tool_schema_snapshot",
            "_tool_result_offload",
            "_tool_result_offload_fallbacks",
            "iterations",
            "tool_calls_count",
            "_step",
            "_total_steps",
            "lm_messages",
        ):
            baseline_canonical = json.dumps(baseline_state[key], sort_keys=True)
            resumed_canonical = json.dumps(resumed_state[key], sort_keys=True)
            assert baseline_canonical == resumed_canonical, (
                f"{key} diverged between the accident-free baseline and "
                f"crash-then-resume:\n  baseline={baseline_canonical}\n  resumed={resumed_canonical}"
            )

        # --- `_compaction_compression_history`: the ONE field that
        # legitimately differs in ENTRY COUNT -- compaction is invoked once
        # PER `ThinRuntime.run()` call, not once per logical turn. The
        # baseline needed exactly 1 call to reach final; the crash+resume
        # scenario inherently needed 2 (the crash forces a retry call), so
        # its compaction step legitimately attempts (and records) twice.
        #
        # Fix-cycle 3 (codex R3): a plain CONTAINMENT check here
        # (`baseline_entry in resumed_entries`) is VACUOUS, because the
        # resume-side's own from-scratch compaction attempt was, until this
        # fix, run against IDENTICAL input to the pre-crash attempt and
        # therefore produced a NUMERICALLY IDENTICAL record -- so even if
        # the pre-crash entry were completely LOST during checkpoint
        # restore, the resumed side's own fresh entry would coincidentally
        # satisfy containment (codex confirmed this via mutation: deleting
        # the pre-crash history did NOT redden the old assertion).
        #
        # The fix: (a) `_COMPACTION_PRIME_RESUME` makes the resume-side's
        # own attempt genuinely DIFFERENT from the pre-crash one; (b) we
        # captured `pre_crash_record` BEFORE the fresh-process handoff;
        # (c) we now assert an exact PREFIX + APPEND shape -- the resumed
        # history must have exactly 2 entries, the FIRST must be BYTE-EQUAL
        # to the captured pre-crash record (proving genuine RESTORATION, not
        # regeneration), and the SECOND must be the distinguishable new
        # post-crash entry.
        resumed_history = resumed_state["_compaction_compression_history"]
        assert len(resumed_history) == 2, (
            "expected exactly 2 entries (restored pre-crash + new post-resume "
            f"attempt), got {len(resumed_history)}: {resumed_history}"
        )
        pre_crash_canonical = json.dumps(pre_crash_record, sort_keys=True)
        resumed_first_canonical = json.dumps(resumed_history[0], sort_keys=True)
        assert resumed_first_canonical == pre_crash_canonical, (
            "the FIRST entry in the resumed history must be BYTE-EQUAL to "
            "the pre-crash record captured before the fresh-process handoff "
            "-- this proves genuine RESTORATION from the durable checkpoint, "
            "not coincidental regeneration -- got "
            f"pre_crash={pre_crash_canonical!r}, resumed_first={resumed_first_canonical!r}"
        )
        resumed_second_canonical = json.dumps(resumed_history[1], sort_keys=True)
        assert resumed_second_canonical != pre_crash_canonical, (
            "the SECOND (post-resume) compaction attempt must be genuinely "
            "distinguishable from the restored pre-crash entry -- otherwise "
            "the two entries could be confused and the byte-equality proof "
            "above would not be meaningful -- got "
            f"resumed_second={resumed_second_canonical!r}"
        )

        # --- Payload-level proof: the ACTUAL prompt sent to the LLM on
        # resume used the PINNED (pre-crash) tool schema, not the drifted
        # "live" list -- checked across every captured prompt (compaction's
        # own summarization call has no tool info, so search all of them).
        assert any(
            "original-big-tool-marker" in p for p in llm_resume.received_prompts
        ), "resumed prompt never mentioned the PINNED tool description at all"
        assert all(
            "CHANGED DESCRIPTION AFTER REDEPLOY" not in p
            for p in llm_resume.received_prompts
        ), "resumed prompt used the DRIFTED tool description instead of the pinned one"
        assert all(
            "new_tool_added_after_restart" not in p for p in llm_resume.received_prompts
        ), (
            "resumed prompt exposed a tool that only exists in the post-crash drifted list"
        )

        # --- Manus file-context recovery: a THIRD, completely separate
        # FileScratchpadProvider instance re-reads c1's offloaded content
        # from REAL disk, by path -- never the in-process object that wrote it.
        reader_provider = FileScratchpadProvider(base_dir=crash_dir)
        c1_entry = await reader_provider.read("tool:c1")
        assert c1_entry is not None, (
            "offloaded content for call c1 was not durably persisted to disk"
        )
        assert c1_entry.content == _BIG_RESULT, (
            "re-read content diverged from what was actually offloaded"
        )


class TestRecitationAndMaskingSurviveCrash:
    """DoD #1 (recitation + masking equivalence): both mechanisms are
    CONFIG/HISTORY-derived (never separately persisted -- Stage 5's whole
    point), but this proves that property holds through a REAL crash
    boundary on the actual public API, not just the Stage 5 pure-function
    unit tests.

    Fix-cycle 2 (codex R2 [3], recitation was vacuous): the previous
    version's resume config still carried a ``RecitationInputFilter``, so
    "marker present in the resumed prompt" was true EVEN IF the checkpoint's
    ``lm_messages`` restore mechanism were completely broken (the filter
    would just re-derive it fresh, masking the very thing under test).
    Fixed: Call 2 (resume) carries NO recitation filter at all -- the marker
    can ONLY appear via genuine ``lm_messages`` restoration.
    """

    @pytest.mark.asyncio
    async def test_recitation_survives_via_genuine_checkpoint_restore_not_a_resume_side_filter(
        self,
    ) -> None:
        from swarmline.resilience.checkpoint import InMemoryCheckpointStore

        def _has_marker(lm_messages: list, marker: str) -> bool:
            for m in lm_messages:
                content = (
                    m.get("content")
                    if isinstance(m, dict)
                    else getattr(m, "content", "")
                )
                if marker in (content or ""):
                    return True
            return False

        store = InMemoryCheckpointStore()
        writer = CheckpointWriter(store, namespace="sw:")
        run_id = "run-recitation"
        messages = [
            Message(role="user", content="hello there")
        ]  # 1 human turn -> cadence fires
        tools = [
            ToolSpec(
                name="allowed_tool",
                description="allowed",
                parameters={"type": "object", "properties": {}},
            )
        ]

        config_pre_crash = RuntimeConfig(
            runtime_name="thin",
            model="openrouter:google/gemini-3.5-flash",
            max_iterations=4,
            max_tool_calls=4,
            checkpoint_writer=writer,
            run_id=run_id,
            input_filters=[RecitationInputFilter(plan_text="PLAN_MARKER_XYZ")],
        )

        async def _allowed_tool(**_: object) -> str:
            return "allowed-ok"

        class _ProbeThenCrash:
            def __init__(self) -> None:
                self._count = 0

            async def __call__(
                self, messages: list, prompt: str, **kwargs: object
            ) -> str:
                self._count += 1
                if self._count == 1:
                    return _tool_call_envelope("allowed_tool", "c1")
                raise RuntimeError("simulated crash mid-run")

        runtime_1 = ThinRuntime(
            config=config_pre_crash,
            llm_call=_ProbeThenCrash(),
            local_tools={"allowed_tool": _allowed_tool},
        )
        events_1 = [
            ev
            async for ev in runtime_1.run(
                messages=messages,
                system_prompt="sys",
                active_tools=tools,
                config=config_pre_crash,
            )
        ]
        _assert_genuine_crash(events_1)

        # --- Resume: a COMPLETELY FRESH ThinRuntime instance, and crucially
        # NO recitation filter configured at all -- the marker can ONLY show
        # up via the checkpoint's own `lm_messages` restore mechanism.
        config_resume = RuntimeConfig(
            runtime_name="thin",
            model="openrouter:google/gemini-3.5-flash",
            max_iterations=4,
            max_tool_calls=4,
            checkpoint_writer=writer,
            run_id=run_id,
            input_filters=[],  # deliberately empty -- see class docstring
        )
        received_messages: list[list] = []

        class _CapturingLlm:
            async def __call__(
                self, messages: list, prompt: str, **kwargs: object
            ) -> str:
                received_messages.append(list(messages))
                return _final_envelope("done")

        runtime_2 = ThinRuntime(
            config=config_resume,
            llm_call=_CapturingLlm(),
            local_tools={"allowed_tool": _allowed_tool},
        )
        async for _ in runtime_2.run(
            messages=messages,
            system_prompt="sys",
            active_tools=tools,
            config=config_resume,
        ):
            pass

        assert _has_marker(received_messages[-1], "PLAN_MARKER_XYZ"), (
            "recitation content must survive the crash boundary via genuine "
            "checkpoint lm_messages restoration -- resume had NO recitation "
            "filter configured, so its presence can only be explained by "
            "the restore mechanism actually working"
        )

    @pytest.mark.asyncio
    async def test_tool_masking_enforcement_identical_pre_and_post_crash(self) -> None:
        from swarmline.resilience.checkpoint import InMemoryCheckpointStore

        store = InMemoryCheckpointStore()
        writer = CheckpointWriter(store, namespace="sw:")
        run_id = "run-masking"
        messages = [Message(role="user", content="hello there")]
        tools = [
            ToolSpec(
                name="allowed_tool",
                description="allowed",
                parameters={"type": "object", "properties": {}},
            ),
            ToolSpec(
                name="masked_tool",
                description="masked out this stage",
                parameters={"type": "object", "properties": {}},
            ),
        ]
        config = RuntimeConfig(
            runtime_name="thin",
            model="openrouter:google/gemini-3.5-flash",
            max_iterations=4,
            max_tool_calls=4,
            checkpoint_writer=writer,
            run_id=run_id,
            native_config={"stage_enabled_tool_names": ["allowed_tool"]},
        )

        async def _allowed_tool(**_: object) -> str:
            return "allowed-ok"

        async def _masked_tool(**_: object) -> str:
            return "SHOULD NEVER RUN"

        class _MaskProbeThenCrash:
            def __init__(self) -> None:
                self._count = 0

            async def __call__(
                self, messages: list, prompt: str, **kwargs: object
            ) -> str:
                self._count += 1
                if self._count == 1:
                    return _tool_call_envelope("masked_tool", "probe1")
                raise RuntimeError("simulated crash mid-run")

        runtime_1 = ThinRuntime(
            config=config,
            llm_call=_MaskProbeThenCrash(),
            local_tools={"allowed_tool": _allowed_tool, "masked_tool": _masked_tool},
        )
        events_1 = [
            ev
            async for ev in runtime_1.run(
                messages=messages,
                system_prompt="sys",
                active_tools=tools,
                config=config,
            )
        ]
        _assert_genuine_crash(events_1)
        pre_crash_deny = next(
            ev
            for ev in events_1
            if getattr(ev, "type", None) == "tool_call_finished"
            and ev.data.get("name") == "masked_tool"
        )
        assert pre_crash_deny.data["ok"] is False
        assert "недоступен" in pre_crash_deny.data["result_summary"]

        class _MaskProbeThenFinal:
            def __init__(self) -> None:
                self._count = 0

            async def __call__(
                self, messages: list, prompt: str, **kwargs: object
            ) -> str:
                self._count += 1
                if self._count == 1:
                    return _tool_call_envelope("masked_tool", "probe2")
                return _final_envelope("done")

        runtime_2 = ThinRuntime(
            config=config,
            llm_call=_MaskProbeThenFinal(),
            local_tools={"allowed_tool": _allowed_tool, "masked_tool": _masked_tool},
        )
        events_2 = [
            ev
            async for ev in runtime_2.run(
                messages=messages,
                system_prompt="sys",
                active_tools=tools,
                config=config,
            )
        ]
        resumed_deny = next(
            ev
            for ev in events_2
            if getattr(ev, "type", None) == "tool_call_finished"
            and ev.data.get("name") == "masked_tool"
        )
        assert resumed_deny.data["ok"] is False
        assert (
            resumed_deny.data["result_summary"] == pre_crash_deny.data["result_summary"]
        ), (
            "masking enforcement diverged between pre-crash and post-resume "
            "for the IDENTICAL native_config"
        )


class TestBackwardCompatOldCheckpoint:
    """DoD #3: a checkpoint written BEFORE Stage 3/4/6 shipped (missing
    ``_tool_schema_snapshot``/``_tool_result_offload``/
    ``_compaction_compression_history`` entirely) must resume WITHOUT
    crashing -- graceful degradation (fresh snapshot minted, empty
    offload maps, empty compression history), never a KeyError/crash.
    Uses ``_DurableJsonCheckpointStore`` too -- proves the OLD-shaped
    payload is itself genuinely JSON round-trippable (a legacy writer
    could realistically have produced exactly this shape on real disk)."""

    @pytest.mark.asyncio
    async def test_partial_legacy_checkpoint_resumes_without_crashing(
        self, tmp_path: Path
    ) -> None:
        """Shape predating Stage 3: only the fields ``_read_lm_messages``/
        ``tool_calls_count`` already read before Stage 3 existed."""
        store = _DurableJsonCheckpointStore()
        writer = CheckpointWriter(store, namespace="sw:")
        run_id = "run-backcompat-partial"
        await writer.after_tool_call(
            run_id=run_id,
            step=2,
            total_steps=6,
            state={"iterations": 2, "tool_calls_count": 2, "lm_messages": []},
        )

        provider = FileScratchpadProvider(base_dir=tmp_path)
        config = _make_backcompat_config(store, run_id, provider)
        llm = _SequencedLlm(
            [_tool_call_envelope("big_tool", "c1"), _final_envelope("done")]
        )
        runtime = ThinRuntime(
            config=config, llm_call=llm, local_tools={"big_tool": _big_tool}
        )
        events = [
            ev
            async for ev in runtime.run(
                messages=_INITIAL_MESSAGES,
                system_prompt="sys",
                active_tools=_TOOLS,
                config=config,
            )
        ]  # must NOT raise

        assert any(getattr(ev, "type", None) == "final" for ev in events)
        saved = store.load_checkpoint("sw:" + run_id)
        assert saved is not None
        assert saved["_tool_schema_snapshot"] is not None  # freshly minted, not crashed
        assert (
            "c1" in saved["_tool_result_offload"]
        )  # offload still works going forward
        assert (
            saved["_compaction_compression_history"] == []
        )  # Tier 2 never fires here (no compaction_llm_model)

    @pytest.mark.asyncio
    async def test_bare_minimum_legacy_checkpoint_resumes_without_crashing(
        self, tmp_path: Path
    ) -> None:
        """Absolute floor: a checkpoint containing ONLY what the ORIGINAL
        OSS-T4 substrate itself injects (``_step``/``_total_steps``), no
        caller-provided keys at all -- e.g. a checkpoint written by some
        even-older external tool against this same ``CheckpointPort``."""
        store = _DurableJsonCheckpointStore(
            seed={"sw:run-backcompat-bare": json.dumps({"_step": 0, "_total_steps": 0})}
        )
        run_id = "run-backcompat-bare"
        provider = FileScratchpadProvider(base_dir=tmp_path)

        config = _make_backcompat_config(store, run_id, provider)
        llm = _SequencedLlm(
            [_tool_call_envelope("big_tool", "c1"), _final_envelope("done")]
        )
        runtime = ThinRuntime(
            config=config, llm_call=llm, local_tools={"big_tool": _big_tool}
        )
        events = [
            ev
            async for ev in runtime.run(
                messages=_INITIAL_MESSAGES,
                system_prompt="sys",
                active_tools=_TOOLS,
                config=config,
            )
        ]  # must NOT raise

        assert any(getattr(ev, "type", None) == "final" for ev in events)
        saved = store.load_checkpoint("sw:" + run_id)
        assert saved is not None
        assert saved["_tool_schema_snapshot"] is not None
        assert saved["_compaction_compression_history"] == []
