"""Self-evolution primitives: stuck detection, recovery cascade, lessons extraction."""

from __future__ import annotations

from swarmline.evolution.stuck_detector import (
    StuckDetector,
    StuckDetectorLike,
    StuckSignal,
    ToolCallRecord,
)

__all__ = [
    "StuckDetector",
    "StuckDetectorLike",
    "StuckSignal",
    "ToolCallRecord",
]
