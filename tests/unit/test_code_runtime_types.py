"""Tests for code_runtime_types — CodeRuntimeEvent, Error Taxonomy, Capabilities, Session.

TDD: RED phase — tests written BEFORE implementation.
"""

from __future__ import annotations

import enum
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# A1: CodeRuntimeEventType enum
# ---------------------------------------------------------------------------


class TestCodeRuntimeEventType:
    """CodeRuntimeEventType must have exactly 6 members."""

    def test_event_type_is_enum(self) -> None:
        from swarmline.code_runtime_types import CodeRuntimeEventType

        assert issubclass(CodeRuntimeEventType, enum.Enum)

    @pytest.mark.parametrize(
        "member",
        ["status", "tool_use", "tool_result", "delta", "error", "final"],
    )
    def test_event_type_has_member(self, member: str) -> None:
        from swarmline.code_runtime_types import CodeRuntimeEventType

        assert hasattr(CodeRuntimeEventType, member)

    def test_event_type_has_exactly_six_members(self) -> None:
        from swarmline.code_runtime_types import CodeRuntimeEventType

        assert len(CodeRuntimeEventType) == 6


# ---------------------------------------------------------------------------
# A1: CODE_RUNTIME_ERROR_KINDS
# ---------------------------------------------------------------------------


class TestCodeRuntimeErrorKinds:
    """CODE_RUNTIME_ERROR_KINDS frozenset with 5 known error kinds."""

    def test_error_kinds_is_frozenset(self) -> None:
        from swarmline.code_runtime_types import CODE_RUNTIME_ERROR_KINDS

        assert isinstance(CODE_RUNTIME_ERROR_KINDS, frozenset)

    @pytest.mark.parametrize(
        "kind",
        [
            "provider_unavailable",
            "session_expired",
            "approval_timeout",
            "sandbox_violation",
            "capability_missing",
        ],
    )
    def test_error_kinds_contains(self, kind: str) -> None:
        from swarmline.code_runtime_types import CODE_RUNTIME_ERROR_KINDS

        assert kind in CODE_RUNTIME_ERROR_KINDS

    def test_error_kinds_has_exactly_five(self) -> None:
        from swarmline.code_runtime_types import CODE_RUNTIME_ERROR_KINDS

        assert len(CODE_RUNTIME_ERROR_KINDS) == 5


# ---------------------------------------------------------------------------
# A1: CodeRuntimeErrorData
# ---------------------------------------------------------------------------


class TestCodeRuntimeErrorData:
    """Frozen dataclass with kind validation."""

    def test_create_valid_error(self) -> None:
        from swarmline.code_runtime_types import CodeRuntimeErrorData

        err = CodeRuntimeErrorData(
            kind="session_expired",
            message="Session timed out",
            recoverable=True,
        )
        assert err.kind == "session_expired"
        assert err.message == "Session timed out"
        assert err.recoverable is True
        assert err.details is None

    def test_create_with_details(self) -> None:
        from swarmline.code_runtime_types import CodeRuntimeErrorData

        details = {"retry_after": 5}
        err = CodeRuntimeErrorData(
            kind="provider_unavailable",
            message="Provider down",
            recoverable=True,
            details=details,
        )
        assert err.details == {"retry_after": 5}

    def test_invalid_kind_falls_back_to_provider_unavailable(self) -> None:
        from swarmline.code_runtime_types import CodeRuntimeErrorData

        err = CodeRuntimeErrorData(kind="unknown_kind", message="bad")
        assert err.kind == "provider_unavailable"

    def test_frozen_immutability(self) -> None:
        from swarmline.code_runtime_types import CodeRuntimeErrorData

        err = CodeRuntimeErrorData(kind="session_expired", message="x")
        with pytest.raises(FrozenInstanceError):
            err.kind = "sandbox_violation"  # type: ignore[misc]

    def test_default_recoverable_is_false(self) -> None:
        from swarmline.code_runtime_types import CodeRuntimeErrorData

        err = CodeRuntimeErrorData(kind="sandbox_violation", message="denied")
        assert err.recoverable is False


# ---------------------------------------------------------------------------
# A1: CodeRuntimeEvent — frozen dataclass with factory methods
# ---------------------------------------------------------------------------


