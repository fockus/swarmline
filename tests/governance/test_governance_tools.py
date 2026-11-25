"""Tests for governance agent tools — 4 tools following hitl_tools pattern.

TDD: Red phase — tests written before implementation.
Tools: check_permission, request_approval, get_audit, redact_secrets.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from swarmline.domain_types import ToolSpec
from swarmline.governance.approval_gates import ApprovalGateManager
from swarmline.governance.audit_trail import InMemoryAuditTrail
from swarmline.governance.governance_tools import create_governance_tools
from swarmline.governance.permission_manager import PermissionManager
from swarmline.governance.secret_boundary import SecretBoundaryManager
from swarmline.governance.types import AuditEntry


@pytest.fixture()
def tools() -> tuple[dict[str, ToolSpec], dict[str, Any]]:
    perm = PermissionManager()
    gate = ApprovalGateManager()
    audit = InMemoryAuditTrail()
    secret = SecretBoundaryManager()
    return create_governance_tools(
        permission_manager=perm,
        approval_gate=gate,
        audit_trail=audit,
        secret_boundary=secret,
    )


@pytest.fixture()
def specs(tools: tuple[dict[str, ToolSpec], dict[str, Any]]) -> dict[str, ToolSpec]:
    return tools[0]


@pytest.fixture()
def executors(tools: tuple[dict[str, ToolSpec], dict[str, Any]]) -> dict[str, Any]:
    return tools[1]


class TestCreateGovernanceToolsFactory:
    """Factory returns correct structure."""

    def test_returns_tuple_of_two_dicts(
        self, tools: tuple[dict[str, ToolSpec], dict[str, Any]]
    ) -> None:
        specs, executors = tools
        assert isinstance(specs, dict)
        assert isinstance(executors, dict)

    def test_four_tools_created(self, specs: dict[str, ToolSpec]) -> None:
        assert len(specs) == 4

    def test_tool_names(self, specs: dict[str, ToolSpec]) -> None:
        expected = {
            "check_permission",
            "request_approval",
            "get_audit",
            "redact_secrets",
        }
        assert set(specs.keys()) == expected

    def test_specs_are_toolspec(self, specs: dict[str, ToolSpec]) -> None:
        assert all(isinstance(s, ToolSpec) for s in specs.values())

    def test_executors_match_specs(
        self, specs: dict[str, ToolSpec], executors: dict[str, Any]
    ) -> None:
        assert set(specs.keys()) == set(executors.keys())

    def test_all_executors_callable(self, executors: dict[str, Any]) -> None:
        assert all(callable(e) for e in executors.values())


class TestCheckPermissionTool:
    """check_permission returns {allowed: bool, reason: str}."""

    def test_allowed_action(self, executors: dict[str, Any]) -> None:
        result = json.loads(
            executors["check_permission"](
                {"profile_name": "editor", "action": "file_write"}
            )
        )
        assert "allowed" in result

    def test_denied_action(self, executors: dict[str, Any]) -> None:
        result = json.loads(
            executors["check_permission"](
                {"profile_name": "read-only", "action": "write_file"}
            )
        )
        assert result["allowed"] is False

    def test_unknown_profile_returns_error(self, executors: dict[str, Any]) -> None:
        result = json.loads(
            executors["check_permission"](
                {"profile_name": "nonexistent", "action": "read"}
            )
        )
        assert result["status"] == "error"

    def test_missing_profile_name_returns_error(
        self, executors: dict[str, Any]
    ) -> None:
        result = json.loads(executors["check_permission"]({"action": "read"}))
        assert result["status"] == "error"

    def test_missing_action_returns_error(self, executors: dict[str, Any]) -> None:
        result = json.loads(executors["check_permission"]({"profile_name": "editor"}))
        assert result["status"] == "error"

    def test_result_has_reason(self, executors: dict[str, Any]) -> None:
        result = json.loads(
            executors["check_permission"](
                {"profile_name": "editor", "action": "file_write"}
            )
        )
        assert "reason" in result

    def test_returns_valid_json(self, executors: dict[str, Any]) -> None:
        raw = executors["check_permission"](
            {"profile_name": "editor", "action": "read"}
        )
        assert isinstance(raw, str)
        parsed = json.loads(raw)
        assert isinstance(parsed, dict)


class TestRequestApprovalTool:
    """request_approval returns {gate_config, requires_approval}."""

    def test_destructive_action_requires_approval(
        self, executors: dict[str, Any]
    ) -> None:
        result = json.loads(
            executors["request_approval"](
                {
                    "action": "deploy",
                    "description": "Deploy to prod",
                    "risk_level": "high",
                }
            )
        )
        assert "requires_approval" in result

    def test_safe_action(self, executors: dict[str, Any]) -> None:
        result = json.loads(
            executors["request_approval"](
                {
                    "action": "file_read",
                    "description": "Read a file",
                    "risk_level": "low",
                }
            )
        )
        assert "requires_approval" in result

    def test_missing_action_returns_error(self, executors: dict[str, Any]) -> None:
        result = json.loads(
            executors["request_approval"]({"description": "test", "risk_level": "low"})
        )
        assert result["status"] == "error"

    def test_returns_valid_json(self, executors: dict[str, Any]) -> None:
        raw = executors["request_approval"](
            {"action": "test", "description": "test", "risk_level": "low"}
        )
        assert isinstance(json.loads(raw), dict)


class TestGetAuditTool:
    """get_audit returns {audit_trail JSON}."""

    def test_get_audit_empty_run(self, executors: dict[str, Any]) -> None:
        result = json.loads(executors["get_audit"]({"run_id": "run-1"}))
        assert result["run_id"] == "run-1"
        assert result["entries"] == []

    def test_get_audit_with_entries(self) -> None:
        audit = InMemoryAuditTrail()
        audit.record(
            AuditEntry(
                entry_id="e-1",
                run_id="run-1",
                timestamp=1700000000.0,
                actor="agent-1",
                action="file_read",
                tool_name="read_file",
                file_path="/src/main.py",
                decision="allowed",
                details={"key": "value"},
            )
        )
        _, executors = create_governance_tools(
            permission_manager=PermissionManager(),
            approval_gate=ApprovalGateManager(),
            audit_trail=audit,
            secret_boundary=SecretBoundaryManager(),
        )
        result = json.loads(executors["get_audit"]({"run_id": "run-1"}))
        assert len(result["entries"]) == 1
        assert result["entries"][0]["actor"] == "agent-1"

    def test_get_audit_filter_by_actor(self) -> None:
        audit = InMemoryAuditTrail()
        audit.record(
            AuditEntry(
                entry_id="e-1",
                run_id="run-1",
                timestamp=1.0,
                actor="alice",
                action="read",
                tool_name=None,
                file_path=None,
                decision=None,
                details={},
            )
        )
        audit.record(
            AuditEntry(
                entry_id="e-2",
                run_id="run-1",
                timestamp=2.0,
                actor="bob",
                action="write",
                tool_name=None,
                file_path=None,
                decision=None,
                details={},
            )
        )
        _, executors = create_governance_tools(
            permission_manager=PermissionManager(),
            approval_gate=ApprovalGateManager(),
            audit_trail=audit,
            secret_boundary=SecretBoundaryManager(),
        )
        result = json.loads(
            executors["get_audit"]({"run_id": "run-1", "actor": "alice"})
        )
        assert len(result["entries"]) == 1
        assert result["entries"][0]["actor"] == "alice"

    def test_missing_run_id_returns_error(self, executors: dict[str, Any]) -> None:
        result = json.loads(executors["get_audit"]({}))
        assert result["status"] == "error"

    def test_returns_valid_json(self, executors: dict[str, Any]) -> None:
        raw = executors["get_audit"]({"run_id": "run-1"})
        assert isinstance(json.loads(raw), dict)


class TestRedactSecretsTool:
    """redact_secrets returns {redacted_text, patterns_found}."""

    def test_redact_api_key(self, executors: dict[str, Any]) -> None:
        result = json.loads(
            executors["redact_secrets"](
                {"text": "key: sk-abcdefghijklmnopqrstuvwxyz1234"}
            )
        )
        assert "sk-" not in result["redacted_text"]
        assert result["patterns_found"] > 0

    def test_no_secrets(self, executors: dict[str, Any]) -> None:
        result = json.loads(executors["redact_secrets"]({"text": "Hello, world!"}))
        assert result["redacted_text"] == "Hello, world!"
        assert result["patterns_found"] == 0

    def test_missing_text_returns_error(self, executors: dict[str, Any]) -> None:
        result = json.loads(executors["redact_secrets"]({}))
        assert result["status"] == "error"

    def test_returns_valid_json(self, executors: dict[str, Any]) -> None:
        raw = executors["redact_secrets"]({"text": "test"})
        assert isinstance(json.loads(raw), dict)


class TestGovernanceToolsDIP:
    """Factory accepts protocols, not concrete types."""

    def test_accepts_protocol_compatible_objects(self) -> None:
        """Any object satisfying the protocols should work."""
        specs, executors = create_governance_tools(
            permission_manager=PermissionManager(),
            approval_gate=ApprovalGateManager(),
            audit_trail=InMemoryAuditTrail(),
            secret_boundary=SecretBoundaryManager(),
        )
        assert len(specs) == 4
        assert len(executors) == 4
