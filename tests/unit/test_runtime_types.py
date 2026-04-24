"""Tests for runtime types - Message, ToolSpec, RuntimeEvent, RuntimeErrorData, RuntimeConfig, resolve_model_name."""

import pytest
from swarmline.runtime.types import (
    DEFAULT_MODEL,
    ModelRequestOptions,
    RUNTIME_ERROR_KINDS,
    RUNTIME_EVENT_TYPES,
    Message,
    RuntimeConfig,
    RuntimeErrorData,
    RuntimeEvent,
    ToolSpec,
    TurnMetrics,
    resolve_model_name,
)

# ---------------------------------------------------------------------------
# Message
# ---------------------------------------------------------------------------


class TestMessage:
    """Message - universalnoe message for AgentRuntime."""

    def test_user_message(self) -> None:
        msg = Message(role="user", content="Привет!")
        assert msg.role == "user"
        assert msg.content == "Привет!"
        assert msg.name is None
        assert msg.tool_calls is None
        assert msg.metadata is None

    def test_tool_message(self) -> None:
        msg = Message(
            role="tool",
            content='{"rate": 12.5}',
            name="mcp__finuslugi__get_bank_deposits",
        )
        assert msg.role == "tool"
        assert msg.name == "mcp__finuslugi__get_bank_deposits"

    def test_to_dict_minimal(self) -> None:
        msg = Message(role="user", content="test")
        d = msg.to_dict()
        assert d == {"role": "user", "content": "test"}
        assert "name" not in d
        assert "metadata" not in d

    def test_to_dict_full(self) -> None:
        msg = Message(
            role="tool",
            content="result",
            name="calc",
            tool_calls=[{"id": "1"}],
            metadata={"ts": 123},
        )
        d = msg.to_dict()
        assert d["name"] == "calc"
        assert d["tool_calls"] == [{"id": "1"}]
        assert d["metadata"] == {"ts": 123}

    def test_from_memory_message(self) -> None:
        """Conversion from MemoryMessage (backward compat)."""
        from swarmline.memory.types import MemoryMessage

        mm = MemoryMessage(role="assistant", content="Ответ", tool_calls=[{"t": 1}])
        msg = Message.from_memory_message(mm)
        assert msg.role == "assistant"
        assert msg.content == "Ответ"
        assert msg.tool_calls == [{"t": 1}]
        assert msg.name is None

    def test_frozen(self) -> None:
        msg = Message(role="user", content="x")
        with pytest.raises(AttributeError):
            msg.role = "assistant"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ToolSpec
# ---------------------------------------------------------------------------


class TestToolSpec:
    """ToolSpec - opisanie toola."""

    def test_mcp_tool(self) -> None:
        spec = ToolSpec(
            name="mcp__iss__get_bonds",
            description="Получить список облигаций",
            parameters={"type": "object", "properties": {"query": {"type": "string"}}},
        )
        assert spec.name == "mcp__iss__get_bonds"
        assert spec.is_local is False

    def test_local_tool(self) -> None:
        spec = ToolSpec(
            name="calculate_goal_plan",
            description="Рассчитать план",
            parameters={"type": "object"},
            is_local=True,
        )
        assert spec.is_local is True

    def test_to_dict(self) -> None:
        spec = ToolSpec(name="t", description="d", parameters={}, is_local=True)
        d = spec.to_dict()
        assert d["name"] == "t"
        assert d["is_local"] is True


# ---------------------------------------------------------------------------
# RuntimeErrorData
# ---------------------------------------------------------------------------


