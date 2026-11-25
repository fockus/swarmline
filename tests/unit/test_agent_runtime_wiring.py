"""Unit tests for shared portable runtime wiring helpers."""

from __future__ import annotations

from typing import Any

import pytest
from swarmline.agent.config import AgentConfig
from swarmline.agent.tool import tool
from swarmline.retry import ExponentialBackoff
from swarmline.runtime.cost import CostBudget
from swarmline.runtime.types import ModelRequestOptions, RuntimeConfig, ThinkingConfig
from swarmline.skills.types import McpServerSpec


def _make_config(**overrides: Any) -> AgentConfig:
    defaults = {"system_prompt": "test prompt"}
    defaults.update(overrides)
    return AgentConfig(**defaults)


class TestBuildPortableRuntimePlan:
    def test_maps_tool_executors_and_active_tools(self) -> None:
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        @tool(name="calc", description="Calculator")
        async def calc(expr: str) -> str:
            return "42"

        config = _make_config(runtime="thin", tools=(calc.__tool_definition__,))

        plan = build_portable_runtime_plan(config, "thin")

        assert plan.config.runtime_name == "thin"
        assert (
            plan.create_kwargs["tool_executors"]["calc"]
            is calc.__tool_definition__.handler
        )
        assert [spec.name for spec in plan.active_tools] == ["calc"]

    def test_includes_mcp_servers_for_mcp_capable_runtimes(self) -> None:
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        mcp_servers = {"iss": McpServerSpec(name="iss", url="https://iss.test")}
        for runtime in ("deepagents", "thin", "openai_agents"):
            config = _make_config(runtime=runtime, mcp_servers=mcp_servers)
            plan = build_portable_runtime_plan(config, runtime)
            assert plan.create_kwargs["mcp_servers"] == mcp_servers, runtime

    def test_cli_plan_never_receives_mcp_servers(self) -> None:
        """cli + mcp_servers is rejected at AgentConfig validation, so the
        wiring never sees it; a plan built without mcp_servers stays clean."""
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        cli_config = _make_config(runtime="cli")
        cli_plan = build_portable_runtime_plan(cli_config, "cli")
        assert "mcp_servers" not in cli_plan.create_kwargs

    def test_injects_thread_id_for_deepagents_sessions(self) -> None:
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        config = _make_config(
            runtime="deepagents", native_config={"checkpointer": object()}
        )

        plan = build_portable_runtime_plan(
            config,
            "deepagents",
            session_id="conv-thread-1",
        )

        assert (
            plan.config.native_config["checkpointer"]
            is config.native_config["checkpointer"]
        )
        assert plan.config.native_config["thread_id"] == "conv-thread-1"

    def test_preserves_dict_style_mcp_servers_for_portable_runtime(self) -> None:
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        mcp_servers = {"iss": {"type": "http", "url": "https://iss.test"}}
        config = _make_config(runtime="thin", mcp_servers=mcp_servers)

        plan = build_portable_runtime_plan(config, "thin")

        assert plan.create_kwargs["mcp_servers"] == mcp_servers

    def test_passes_structured_and_request_options_to_runtime_config(self) -> None:
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        request_options = ModelRequestOptions(max_tokens=777, timeout_sec=15.0)
        config = _make_config(
            runtime="thin",
            structured_mode="auto",
            structured_schema_name="custom_schema_v1",
            structured_strict=False,
            max_model_retries=4,
            request_options=request_options,
        )

        plan = build_portable_runtime_plan(config, "thin")

        assert plan.config.structured_mode == "auto"
        assert plan.config.structured_schema_name == "custom_schema_v1"
        assert plan.config.structured_strict is False
        assert plan.config.max_model_retries == 4
        assert plan.config.request_options is request_options

    def test_passes_base_url_to_runtime_config(self) -> None:
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        config = _make_config(runtime="thin", base_url="https://llm-proxy.test/v1")

        plan = build_portable_runtime_plan(config, "thin")

        assert plan.config.base_url == "https://llm-proxy.test/v1"

    def test_pi_sdk_runtime_options_are_passed_to_factory_kwargs(self) -> None:
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan
        from swarmline.runtime.pi_sdk.types import PiSdkOptions

        options = PiSdkOptions(toolset="readonly", cwd="/workspace")
        config = _make_config(runtime="pi_sdk", runtime_options=options)

        plan = build_portable_runtime_plan(config, "pi_sdk")

        assert plan.create_kwargs["pi_options"] is options

    def test_agent_config_retry_policy_default_none_runtime_unchanged(self) -> None:
        """No retry_policy on AgentConfig -> RuntimeConfig.retry_policy stays the
        untouched default (None), byte-identical to pre-passthrough behaviour."""
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        config = _make_config(runtime="thin")

        plan = build_portable_runtime_plan(config, "thin")

        assert config.retry_policy is None
        assert plan.config.retry_policy is None
        assert plan.config.retry_policy == RuntimeConfig().retry_policy

    def test_agent_config_retry_policy_passthrough_to_runtime_config(self) -> None:
        """An explicit AgentConfig.retry_policy is threaded through unchanged to
        the RuntimeConfig consumed by run_buffered_llm_call."""
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        policy = ExponentialBackoff(max_retries=5, base_delay=2.0)
        config = _make_config(runtime="thin", retry_policy=policy)

        plan = build_portable_runtime_plan(config, "thin")

        assert plan.config.retry_policy is policy


