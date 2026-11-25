"""Governance protocols — ISP-compliant ports for permission, approval, audit, secrets.

Each protocol has at most 5 methods. All are @runtime_checkable.
Imports only from governance.types (pure domain).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from swarmline.governance.types import (
    ApprovalGateConfig,
    AuditEntry,
    AuditTrail,
    PermissionLevel,
    PermissionProfile,
    SecretPattern,
    TrustZone,
)


@runtime_checkable
class PermissionManagerPort(Protocol):
    """Port for checking permissions against named profiles.

    Methods: 3 (ISP ≤5 compliant)
    """

    def check_permission(
        self, profile_name: str, action: str, tool_name: str | None = None
    ) -> bool: ...

    def get_profile(self, name: str) -> PermissionProfile | None: ...

    def list_profiles(self) -> list[PermissionProfile]: ...


@runtime_checkable
class ApprovalGatePort(Protocol):
    """Port for checking approval gates by action pattern.

    Methods: 2 (ISP ≤5 compliant)
    """

    def check_gate(
        self, action: str, profile_level: PermissionLevel
    ) -> ApprovalGateConfig | None: ...

    def get_gates_for_action(self, action: str) -> list[ApprovalGateConfig]: ...


@runtime_checkable
class AuditTrailPort(Protocol):
    """Port for recording and querying audit entries.

    Methods: 3 (ISP ≤5 compliant)
    """

    def record(self, entry: AuditEntry) -> None: ...

    def get_trail(self, run_id: str) -> AuditTrail: ...

    def get_entries_by_actor(self, run_id: str, actor: str) -> list[AuditEntry]: ...


@runtime_checkable
class SecretBoundaryPort(Protocol):
    """Port for redacting secrets and checking trust zones.

    Methods: 3 (ISP ≤5 compliant)
    """

    def redact(self, text: str) -> str: ...

    def is_trusted_zone(self, zone: TrustZone) -> bool: ...

    def get_patterns(self) -> list[SecretPattern]: ...
