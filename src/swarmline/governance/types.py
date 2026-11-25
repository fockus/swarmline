"""Pure domain types for Governance — zero external dependencies.

Types for permission management, approval gates, audit trails, and secret boundaries.
Clean Architecture: no imports from runtime/, infrastructure/, or any SDK.

Types:
- PermissionLevel: READ_ONLY, EDIT, GIT_WRITE, NETWORK_ENABLED, DEPLOY_CAPABLE
- PermissionProfile: frozen profile with name, level, allowed tools, denied patterns
- ApprovalGateConfig: frozen gate config with action pattern and risk level
- AuditEntry: frozen single audit record
- AuditTrail: frozen collection of audit entries for a run
- SecretPattern: frozen pattern for secret redaction
- TrustZone: TRUSTED, UNTRUSTED, SANDBOX
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class PermissionLevel(enum.IntEnum):
    """Hierarchical permission levels — each inherits from lower."""

    READ_ONLY = 1
    EDIT = 2
    GIT_WRITE = 3
    NETWORK_ENABLED = 4
    DEPLOY_CAPABLE = 5


class TrustZone(enum.StrEnum):
    """Trust zone classification for execution contexts."""

    TRUSTED = "trusted"
    UNTRUSTED = "untrusted"
    SANDBOX = "sandbox"


@dataclass(frozen=True, slots=True)
class PermissionProfile:
    """Named permission profile with level, allowed tools, and denied patterns."""

    name: str
    level: PermissionLevel
    allowed_tools: frozenset[str]
    denied_patterns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ApprovalGateConfig:
    """Configuration for an approval gate triggered by action patterns."""

    action_pattern: str
    risk_level: str
    requires_approval: bool
    auto_approve_below: PermissionLevel | None


@dataclass(frozen=True, slots=True)
class AuditEntry:
    """Single audit record for an action taken during a run."""

    entry_id: str
    run_id: str
    timestamp: float
    actor: str
    action: str
    tool_name: str | None
    file_path: str | None
    decision: str | None
    details: dict[str, object]


@dataclass(frozen=True, slots=True)
class AuditTrail:
    """Append-only collection of audit entries for a run."""

    run_id: str
    entries: tuple[AuditEntry, ...]


@dataclass(frozen=True, slots=True)
class SecretPattern:
    """Pattern for detecting and redacting secrets in text."""

    pattern: str
    replacement: str
    description: str