class TestCodeRuntimeEvent:
    """Frozen dataclass with factory methods for each event type."""

    def test_frozen_immutability(self) -> None:
        from swarmline.code_runtime_types import CodeRuntimeEvent, CodeRuntimeEventType

        evt = CodeRuntimeEvent(type=CodeRuntimeEventType.status, data={"text": "hi"})
        with pytest.raises(FrozenInstanceError):
            evt.type = CodeRuntimeEventType.final  # type: ignore[misc]

    def test_factory_status(self) -> None:
        from swarmline.code_runtime_types import CodeRuntimeEvent, CodeRuntimeEventType

        evt = CodeRuntimeEvent.status("Running...")
        assert evt.type == CodeRuntimeEventType.status
        assert evt.data == {"text": "Running..."}

    def test_factory_tool_use(self) -> None:
        from swarmline.code_runtime_types import CodeRuntimeEvent, CodeRuntimeEventType

        evt = CodeRuntimeEvent.tool_use(name="edit", args={"path": "/a"})
        assert evt.type == CodeRuntimeEventType.tool_use
        assert evt.data["name"] == "edit"
        assert evt.data["args"] == {"path": "/a"}

    def test_factory_tool_result(self) -> None:
        from swarmline.code_runtime_types import CodeRuntimeEvent, CodeRuntimeEventType

        evt = CodeRuntimeEvent.tool_result(name="edit", ok=True, summary="done")
        assert evt.type == CodeRuntimeEventType.tool_result
        assert evt.data["name"] == "edit"
        assert evt.data["ok"] is True
        assert evt.data["summary"] == "done"

    def test_factory_delta(self) -> None:
        from swarmline.code_runtime_types import CodeRuntimeEvent, CodeRuntimeEventType

        evt = CodeRuntimeEvent.delta("Hello ")
        assert evt.type == CodeRuntimeEventType.delta
        assert evt.data == {"text": "Hello "}

    def test_factory_error(self) -> None:
        from swarmline.code_runtime_types import (
            CodeRuntimeErrorData,
            CodeRuntimeEvent,
            CodeRuntimeEventType,
        )

        err = CodeRuntimeErrorData(kind="sandbox_violation", message="denied")
        evt = CodeRuntimeEvent.error(err)
        assert evt.type == CodeRuntimeEventType.error
        assert evt.data["kind"] == "sandbox_violation"
        assert evt.data["message"] == "denied"

    def test_factory_final(self) -> None:
        from swarmline.code_runtime_types import CodeRuntimeEvent, CodeRuntimeEventType

        evt = CodeRuntimeEvent.final(text="Done", session_id="s1")
        assert evt.type == CodeRuntimeEventType.final
        assert evt.data["text"] == "Done"
        assert evt.data["session_id"] == "s1"

    def test_factory_final_defaults(self) -> None:
        from swarmline.code_runtime_types import CodeRuntimeEvent

        evt = CodeRuntimeEvent.final(text="Result")
        assert evt.data["text"] == "Result"
        assert evt.data.get("session_id") is None

    def test_text_property(self) -> None:
        from swarmline.code_runtime_types import CodeRuntimeEvent

        evt = CodeRuntimeEvent.delta("chunk")
        assert evt.text == "chunk"

    def test_is_final_property(self) -> None:
        from swarmline.code_runtime_types import CodeRuntimeEvent

        evt = CodeRuntimeEvent.final(text="done")
        assert evt.is_final is True

        evt2 = CodeRuntimeEvent.status("working")
        assert evt2.is_final is False

    def test_is_error_property(self) -> None:
        from swarmline.code_runtime_types import (
            CodeRuntimeErrorData,
            CodeRuntimeEvent,
        )

        err = CodeRuntimeErrorData(kind="session_expired", message="x")
        evt = CodeRuntimeEvent.error(err)
        assert evt.is_error is True

    def test_to_dict(self) -> None:
        from swarmline.code_runtime_types import CodeRuntimeEvent

        evt = CodeRuntimeEvent.status("hello")
        d = evt.to_dict()
        assert d["type"] == "status"
        assert d["data"] == {"text": "hello"}


# ---------------------------------------------------------------------------
# A2: CodeRuntimeCapabilities
# ---------------------------------------------------------------------------


