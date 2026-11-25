"""Tests for Stage 6 (context-engineering-manus-parity) Ступень B — compaction
cascade wiring in agent/runtime_wiring.py: RuntimeConfig.compaction threading
via AgentConfig.native_config, generic opt-in (not gated on coding_profile),
closing the same composition-root wiring gap shape as BL-77."""

from __future__ import annotations

from swarmline.agent.config import AgentConfig
from swarmline.agent.runtime_wiring import build_portable_runtime_plan
from swarmline.compaction import CompactionConfig


class TestCompactionWiring_Absent:
    def test_absent_flag_is_a_hard_no_op(self) -> None:
        """No native_config key -> RuntimeConfig.compaction stays None,
        byte-identical to pre-Stage-6 behaviour."""
        cfg = AgentConfig(system_prompt="test", runtime="thin", cwd="/tmp/test-coding")
        plan = build_portable_runtime_plan(cfg, "thin")
        assert plan.config.compaction is None

    def test_falsy_flag_is_a_hard_no_op(self) -> None:
        cfg = AgentConfig(
            system_prompt="test",
            runtime="thin",
            cwd="/tmp/test-coding",
            native_config={"compaction_enabled": False},
        )
        plan = build_portable_runtime_plan(cfg, "thin")
        assert plan.config.compaction is None

    def test_not_gated_on_coding_profile(self) -> None:
        cfg = AgentConfig(
            system_prompt="test",
            runtime="thin",
            cwd="/tmp/test-coding",
            native_config={"compaction_enabled": True},
        )
        assert cfg.coding_profile is None
        plan = build_portable_runtime_plan(cfg, "thin")
        assert isinstance(plan.config.compaction, CompactionConfig)


class TestCompactionWiring_Present:
    def test_enabled_flag_builds_default_config(self) -> None:
        cfg = AgentConfig(
            system_prompt="test",
            runtime="thin",
            cwd="/tmp/test-coding",
            native_config={"compaction_enabled": True},
        )
        plan = build_portable_runtime_plan(cfg, "thin")
        compaction = plan.config.compaction
        assert compaction is not None
        assert compaction.threshold_tokens == CompactionConfig().threshold_tokens
        assert compaction.context_window_tokens is None

    def test_threshold_tokens_threaded(self) -> None:
        cfg = AgentConfig(
            system_prompt="test",
            runtime="thin",
            cwd="/tmp/test-coding",
            native_config={
                "compaction_enabled": True,
                "compaction_threshold_tokens": 12_345,
            },
        )
        plan = build_portable_runtime_plan(cfg, "thin")
        assert plan.config.compaction.threshold_tokens == 12_345

    def test_context_window_and_reserve_threaded(self) -> None:
        cfg = AgentConfig(
            system_prompt="test",
            runtime="thin",
            cwd="/tmp/test-coding",
            native_config={
                "compaction_enabled": True,
                "compaction_context_window_tokens": 50_000,
                "compaction_max_output_reserve_tokens": 4_000,
            },
        )
        plan = build_portable_runtime_plan(cfg, "thin")
        compaction = plan.config.compaction
        assert compaction.context_window_tokens == 50_000
        assert compaction.max_output_reserve_tokens == 4_000
        assert compaction.effective_threshold_tokens == 46_000

    def test_preserve_recent_pairs_threaded(self) -> None:
        cfg = AgentConfig(
            system_prompt="test",
            runtime="thin",
            cwd="/tmp/test-coding",
            native_config={
                "compaction_enabled": True,
                "compaction_preserve_recent_pairs": 7,
            },
        )
        plan = build_portable_runtime_plan(cfg, "thin")
        assert plan.config.compaction.preserve_recent_pairs == 7

    def test_compactable_tool_names_threaded(self) -> None:
        cfg = AgentConfig(
            system_prompt="test",
            runtime="thin",
            cwd="/tmp/test-coding",
            native_config={
                "compaction_enabled": True,
                "compaction_compactable_tool_names": ["read_file", "grep"],
            },
        )
        plan = build_portable_runtime_plan(cfg, "thin")
        assert plan.config.compaction.compactable_tool_names == frozenset(
            {"read_file", "grep"}
        )

    def test_defaults_used_when_only_flag_set(self) -> None:
        """Every optional key is independently defaulted from CompactionConfig
        itself -- no silently-drifting duplicate literal defaults."""
        cfg = AgentConfig(
            system_prompt="test",
            runtime="thin",
            cwd="/tmp/test-coding",
            native_config={"compaction_enabled": True},
        )
        plan = build_portable_runtime_plan(cfg, "thin")
        compaction = plan.config.compaction
        default = CompactionConfig()
        assert compaction.max_output_reserve_tokens == default.max_output_reserve_tokens
        assert compaction.preserve_recent_pairs == default.preserve_recent_pairs
        assert compaction.compactable_tool_names == default.compactable_tool_names


class TestCompactionWiring_DedupEnabled:
    """BL-81: Ступень A (Tier-0 hash-dedup) is fully implemented and unit-tested
    in CompactionConfig, but was unreachable through the composition root — every
    other CompactionConfig knob had a native_config key and this one did not, so
    a host could only turn it on by hand-building CompactionConfig."""

    def test_dedup_key_absent_keeps_the_conservative_default(self) -> None:
        """Opting into compaction must NOT silently add a new tier: a caller who
        sets only compaction_enabled still gets dedup_enabled=False."""
        cfg = AgentConfig(
            system_prompt="test",
            runtime="thin",
            cwd="/tmp/test-coding",
            native_config={"compaction_enabled": True},
        )
        plan = build_portable_runtime_plan(cfg, "thin")
        assert plan.config.compaction is not None
        assert plan.config.compaction.dedup_enabled is CompactionConfig().dedup_enabled
        assert plan.config.compaction.dedup_enabled is False

    def test_dedup_key_true_reaches_compaction_config(self) -> None:
        cfg = AgentConfig(
            system_prompt="test",
            runtime="thin",
            cwd="/tmp/test-coding",
            native_config={
                "compaction_enabled": True,
                "compaction_dedup_enabled": True,
            },
        )
        plan = build_portable_runtime_plan(cfg, "thin")
        assert plan.config.compaction is not None
        assert plan.config.compaction.dedup_enabled is True

    def test_dedup_key_false_is_respected(self) -> None:
        cfg = AgentConfig(
            system_prompt="test",
            runtime="thin",
            cwd="/tmp/test-coding",
            native_config={
                "compaction_enabled": True,
                "compaction_dedup_enabled": False,
            },
        )
        plan = build_portable_runtime_plan(cfg, "thin")
        assert plan.config.compaction is not None
        assert plan.config.compaction.dedup_enabled is False

    def test_non_bool_dedup_value_falls_back_to_default(self) -> None:
        """Same defensive shape as the other knobs: a wrong-typed value must not
        crash the composition root, it falls back to the conservative default."""
        cfg = AgentConfig(
            system_prompt="test",
            runtime="thin",
            cwd="/tmp/test-coding",
            native_config={
                "compaction_enabled": True,
                "compaction_dedup_enabled": "yes",
            },
        )
        plan = build_portable_runtime_plan(cfg, "thin")
        assert plan.config.compaction is not None
        assert plan.config.compaction.dedup_enabled is False
