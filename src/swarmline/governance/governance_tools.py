"""Governance tool factory — agent-callable tools for permission, approval, audit, secrets.

Creates 4 tools: check_permission, request_approval, get_audit, redact_secrets.
All return JSON-serialized results. Follows hitl_tools.py pattern.
Accepts protocols (DIP), not concrete types.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from swarmline.domain_types import ToolSpec
from swarmline.governance.protocols import (
    ApprovalGatePort,
    AuditTrailPort,
    PermissionManagerPort,
    SecretBoundaryPort,
)

# ---------------------------------------------------------------------------
# JSON Schemas
# ---------------------------------------------------------------------------

_CHECK_PERMISSION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "profile_name": {"type": "string", "description": "Permission profile name"},
        "action": {"type": "string", "description": "Action to check permission for"},
        "tool_name": {
            "type": "string",
            "description": "Optional tool name for allowlist check",
        },
    },
    "required": ["profile_name", "action"],
}

_REQUEST_APPROVAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "description": "Action requiring approval"},
        "description": {"type": "string", "description": "Description of the action"},
        "risk_level": {
            "type": "string",
            "description": "Risk level: low, medium, high, critical",
        },
    },
    "required": ["action", "description", "risk_level"],
}

_GET_AUDIT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "run_id": {"type": "string", "description": "Run ID to get audit trail for"},
        "actor": {"type": "string", "description": "Optional actor filter"},
    },
    "required": ["run_id"],
}

_REDACT_SECRETS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "text": {"type": "string", "description": "Text to redact secrets from"},
    },
    "required": ["text"],
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _error_json(error_type: str, message: str) -> str:
    return json.dumps({"status": "error", "error_type": error_type, "message": message})


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_governance_tools(
    *,
    permission_manager: PermissionManagerPort,
    approval_gate: ApprovalGatePort,
    audit_trail: AuditTrailPort,
    secret_boundary: SecretBoundaryPort,
) -> tuple[dict[str, ToolSpec], dict[str, Callable[..., Any]]]:
    """Create 4 governance tools for agent use.

    Returns (specs dict, executors dict) matching the workspace tools pattern.
    """
    specs: dict[str, ToolSpec] = {}
    executors: dict[str, Callable[..., Any]] = {}

    # 1. check_permission
    def _check_permission(args: dict[str, Any]) -> str:
        profile_name = args.get("profile_name", "")
        action = args.get("action", "")

        if not profile_name:
            return _error_json("validation", "profile_name is required")
        if not action:
            return _error_json("validation", "action is required")

        profile = permission_manager.get_profile(profile_name)
        if profile is None:
            return _error_json("not_found", f"Profile '{profile_name}' not found")

        tool_name = args.get("tool_name")
        allowed = permission_manager.check_permission(profile_name, action, tool_name)

        reason = (
            f"Action '{action}' allowed by profile '{profile_name}' (level={profile.level.name})"
            if allowed
            else f"Action '{action}' denied by profile '{profile_name}' (level={profile.level.name})"
        )

        return json.dumps(
            {"allowed": allowed, "reason": reason, "profile_name": profile_name}
        )

    specs["check_permission"] = ToolSpec(
        name="check_permission",
        description="Check if an action is allowed by a permission profile",
        parameters=_CHECK_PERMISSION_SCHEMA,
    )
    executors["check_permission"] = _check_permission

    # 2. request_approval
    def _request_approval(args: dict[str, Any]) -> str:
        action = args.get("action", "")
        description = args.get("description", "")
        risk_level = args.get("risk_level", "")

        if not action:
            return _error_json("validation", "action is required")
        if not description:
            return _error_json("validation", "description is required")
        if not risk_level:
            return _error_json("validation", "risk_level is required")

        gates = approval_gate.get_gates_for_action(action)
        requires_approval = any(g.requires_approval for g in gates)

        gate_configs = [
            {
                "action_pattern": g.action_pattern,
                "risk_level": g.risk_level,
                "requires_approval": g.requires_approval,
                "auto_approve_below": g.auto_approve_below.name
                if g.auto_approve_below
                else None,
            }
            for g in gates
        ]

        return json.dumps(
            {
                "action": action,
                "description": description,
                "risk_level": risk_level,
                "requires_approval": requires_approval,
                "matching_gates": gate_configs,
            }
        )

    specs["request_approval"] = ToolSpec(
        name="request_approval",
        description="Check if an action requires approval based on configured gates",
        parameters=_REQUEST_APPROVAL_SCHEMA,
    )
    executors["request_approval"] = _request_approval

    # 3. get_audit
    def _get_audit(args: dict[str, Any]) -> str:
        run_id = args.get("run_id", "")
        if not run_id:
            return _error_json("validation", "run_id is required")

        actor = args.get("actor")
        if actor:
            entries = audit_trail.get_entries_by_actor(run_id, actor)
        else:
            trail = audit_trail.get_trail(run_id)
            entries = list(trail.entries)

        return json.dumps(
            {
                "run_id": run_id,
                "actor_filter": actor,
                "entries": [
                    {
                        "entry_id": e.entry_id,
                        "run_id": e.run_id,
                        "timestamp": e.timestamp,
                        "actor": e.actor,
                        "action": e.action,
                        "tool_name": e.tool_name,
                        "file_path": e.file_path,
                        "decision": e.decision,
                        "details": e.details,
                    }
                    for e in entries
                ],
            }
        )

    specs["get_audit"] = ToolSpec(
        name="get_audit",
        description="Get the audit trail for a run, optionally filtered by actor",
        parameters=_GET_AUDIT_SCHEMA,
    )
    executors["get_audit"] = _get_audit

    # 4. redact_secrets
    def _redact_secrets(args: dict[str, Any]) -> str:
        text = args.get("text", "")
        if not text:
            return _error_json("validation", "text is required")

        redacted = secret_boundary.redact(text)
        patterns_found = redacted.count("[REDACTED:")

        return json.dumps(
            {
                "redacted_text": redacted,
                "patterns_found": patterns_found,
            }
        )

    specs["redact_secrets"] = ToolSpec(
        name="redact_secrets",
        description="Redact secrets from text using configured patterns",
        parameters=_REDACT_SECRETS_SCHEMA,
    )
    executors["redact_secrets"] = _redact_secrets

    return specs, executors