class TestCodeRuntimeCapabilities:
    """Frozen dataclass with 6 boolean flags, supports(), enabled_flags()."""

    def test_create_with_defaults(self) -> None:
        from swarmline.code_runtime_types import CodeRuntimeCapabilities

        caps = CodeRuntimeCapabilities(provider="claude_code", mode="interactive")
        assert caps.provider == "claude_code"
        assert caps.mode == "interactive"
        assert caps.approvals is False
        assert caps.subagents is False
        assert caps.hooks is False
        assert caps.worktrees is False
        assert caps.session_persistence is False
        assert caps.sandbox is False

    def test_create_with_flags_enabled(self) -> None:
        from swarmline.code_runtime_types import CodeRuntimeCapabilities

        caps = CodeRuntimeCapabilities(
            provider="claude_code",
            mode="interactive",
            approvals=True,
            subagents=True,
            hooks=True,
            worktrees=True,
            session_persistence=True,
            sandbox=True,
        )
        assert caps.approvals is True
        assert caps.sandbox is True

    def test_frozen_immutability(self) -> None:
        from swarmline.code_runtime_types import CodeRuntimeCapabilities

        caps = CodeRuntimeCapabilities(provider="claude_code", mode="interactive")
        with pytest.raises(FrozenInstanceError):
            caps.approvals = True  # type: ignore[misc]

    @pytest.mark.parametrize(
        "flag",
        [
            "approvals",
            "subagents",
            "hooks",
            "worktrees",
            "session_persistence",
            "sandbox",
        ],
    )
    def test_supports_enabled_flag_returns_true(self, flag: str) -> None:
        from swarmline.code_runtime_types import CodeRuntimeCapabilities

        kwargs = {"provider": "test", "mode": "test", flag: True}
        caps = CodeRuntimeCapabilities(**kwargs)
        assert caps.supports(flag) is True

    @pytest.mark.parametrize(
        "flag",
        [
            "approvals",
            "subagents",
            "hooks",
            "worktrees",
            "session_persistence",
            "sandbox",
        ],
    )
    def test_supports_disabled_flag_returns_false(self, flag: str) -> None:
        from swarmline.code_runtime_types import CodeRuntimeCapabilities

        caps = CodeRuntimeCapabilities(provider="test", mode="test")
        assert caps.supports(flag) is False

    def test_supports_invalid_flag_returns_false(self) -> None:
        from swarmline.code_runtime_types import CodeRuntimeCapabilities

        caps = CodeRuntimeCapabilities(provider="test", mode="test", approvals=True)
        assert caps.supports("nonexistent") is False

    def test_enabled_flags_empty(self) -> None:
        from swarmline.code_runtime_types import CodeRuntimeCapabilities

        caps = CodeRuntimeCapabilities(provider="test", mode="test")
        assert caps.enabled_flags() == frozenset()

    def test_enabled_flags_some(self) -> None:
        from swarmline.code_runtime_types import CodeRuntimeCapabilities

        caps = CodeRuntimeCapabilities(
            provider="test", mode="test", approvals=True, sandbox=True
        )
        assert caps.enabled_flags() == frozenset({"approvals", "sandbox"})

    def test_enabled_flags_all(self) -> None:
        from swarmline.code_runtime_types import CodeRuntimeCapabilities

        caps = CodeRuntimeCapabilities(
            provider="test",
            mode="test",
            approvals=True,
            subagents=True,
            hooks=True,
            worktrees=True,
            session_persistence=True,
            sandbox=True,
        )
        assert len(caps.enabled_flags()) == 6


# ---------------------------------------------------------------------------
# A3: CodeSessionStatus + CodeRuntimeSession
# ---------------------------------------------------------------------------


class TestCodeSessionStatus:
    """CodeSessionStatus enum with 6 lifecycle states."""

    def test_is_enum(self) -> None:
        from swarmline.code_runtime_types import CodeSessionStatus

        assert issubclass(CodeSessionStatus, enum.Enum)

    @pytest.mark.parametrize(
        "member",
        ["CREATED", "RUNNING", "PAUSED", "COMPLETED", "FAILED", "TERMINATED"],
    )
    def test_has_member(self, member: str) -> None:
        from swarmline.code_runtime_types import CodeSessionStatus

        assert hasattr(CodeSessionStatus, member)

    def test_has_exactly_six_members(self) -> None:
        from swarmline.code_runtime_types import CodeSessionStatus

        assert len(CodeSessionStatus) == 6