class TestRuntimeErrorData:
    """RuntimeErrorData - tipizirovannaya error."""

    def test_valid_kind(self) -> None:
        err = RuntimeErrorData(kind="loop_limit", message="Превышен лимит итераций")
        assert err.kind == "loop_limit"
        assert err.recoverable is False

    def test_unknown_kind_fallback(self) -> None:
        """Notizvestnyy kind -> avtozamena on runtime_crash."""
        err = RuntimeErrorData(kind="unknown_kind", message="test")
        assert err.kind == "runtime_crash"

    def test_to_dict(self) -> None:
        err = RuntimeErrorData(
            kind="mcp_timeout",
            message="timeout",
            recoverable=True,
            details={"server": "iss"},
        )
        d = err.to_dict()
        assert d["kind"] == "mcp_timeout"
        assert d["recoverable"] is True
        assert d["details"]["server"] == "iss"

    def test_all_kinds_exist(self) -> None:
        """Vse zayavlennye kinds available."""
        expected = {
            "runtime_crash",
            "bad_model_output",
            "loop_limit",
            "budget_exceeded",
            "mcp_timeout",
            "tool_error",
            "dependency_missing",
            "capability_unsupported",
            "cancelled",
            "guardrail_tripwire",
            "retry",
        }
        assert expected == RUNTIME_ERROR_KINDS


# ---------------------------------------------------------------------------
# RuntimeEvent (fabrichnye metody)
# ---------------------------------------------------------------------------


class TestRuntimeEvent:
    """RuntimeEvent - unifitsirovannoe event striminga."""

    def test_assistant_delta(self) -> None:
        ev = RuntimeEvent.assistant_delta("Привет")
        assert ev.type == "assistant_delta"
        assert ev.data["text"] == "Привет"

    def test_status(self) -> None:
        ev = RuntimeEvent.status("Ищу вклады…")
        assert ev.type == "status"
        assert ev.data["text"] == "Ищу вклады…"

    def test_approval_required(self) -> None:
        ev = RuntimeEvent.approval_required(
            action_name="edit_file",
            args={"path": "app.py"},
            allowed_decisions=["approve", "reject"],
            interrupt_id="interrupt-1",
            description="Review edit",
        )
        assert ev.type == "approval_required"
        assert ev.data["action_name"] == "edit_file"
        assert ev.data["allowed_decisions"] == ["approve", "reject"]
        assert ev.data["interrupt_id"] == "interrupt-1"

    def test_user_input_requested(self) -> None:
        ev = RuntimeEvent.user_input_requested(
            prompt="Need answer",
            interrupt_id="interrupt-2",
        )
        assert ev.type == "user_input_requested"
        assert ev.data["prompt"] == "Need answer"
        assert ev.data["interrupt_id"] == "interrupt-2"

    def test_native_notice(self) -> None:
        ev = RuntimeEvent.native_notice(
            "Native thread is active",
            metadata={"thread_id": "t1"},
        )
        assert ev.type == "native_notice"
        assert ev.data["text"] == "Native thread is active"
        assert ev.data["metadata"] == {"thread_id": "t1"}

    def test_tool_call_started(self) -> None:
        ev = RuntimeEvent.tool_call_started(
            name="mcp__iss__get_bonds",
            args={"query": "облигации"},
            correlation_id="c1",
        )
        assert ev.type == "tool_call_started"
        assert ev.data["name"] == "mcp__iss__get_bonds"
        assert ev.data["correlation_id"] == "c1"
        assert ev.data["args"] == {"query": "облигации"}

    def test_tool_call_started_auto_id(self) -> None:
        ev = RuntimeEvent.tool_call_started(name="calc")
        assert len(ev.data["correlation_id"]) == 8  # auto-generated

    def test_tool_call_finished(self) -> None:
        ev = RuntimeEvent.tool_call_finished(
            name="calc",
            correlation_id="c1",
            ok=True,
            result_summary="done",
        )
        assert ev.type == "tool_call_finished"
        assert ev.data["ok"] is True
        assert ev.data["correlation_id"] == "c1"

    def test_tool_call_finished_truncates_summary(self) -> None:
        long_result = "x" * 300
        ev = RuntimeEvent.tool_call_finished(
            name="calc",
            correlation_id="c1",
            result_summary=long_result,
        )
        assert len(ev.data["result_summary"]) == 200

    def test_final(self) -> None:
        msgs = [Message(role="assistant", content="Ответ")]
        metrics = TurnMetrics(latency_ms=100, tool_calls_count=2)
        ev = RuntimeEvent.final("Ответ", new_messages=msgs, metrics=metrics)
        assert ev.type == "final"
        assert ev.data["text"] == "Ответ"
        assert len(ev.data["new_messages"]) == 1
        assert ev.data["metrics"]["latency_ms"] == 100

    def test_final_empty(self) -> None:
        ev = RuntimeEvent.final("ok")
        assert ev.data["new_messages"] == []
        assert ev.data["metrics"] == {}

    def test_final_with_metadata(self) -> None:
        ev = RuntimeEvent.final(
            "ok",
            session_id="sess-1",
            total_cost_usd=0.25,
            usage={"input_tokens": 10, "output_tokens": 5},
            structured_output={"answer": 42},
            native_metadata={"thread_id": "t1"},
        )
        assert ev.data["session_id"] == "sess-1"
        assert ev.data["total_cost_usd"] == 0.25
        assert ev.data["usage"] == {"input_tokens": 10, "output_tokens": 5}
        assert ev.data["structured_output"] == {"answer": 42}
        assert ev.data["native_metadata"] == {"thread_id": "t1"}

    def test_error(self) -> None:
        err = RuntimeErrorData(kind="loop_limit", message="limit")
        ev = RuntimeEvent.error(err)
        assert ev.type == "error"
        assert ev.data["kind"] == "loop_limit"

    def test_to_dict(self) -> None:
        ev = RuntimeEvent.assistant_delta("test")
        d = ev.to_dict()
        assert d["type"] == "assistant_delta"
        assert d["data"]["text"] == "test"

    def test_all_event_types(self) -> None:
        expected = {
            "assistant_delta",
            "thinking_delta",
            "status",
            "tool_call_started",
            "tool_call_finished",
            "approval_required",
            "user_input_requested",
            "native_notice",
            "final",
            "error",
            "background_complete",
        }
        assert expected == RUNTIME_EVENT_TYPES