class TestResolveMcpServerUrl:
    def test_resolves_plain_dict_server_config(self) -> None:
        from swarmline.runtime.thin.mcp_client import resolve_mcp_server_url

        url = resolve_mcp_server_url(
            {"iss": {"type": "http", "url": "https://iss.test"}},
            "iss",
        )

        assert url == "https://iss.test"


# ---------------------------------------------------------------------------
# I-098a — Stage 1: thinking / cost_budget / resume_session_id / env
# translation from AgentConfig into the portable RuntimeConfig/create_kwargs.
# ---------------------------------------------------------------------------


class TestThinkingTranslation:
    """AgentConfig.thinking -> RuntimeConfig.thinking (thin/openai_agents/pi_sdk)."""

    @pytest.mark.parametrize("runtime", ["thin", "openai_agents", "pi_sdk"])
    def test_enabled_thinking_reaches_runtime_config(self, runtime: str) -> None:
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        config = _make_config(
            runtime=runtime, thinking=ThinkingConfig(budget_tokens=1024)
        )

        plan = build_portable_runtime_plan(config, runtime)

        assert plan.config.thinking is not None
        assert plan.config.thinking.budget_tokens == 1024

    def test_unset_thinking_leaves_runtime_config_thinking_none(self) -> None:
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        config = _make_config(runtime="thin")

        plan = build_portable_runtime_plan(config, "thin")

        assert plan.config.thinking is None

    def test_disabled_thinking_dict_translates_to_none(self) -> None:
        """Deprecated dict form {"type": "disabled"} means "no thinking budget",
        not a truthy RuntimeConfig.thinking."""
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        with pytest.deprecated_call():
            config = _make_config(runtime="thin", thinking={"type": "disabled"})

        plan = build_portable_runtime_plan(config, "thin")

        assert plan.config.thinking is None

    def test_empty_thinking_dict_is_enabled_with_default_budget_not_dropped(
        self,
    ) -> None:
        """The validator (factory.py) treats {} as ENABLED (type != "disabled"):
        the translation must not silently drop it via a falsy check."""
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        with pytest.deprecated_call():
            config = _make_config(runtime="thin", thinking={})

        plan = build_portable_runtime_plan(config, "thin")

        assert plan.config.thinking == ThinkingConfig(budget_tokens=10_000)

    def test_adaptive_thinking_dict_raises_value_error(self) -> None:
        """Adaptive thinking is claude_sdk-specific; portable runtimes have no
        equivalent, so it must fail loudly rather than silently coerce."""
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        with pytest.deprecated_call():
            config = _make_config(runtime="thin", thinking={"type": "adaptive"})

        with pytest.raises(ValueError, match="adaptive"):
            build_portable_runtime_plan(config, "thin")

    def test_zero_budget_tokens_raises_value_error(self) -> None:
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        with pytest.deprecated_call():
            config = _make_config(runtime="thin", thinking={"budget_tokens": 0})

        with pytest.raises(ValueError, match="0"):
            build_portable_runtime_plan(config, "thin")

    def test_string_budget_tokens_raises_value_error(self) -> None:
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        with pytest.deprecated_call():
            config = _make_config(runtime="thin", thinking={"budget_tokens": "2000"})

        with pytest.raises(ValueError, match="2000"):
            build_portable_runtime_plan(config, "thin")

    def test_bool_budget_tokens_raises_value_error(self) -> None:
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        with pytest.deprecated_call():
            config = _make_config(runtime="thin", thinking={"budget_tokens": True})

        with pytest.raises(ValueError, match="True"):
            build_portable_runtime_plan(config, "thin")

    def test_unknown_thinking_type_raises_value_error(self) -> None:
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        with pytest.deprecated_call():
            config = _make_config(runtime="thin", thinking={"type": "bogus"})

        with pytest.raises(ValueError, match="bogus"):
            build_portable_runtime_plan(config, "thin")

    def test_degraded_runtime_adaptive_thinking_does_not_raise_when_not_strict(
        self,
    ) -> None:
        """cli has no thinking_stream capability. Under strict_capabilities=False
        the capability validator only warns and degrades (drops thinking) --
        it must NOT then hit _resolve_thinking_config's stricter adaptive
        check and raise a second, unrelated ValueError (round-2 regression:
        baseline 3c503fb silently dropped adaptive thinking for cli)."""
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        with pytest.deprecated_call():
            config = _make_config(
                runtime="cli",
                thinking={"type": "adaptive"},
                strict_capabilities=False,
            )

        with pytest.warns(UserWarning, match="thinking"):
            plan = build_portable_runtime_plan(config, "cli")

        assert plan.config.thinking is None

    def test_degraded_runtime_invalid_budget_tokens_does_not_raise_when_not_strict(
        self,
    ) -> None:
        """Same degrade-not-raise contract for an invalid (non-int) budget on
        a runtime without the thinking_stream capability."""
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        with pytest.deprecated_call():
            config = _make_config(
                runtime="cli",
                thinking={"budget_tokens": "bogus"},
                strict_capabilities=False,
            )

        with pytest.warns(UserWarning, match="thinking"):
            plan = build_portable_runtime_plan(config, "cli")

        assert plan.config.thinking is None

    def test_degraded_runtime_valid_thinking_is_dropped_not_translated(self) -> None:
        """Even a perfectly valid budget must be dropped (not translated) for
        a degraded runtime -- degrade semantics = drop, matching baseline."""
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        with pytest.deprecated_call():
            config = _make_config(
                runtime="cli",
                thinking={"budget_tokens": 5000},
                strict_capabilities=False,
            )

        with pytest.warns(UserWarning, match="thinking"):
            plan = build_portable_runtime_plan(config, "cli")

        assert plan.config.thinking is None

    def test_capable_runtime_adaptive_thinking_still_raises_when_not_strict(
        self,
    ) -> None:
        """Guard: thin DOES have the thinking_stream capability, so no
        violation is ever raised by the validator for it -- the degrade path
        never applies, and _resolve_thinking_config's loud adaptive check
        must still fire regardless of strict_capabilities."""
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        with pytest.deprecated_call():
            config = _make_config(
                runtime="thin",
                thinking={"type": "adaptive"},
                strict_capabilities=False,
            )

        with pytest.raises(ValueError, match="adaptive"):
            build_portable_runtime_plan(config, "thin")