class TestCodeRuntimeSession:
    """Frozen session snapshot."""

    def test_create_session(self) -> None:
        from swarmline.code_runtime_types import (
            CodeRuntimeCapabilities,
            CodeRuntimeSession,
            CodeSessionStatus,
        )

        caps = CodeRuntimeCapabilities(provider="claude_code", mode="interactive")
        now = datetime(2026, 4, 12, tzinfo=timezone.utc)
        session = CodeRuntimeSession(
            session_id="s-123",
            provider="claude_code",
            status=CodeSessionStatus.CREATED,
            capabilities=caps,
            created_at=now,
        )
        assert session.session_id == "s-123"
        assert session.provider == "claude_code"
        assert session.status == CodeSessionStatus.CREATED
        assert session.capabilities is caps
        assert session.created_at == now

    def test_frozen_immutability(self) -> None:
        from swarmline.code_runtime_types import (
            CodeRuntimeCapabilities,
            CodeRuntimeSession,
            CodeSessionStatus,
        )

        caps = CodeRuntimeCapabilities(provider="test", mode="test")
        now = datetime(2026, 4, 12, tzinfo=timezone.utc)
        session = CodeRuntimeSession(
            session_id="s-1",
            provider="test",
            status=CodeSessionStatus.RUNNING,
            capabilities=caps,
            created_at=now,
        )
        with pytest.raises(FrozenInstanceError):
            session.status = CodeSessionStatus.FAILED  # type: ignore[misc]

    def test_session_with_all_statuses(self) -> None:
        from swarmline.code_runtime_types import (
            CodeRuntimeCapabilities,
            CodeRuntimeSession,
            CodeSessionStatus,
        )

        caps = CodeRuntimeCapabilities(provider="test", mode="test")
        now = datetime(2026, 4, 12, tzinfo=timezone.utc)
        for status in CodeSessionStatus:
            session = CodeRuntimeSession(
                session_id="s-x",
                provider="test",
                status=status,
                capabilities=caps,
                created_at=now,
            )
            assert session.status == status

    def test_session_no_sdk_types(self) -> None:
        """Session uses only stdlib + domain types."""
        from swarmline.code_runtime_types import CodeRuntimeSession

        import dataclasses

        fields = {f.name: f.type for f in dataclasses.fields(CodeRuntimeSession)}
        assert "str" in str(fields["session_id"])
        assert "str" in str(fields["provider"])


# ---------------------------------------------------------------------------
# A1: Zero SDK imports verification
# ---------------------------------------------------------------------------


class TestZeroSdkImports:
    """code_runtime_types must not import any SDK packages."""

    def test_no_anthropic_import(self) -> None:
        import importlib
        import inspect

        mod = importlib.import_module("swarmline.code_runtime_types")
        source = inspect.getsource(mod)
        assert "import anthropic" not in source
        assert "from anthropic" not in source

    def test_no_openai_import(self) -> None:
        import importlib
        import inspect

        mod = importlib.import_module("swarmline.code_runtime_types")
        source = inspect.getsource(mod)
        assert "import openai" not in source
        assert "from openai" not in source


# ---------------------------------------------------------------------------
# Edge-case tests (tester-2)
# ---------------------------------------------------------------------------


