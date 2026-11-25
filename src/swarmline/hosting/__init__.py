"""swarmline.hosting — generic hosted session lifecycle.

Provides a product-neutral session registry (admit / complete / drain),
heartbeat emission at admission, and startup crash detection.

All identifiers are plain str (session_id, owner_id). No
tenant/workspace/AccessContext/billing/FastAPI/SQLAlchemy/Lobu types.

Public API::

    from swarmline.hosting import (
        HeartbeatEmitter,
        RuntimeSessionRegistry,
        StartupCrashDetector,
        StaleSession,
    )

Fly.io / Firecracker sandbox providers are SEPARATE optional packages,
NOT shipped in this core subpackage.

REQ-OSS-050: opt-in / additive — importing this package does not modify
any existing swarmline module.
REQ-OSS-051: zero product coupling.
"""

from swarmline.hosting.crash_detector import StartupCrashDetector, StaleSession
from swarmline.hosting.ports import ClockFactory, FinalizeCallback, HeartbeatEmitter
from swarmline.hosting.session_registry import RuntimeSessionRegistry

__all__ = [
    "ClockFactory",
    "FinalizeCallback",
    "HeartbeatEmitter",
    "RuntimeSessionRegistry",
    "StartupCrashDetector",
    "StaleSession",
]
