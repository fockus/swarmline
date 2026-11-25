"""Governance package — permissions, approval gates, audit trails, secret boundaries.

Lazy exports via __getattr__ to keep import cost minimal.
"""

from __future__ import annotations

_TYPE_EXPORTS = {
    "PermissionLevel",
    "PermissionProfile",
    "ApprovalGateConfig",
    "AuditEntry",
    "AuditTrail",
    "SecretPattern",
    "TrustZone",
}

_PROTOCOL_EXPORTS = {
    "PermissionManagerPort",
    "ApprovalGatePort",
    "AuditTrailPort",
    "SecretBoundaryPort",
}

_PERMISSION_MANAGER_EXPORTS = {
    "PermissionManager",
}

_APPROVAL_GATES_EXPORTS = {
    "ApprovalGateManager",
}

_AUDIT_TRAIL_EXPORTS = {
    "InMemoryAuditTrail",
}

_SECRET_BOUNDARY_EXPORTS = {
    "SecretBoundaryManager",
}

_GOVERNANCE_TOOLS_EXPORTS = {
    "create_governance_tools",
}

_ALL_EXPORTS = (
    _TYPE_EXPORTS
    | _PROTOCOL_EXPORTS
    | _PERMISSION_MANAGER_EXPORTS
    | _APPROVAL_GATES_EXPORTS
    | _AUDIT_TRAIL_EXPORTS
    | _SECRET_BOUNDARY_EXPORTS
    | _GOVERNANCE_TOOLS_EXPORTS
)

__all__ = list(_ALL_EXPORTS)

_MODULE_MAP: dict[str, str] = {
    **{name: "types" for name in _TYPE_EXPORTS},
    **{name: "protocols" for name in _PROTOCOL_EXPORTS},
    **{name: "permission_manager" for name in _PERMISSION_MANAGER_EXPORTS},
    **{name: "approval_gates" for name in _APPROVAL_GATES_EXPORTS},
    **{name: "audit_trail" for name in _AUDIT_TRAIL_EXPORTS},
    **{name: "secret_boundary" for name in _SECRET_BOUNDARY_EXPORTS},
    **{name: "governance_tools" for name in _GOVERNANCE_TOOLS_EXPORTS},
}


def __getattr__(name: str) -> object:
    module_name = _MODULE_MAP.get(name)
    if module_name is not None:
        import importlib

        mod = importlib.import_module(f"swarmline.governance.{module_name}")
        return getattr(mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