class TestCodeRuntimeEventEdgeCases:
    """Edge cases for CodeRuntimeEvent factory methods and properties."""

    def test_factory_status_empty_string(self) -> None:
        from swarmline.code_runtime_types import CodeRuntimeEvent

        evt = CodeRuntimeEvent.status("")
        assert evt.text == ""
        assert evt.data == {"text": ""}

    def test_factory_delta_empty_string(self) -> None:
        from swarmline.code_runtime_types import CodeRuntimeEvent

        evt = CodeRuntimeEvent.delta("")
        assert evt.text == ""

    def test_factory_tool_use_none_args_defaults_to_empty_dict(self) -> None:
        from swarmline.code_runtime_types import CodeRuntimeEvent

        evt = CodeRuntimeEvent.tool_use(name="bash", args=None)
        assert evt.data["args"] == {}

    def test_text_property_on_non_text_event_returns_empty(self) -> None:
        from swarmline.code_runtime_types import CodeRuntimeEvent

        evt = CodeRuntimeEvent.tool_use(name="edit", args={"path": "x"})
        assert evt.text == ""

    def test_error_event_carries_fallback_kind(self) -> None:
        """Error with unknown kind falls back; event data reflects fallback."""
        from swarmline.code_runtime_types import CodeRuntimeErrorData, CodeRuntimeEvent

        err = CodeRuntimeErrorData(kind="totally_bogus", message="bad")
        evt = CodeRuntimeEvent.error(err)
        assert evt.data["kind"] == "provider_unavailable"

    def test_to_dict_roundtrip_consistency(self) -> None:
        """to_dict() output is consistent — calling twice gives equal results."""
        from swarmline.code_runtime_types import CodeRuntimeEvent

        evt = CodeRuntimeEvent.tool_result(name="run", ok=False, summary="fail")
        assert evt.to_dict() == evt.to_dict()

    @pytest.mark.parametrize(
        "factory,kwargs",
        [
            ("status", {"text": "x"}),
            ("delta", {"text": "y"}),
            ("tool_use", {"name": "t"}),
            ("tool_result", {"name": "t"}),
            ("final", {"text": "z"}),
        ],
    )
    def test_to_dict_type_is_string_value(
        self, factory: str, kwargs: dict[str, Any]
    ) -> None:
        """to_dict()['type'] is the enum's string value, not the enum itself."""
        from swarmline.code_runtime_types import CodeRuntimeEvent

        evt = getattr(CodeRuntimeEvent, factory)(**kwargs)
        d = evt.to_dict()
        assert isinstance(d["type"], str)

    def test_event_with_large_data_payload(self) -> None:
        from swarmline.code_runtime_types import CodeRuntimeEvent, CodeRuntimeEventType

        large_data = {"text": "x" * 100_000, "extra": list(range(1000))}
        evt = CodeRuntimeEvent(type=CodeRuntimeEventType.status, data=large_data)
        assert len(evt.data["text"]) == 100_000
        assert len(evt.data["extra"]) == 1000

    def test_default_data_is_empty_dict(self) -> None:
        from swarmline.code_runtime_types import CodeRuntimeEvent, CodeRuntimeEventType

        evt = CodeRuntimeEvent(type=CodeRuntimeEventType.delta)
        assert evt.data == {}
        assert evt.text == ""


class TestCodeRuntimeErrorDataEdgeCases:
    """Edge cases for CodeRuntimeErrorData."""

    def test_to_dict_without_details_excludes_key(self) -> None:
        from swarmline.code_runtime_types import CodeRuntimeErrorData

        err = CodeRuntimeErrorData(kind="session_expired", message="gone")
        d = err.to_dict()
        assert "details" not in d

    def test_to_dict_with_details_includes_key(self) -> None:
        from swarmline.code_runtime_types import CodeRuntimeErrorData

        err = CodeRuntimeErrorData(
            kind="session_expired", message="gone", details={"code": 408}
        )
        d = err.to_dict()
        assert d["details"] == {"code": 408}

    def test_empty_message_is_valid(self) -> None:
        from swarmline.code_runtime_types import CodeRuntimeErrorData

        err = CodeRuntimeErrorData(kind="sandbox_violation", message="")
        assert err.message == ""

    @pytest.mark.parametrize(
        "kind",
        [
            "provider_unavailable",
            "session_expired",
            "approval_timeout",
            "sandbox_violation",
            "capability_missing",
        ],
    )
    def test_to_dict_preserves_kind(self, kind: str) -> None:
        from swarmline.code_runtime_types import CodeRuntimeErrorData

        err = CodeRuntimeErrorData(kind=kind, message="m")
        assert err.to_dict()["kind"] == kind