class TestCostBudgetTranslation:
    """AgentConfig.max_budget_usd -> RuntimeConfig.cost_budget (thin/pi_sdk)."""

    @pytest.mark.parametrize("runtime", ["thin", "pi_sdk"])
    def test_max_budget_usd_builds_cost_budget(self, runtime: str) -> None:
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        config = _make_config(runtime=runtime, max_budget_usd=1.5)

        plan = build_portable_runtime_plan(config, runtime)

        assert plan.config.cost_budget == CostBudget(
            max_cost_usd=1.5, action_on_exceed="error"
        )

    def test_unset_max_budget_usd_leaves_cost_budget_none(self) -> None:
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        config = _make_config(runtime="thin")

        plan = build_portable_runtime_plan(config, "thin")

        assert plan.config.cost_budget is None


class TestResumeSessionIdTranslation:
    """AgentConfig.resume_session_id -> pi_sdk extra / deepagents thread_id."""

    def test_pi_sdk_resume_session_id_maps_to_pi_session_file_extra(self) -> None:
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        config = _make_config(runtime="pi_sdk", resume_session_id="sess-0001")

        plan = build_portable_runtime_plan(config, "pi_sdk")

        assert plan.config.extra["pi_session_file"] == "sess-0001"

    def test_deepagents_resume_session_id_maps_to_thread_id(self) -> None:
        """resume_session_id requires deepagents' native-mode + checkpointer
        gate (capabilities.py `_resolve_deepagents`) to pass validation."""
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        config = _make_config(
            runtime="deepagents",
            resume_session_id="sess-0001",
            allow_native_features=True,
            native_config={"checkpointer": object()},
        )

        plan = build_portable_runtime_plan(config, "deepagents")

        assert plan.config.native_config["thread_id"] == "sess-0001"

    def test_deepagents_resume_session_id_takes_priority_over_session_id_param(
        self,
    ) -> None:
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        config = _make_config(
            runtime="deepagents",
            resume_session_id="sess-explicit",
            allow_native_features=True,
            native_config={"checkpointer": object()},
        )

        plan = build_portable_runtime_plan(
            config, "deepagents", session_id="conv-thread-1"
        )

        assert plan.config.native_config["thread_id"] == "sess-explicit"

    def test_deepagents_session_id_param_used_when_no_resume_session_id(self) -> None:
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        config = _make_config(runtime="deepagents")

        plan = build_portable_runtime_plan(
            config, "deepagents", session_id="conv-thread-1"
        )

        assert plan.config.native_config["thread_id"] == "conv-thread-1"