# ---------------------------------------------------------------------------
# RuntimeConfig
# ---------------------------------------------------------------------------


class TestRuntimeConfig:
    """RuntimeConfig - configuration runtime."""

    def test_defaults(self) -> None:
        cfg = RuntimeConfig()
        assert cfg.runtime_name == "claude_sdk"
        assert cfg.max_iterations == 6
        assert cfg.max_tool_calls == 8
        assert cfg.max_model_retries == 2
        assert cfg.output_format is None
        assert cfg.output_type is None
        assert cfg.structured_mode == "prompt"
        assert cfg.structured_schema_name is None
        assert cfg.structured_strict is True
        assert cfg.request_options is None
        assert cfg.feature_mode == "portable"
        assert cfg.required_capabilities is None
        assert cfg.allow_native_features is False
        assert cfg.native_config == {}

    def test_thin_config(self) -> None:
        cfg = RuntimeConfig(
            runtime_name="thin",
            max_iterations=10,
            model="claude-sonnet-4-20250514",
        )
        assert cfg.runtime_name == "thin"
        assert cfg.max_iterations == 10

    def test_invalid_runtime_name(self) -> None:
        with pytest.raises(ValueError, match="Unknown runtime"):
            RuntimeConfig(runtime_name="nonexistent")

    def test_valid_names(self) -> None:
        for name in ("claude_sdk", "deepagents", "thin"):
            cfg = RuntimeConfig(runtime_name=name)
            assert cfg.runtime_name == name

    def test_extra_params(self) -> None:
        cfg = RuntimeConfig(extra={"temperature": 0.7})
        assert cfg.extra["temperature"] == 0.7

    def test_request_options_are_stored(self) -> None:
        options = ModelRequestOptions(
            max_tokens=123,
            temperature=0.2,
            timeout_sec=30.0,
            provider_options={"require_parameters": True},
            plugins=[{"id": "response-healing"}],
        )

        cfg = RuntimeConfig(runtime_name="thin", request_options=options)

        assert cfg.request_options is options
        assert cfg.request_options.max_tokens == 123
        assert cfg.request_options.provider_options == {"require_parameters": True}

    def test_structured_mode_rejects_unknown_value(self) -> None:
        with pytest.raises(ValueError, match="Unknown structured_mode"):
            RuntimeConfig(runtime_name="thin", structured_mode="magic")  # type: ignore[arg-type]

    def test_default_model(self) -> None:
        """Po umolchaniyu - DEFAULT_MODEL."""
        cfg = RuntimeConfig()
        assert cfg.model == DEFAULT_MODEL

    def test_custom_model(self) -> None:
        """Mozhno zadat model napryamuyu."""
        cfg = RuntimeConfig(model="claude-opus-4-20250514")
        assert cfg.model == "claude-opus-4-20250514"

    def test_invalid_feature_mode(self) -> None:
        with pytest.raises(ValueError, match="feature_mode"):
            RuntimeConfig(feature_mode="invalid")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# resolve_model_name