class TestCodeRuntimeCapabilitiesEdgeCases:
    """Edge cases for CodeRuntimeCapabilities."""

    def test_supports_empty_string_returns_false(self) -> None:
        from swarmline.code_runtime_types import CodeRuntimeCapabilities

        caps = CodeRuntimeCapabilities(provider="test", mode="test", approvals=True)
        assert caps.supports("") is False

    def test_enabled_flags_returns_frozenset_type(self) -> None:
        from swarmline.code_runtime_types import CodeRuntimeCapabilities

        caps = CodeRuntimeCapabilities(provider="test", mode="test", sandbox=True)
        result = caps.enabled_flags()
        assert type(result) is frozenset

    def test_enabled_flags_all_true_contains_all_six(self) -> None:
        from swarmline.code_runtime_types import CodeRuntimeCapabilities

        caps = CodeRuntimeCapabilities(
            provider="p",
            mode="m",
            approvals=True,
            subagents=True,
            hooks=True,
            worktrees=True,
            session_persistence=True,
            sandbox=True,
        )
        expected = frozenset(
            {
                "approvals",
                "subagents",
                "hooks",
                "worktrees",
                "session_persistence",
                "sandbox",
            }
        )
        assert caps.enabled_flags() == expected

    def test_supports_and_enabled_flags_consistent(self) -> None:
        """Every flag in enabled_flags() returns True from supports()."""
        from swarmline.code_runtime_types import CodeRuntimeCapabilities

        caps = CodeRuntimeCapabilities(
            provider="test", mode="test", hooks=True, sandbox=True
        )
        for flag in caps.enabled_flags():
            assert caps.supports(flag) is True


class TestCodeRuntimeSessionEdgeCases:
    """Edge cases for CodeRuntimeSession."""

    def test_session_equality_same_fields(self) -> None:
        """Frozen dataclass __eq__ compares by fields."""
        from swarmline.code_runtime_types import (
            CodeRuntimeCapabilities,
            CodeRuntimeSession,
            CodeSessionStatus,
        )

        caps = CodeRuntimeCapabilities(provider="test", mode="test")
        now = datetime(2026, 4, 12, tzinfo=timezone.utc)
        s1 = CodeRuntimeSession(
            session_id="s-1",
            provider="test",
            status=CodeSessionStatus.CREATED,
            capabilities=caps,
            created_at=now,
        )
        s2 = CodeRuntimeSession(
            session_id="s-1",
            provider="test",
            status=CodeSessionStatus.CREATED,
            capabilities=caps,
            created_at=now,
        )
        assert s1 == s2

    def test_session_inequality_different_status(self) -> None:
        from swarmline.code_runtime_types import (
            CodeRuntimeCapabilities,
            CodeRuntimeSession,
            CodeSessionStatus,
        )

        caps = CodeRuntimeCapabilities(provider="test", mode="test")
        now = datetime(2026, 4, 12, tzinfo=timezone.utc)
        s1 = CodeRuntimeSession(
            session_id="s-1",
            provider="test",
            status=CodeSessionStatus.CREATED,
            capabilities=caps,
            created_at=now,
        )
        s2 = CodeRuntimeSession(
            session_id="s-1",
            provider="test",
            status=CodeSessionStatus.RUNNING,
            capabilities=caps,
            created_at=now,
        )
        assert s1 != s2


class TestCodeRuntimeConfigEdgeCases:
    """Edge cases for CodeRuntimeConfig."""

    def test_default_values(self) -> None:
        from swarmline.code_runtime_types import CodeRuntimeConfig

        cfg = CodeRuntimeConfig()
        assert cfg.provider == "claude_code"
        assert cfg.model == "claude-sonnet-4-20250514"
        assert cfg.working_directory == "."
        assert cfg.approval_mode == "auto"
        assert cfg.sandbox is True
        assert cfg.extra == {}

    def test_custom_values(self) -> None:
        from swarmline.code_runtime_types import CodeRuntimeConfig

        cfg = CodeRuntimeConfig(
            provider="codex",
            model="codex-mini",
            working_directory="/tmp/work",
            approval_mode="manual",
            sandbox=False,
            extra={"timeout": 60},
        )
        assert cfg.provider == "codex"
        assert cfg.model == "codex-mini"
        assert cfg.working_directory == "/tmp/work"
        assert cfg.approval_mode == "manual"
        assert cfg.sandbox is False
        assert cfg.extra == {"timeout": 60}

    def test_frozen_immutability(self) -> None:
        from swarmline.code_runtime_types import CodeRuntimeConfig

        cfg = CodeRuntimeConfig()
        with pytest.raises(FrozenInstanceError):
            cfg.provider = "codex"  # type: ignore[misc]

    def test_config_equality(self) -> None:
        from swarmline.code_runtime_types import CodeRuntimeConfig

        c1 = CodeRuntimeConfig(provider="codex", sandbox=False)
        c2 = CodeRuntimeConfig(provider="codex", sandbox=False)
        assert c1 == c2