class TestEnvTranslation:
    """AgentConfig.env -> extra["env"], subprocess runtimes only (pi_sdk/cli)."""

    @pytest.mark.parametrize("runtime", ["pi_sdk", "cli"])
    def test_env_reaches_extra_for_subprocess_runtimes(self, runtime: str) -> None:
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        config = _make_config(runtime=runtime, env={"SWARMLINE_CONTRACT_PROBE": "1"})

        plan = build_portable_runtime_plan(config, runtime)

        assert plan.config.extra["env"] == {"SWARMLINE_CONTRACT_PROBE": "1"}

    @pytest.mark.parametrize("runtime", ["thin", "deepagents", "openai_agents"])
    def test_env_does_not_silently_appear_for_non_subprocess_runtimes(
        self, runtime: str
    ) -> None:
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        config = _make_config(runtime=runtime, env={"SWARMLINE_CONTRACT_PROBE": "1"})

        plan = build_portable_runtime_plan(config, runtime)

        assert "env" not in plan.config.extra

    def test_empty_env_does_not_add_extra_key_for_pi_sdk(self) -> None:
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        config = _make_config(runtime="pi_sdk")

        plan = build_portable_runtime_plan(config, "pi_sdk")

        assert "env" not in plan.config.extra


async def _probe_can_use_tool(
    tool_name: str, tool_input: dict[str, Any], context: Any
) -> Any:
    return {"behavior": "allow"}


class TestCanUseToolTranslation:
    """AgentConfig.can_use_tool -> create_kwargs["can_use_tool"], thin only (I-098b)."""

    def test_thin_can_use_tool_reaches_create_kwargs(self) -> None:
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        config = _make_config(runtime="thin", can_use_tool=_probe_can_use_tool)

        plan = build_portable_runtime_plan(config, "thin")

        assert plan.create_kwargs["can_use_tool"] is _probe_can_use_tool

    def test_unset_can_use_tool_does_not_add_create_kwargs_key(self) -> None:
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        config = _make_config(runtime="thin")

        plan = build_portable_runtime_plan(config, "thin")

        assert "can_use_tool" not in plan.create_kwargs

    @pytest.mark.parametrize(
        "runtime", ["deepagents", "openai_agents", "pi_sdk", "cli", "temporal"]
    )
    def test_other_runtimes_reject_can_use_tool_at_capability_validation(
        self, runtime: str
    ) -> None:
        """Only claude_sdk/thin declare the ``permissions`` capability: the
        other portable runtimes must reject can_use_tool loudly at validation
        rather than silently accepting a callback nothing will ever invoke."""
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        config = _make_config(runtime=runtime, can_use_tool=_probe_can_use_tool)

        with pytest.raises(ValueError, match="can_use_tool"):
            build_portable_runtime_plan(config, runtime)


class _NoCapsFactory:
    """Minimal custom RuntimeFactoryPort whose get_capabilities returns None.

    Mirrors real downstream test fakes (pre-v2-capabilities contract) that
    satisfy the structural Protocol but never registered capability metadata.
    """

    def validate_agent_config(self, config: Any) -> None:
        return None

    def resolve_agent_model(self, config: Any) -> str:
        return "scripted-model"

    def get_capabilities(
        self, config: Any | None = None, runtime_override: str | None = None
    ) -> Any:
        return None

    def validate_capabilities(self, *args: Any, **kwargs: Any) -> Any:
        return None

    def create(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("plan building must not create a runtime")


class TestCustomFactoryWithoutCapabilities:
    """Regression: the I-098a thinking gate crashed on custom factories whose
    get_capabilities returns None (AttributeError: NoneType .resolve)."""

    def test_none_capabilities_factory_builds_plan_without_thinking(self) -> None:
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        config = _make_config(runtime="thin")

        plan = build_portable_runtime_plan(
            config, "thin", runtime_factory=_NoCapsFactory()
        )

        assert plan.config.thinking is None

    def test_none_capabilities_factory_keeps_thinking_translation(self) -> None:
        """Pre-I-098a baseline for capability-less factories: `thinking` is
        translated unconditionally, not silently dropped."""
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        config = _make_config(
            runtime="thin", thinking=ThinkingConfig(budget_tokens=1024)
        )

        plan = build_portable_runtime_plan(
            config, "thin", runtime_factory=_NoCapsFactory()
        )

        assert plan.config.thinking == ThinkingConfig(budget_tokens=1024)