# ---------------------------------------------------------------------------


class TestResolveModelName:
    """resolve_model_name - razreshenie imeni models (alias + full imya)."""

    def test_none_returns_default(self) -> None:
        assert resolve_model_name(None) == DEFAULT_MODEL

    def test_empty_returns_default(self) -> None:
        assert resolve_model_name("") == DEFAULT_MODEL

    def test_short_alias_sonnet(self) -> None:
        assert resolve_model_name("sonnet") == "claude-sonnet-4-20250514"

    def test_short_alias_opus(self) -> None:
        assert resolve_model_name("opus") == "claude-opus-4-20250514"

    def test_short_alias_haiku(self) -> None:
        assert resolve_model_name("haiku") == "claude-haiku-3-20250307"

    def test_alias_case_insensitive(self) -> None:
        assert resolve_model_name("SONNET") == "claude-sonnet-4-20250514"
        assert resolve_model_name("Opus") == "claude-opus-4-20250514"

    def test_full_name_sonnet(self) -> None:
        assert resolve_model_name("claude-sonnet-4-20250514") == "claude-sonnet-4-20250514"

    def test_full_name_opus(self) -> None:
        assert resolve_model_name("claude-opus-4-20250514") == "claude-opus-4-20250514"

    def test_full_name_haiku(self) -> None:
        assert resolve_model_name("claude-haiku-3-20250307") == "claude-haiku-3-20250307"

    def test_prefix_match(self) -> None:
        """Prefix match for notpolnyh imen."""
        result = resolve_model_name("claude-opus")
        assert result == "claude-opus-4-20250514"

    def test_invalid_returns_default(self) -> None:
        assert resolve_model_name("nonexistent_model_xyz") == DEFAULT_MODEL

    def test_multi_provider_models(self) -> None:
        """Multiprovaydernye models from models.yaml."""
        assert resolve_model_name("gpt-4o") == "gpt-4o"
        assert resolve_model_name("gemini") == "gemini-2.5-pro"
        assert resolve_model_name("r1") == "deepseek-reasoner"

    def test_explicit_provider_prefix_passthrough(self) -> None:
        """Explicit provider:model not should shlopyvatsya in registry default."""
        assert (
            resolve_model_name("openrouter:anthropic/claude-3.5-haiku")
            == "openrouter:anthropic/claude-3.5-haiku"
        )

    def test_whitespace_trimmed(self) -> None:
        assert resolve_model_name("  sonnet  ") == "claude-sonnet-4-20250514"

    def test_valid_model_names_via_registry(self) -> None:
        """ModelRegistry.valid_models contains models vseh provayderov."""
        from swarmline.runtime.model_registry import get_registry

        valid = get_registry().valid_models
        assert "claude-sonnet-4-20250514" in valid
        assert "claude-opus-4-20250514" in valid
        assert "claude-haiku-3-20250307" in valid
        assert "gpt-4o" in valid


# ---------------------------------------------------------------------------
# TurnMetrics
# ---------------------------------------------------------------------------


class TestTurnMetrics:
    """TurnMetrics - metrics turn'a."""

    def test_defaults(self) -> None:
        m = TurnMetrics()
        assert m.latency_ms == 0
        assert m.model == ""

    def test_to_dict(self) -> None:
        m = TurnMetrics(latency_ms=50, tool_calls_count=3, model="sonnet")
        d = m.to_dict()
        assert d["latency_ms"] == 50
        assert d["tool_calls_count"] == 3
        assert d["model"] == "sonnet"
