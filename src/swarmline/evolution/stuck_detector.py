"""StuckDetector — semantic loop detection for agent tool-call history.

Detects three patterns of stuck behavior in a sliding window:
1. Exact repeat: same tool + same args 3+ times (confidence 0.9). When a record
   carries ``result_hash``, the result must repeat too: the same call whose result
   keeps changing (polling) is progress, not a loop.
2. Same tool, different args: 4+ times (confidence 0.6)
3. Alternating between 2 tools: 6+ calls (confidence 0.7)

Pure domain logic — no external dependencies.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

WINDOW_SIZE = 6
EXACT_REPEAT_THRESHOLD = 3

# Volatile parts of a tool result that change between otherwise identical calls.
_ISO_TIMESTAMP = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?"
)
_UUID = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
_VOLATILE_KEY = re.compile(r"^(duration|elapsed|pid)(_\w+)?$", re.IGNORECASE)


def _drop_volatile(value: object) -> object:
    if isinstance(value, dict):
        return {
            k: _drop_volatile(v)
            for k, v in value.items()
            if not _VOLATILE_KEY.match(str(k))
        }
    if isinstance(value, list):
        return [_drop_volatile(v) for v in value]
    return value


@dataclass(frozen=True, slots=True)
class ToolCallRecord:
    """Immutable record of a single tool call in agent history."""

    tool_name: str
    args_hash: str
    result_summary: str
    # Optional fingerprint of the (de-volatilised) result. None keeps the
    # pre-existing (tool, args) repeat semantics.
    result_hash: str | None = None

    @property
    def repeat_key(self) -> tuple[str, str, str | None]:
        """Identity of a call for exact-repeat detection."""
        return (self.tool_name, self.args_hash, self.result_hash)

    @staticmethod
    def compute_args_hash(args: dict) -> str:  # type: ignore[type-arg]
        """Deterministic hash of sorted JSON keys+values."""
        canonical = json.dumps(args, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]

    @staticmethod
    def compute_result_hash(result: str) -> str:
        """Hash of a result with ISO timestamps, UUIDs and ``duration``/``elapsed``/
        ``pid`` JSON fields removed, so a re-run returning the same data matches."""
        try:
            data = _drop_volatile(json.loads(result))
            canonical = json.dumps(data, sort_keys=True, default=str)
        except (ValueError, TypeError):
            canonical = str(result)
        canonical = _UUID.sub("<uuid>", _ISO_TIMESTAMP.sub("<ts>", canonical))
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]

    @classmethod
    def from_call(cls, tool_name: str, args: dict, result: str) -> ToolCallRecord:  # type: ignore[type-arg]
        """Factory: create from raw call data, truncating result to 100 chars."""
        return cls(
            tool_name=tool_name,
            args_hash=cls.compute_args_hash(args),
            result_summary=result[:100],
        )


@dataclass(frozen=True, slots=True)
class StuckSignal:
    """Signal emitted when a stuck pattern is detected."""

    repeated_tool: str
    repeat_count: int
    confidence: float  # 0.0 – 1.0


@runtime_checkable
class StuckDetectorLike(Protocol):
    """Port: stuck detection contract."""

    def detect(self, history: list[ToolCallRecord]) -> StuckSignal | None: ...


class StuckDetector:
    """Stateless stuck detector operating on a sliding window of tool calls."""

    def detect(self, history: list[ToolCallRecord]) -> StuckSignal | None:
        """Analyse the last WINDOW_SIZE tool calls for stuck patterns.

        Returns the highest-confidence signal found, or None.
        """
        if len(history) < 3:
            return None

        window = history[-WINDOW_SIZE:]

        # Priority order: exact repeat (0.9) > alternating (0.7) > same tool (0.6)
        exact = self._detect_exact_repeat(window)
        if exact is not None:
            return exact

        alternating = self._detect_alternating(window)
        if alternating is not None:
            return alternating

        same_tool = self._detect_same_tool_different_args(window)
        if same_tool is not None:
            return same_tool

        return None

    def detect_latest_repeat(self, history: list[ToolCallRecord]) -> StuckSignal | None:
        """Exact repeat that INCLUDES the latest call.

        Unlike ``detect``, an old loop the model has already left does not keep
        signalling while it lingers in the window.
        """
        if not history:
            return None
        window = history[-WINDOW_SIZE:]
        latest = window[-1].repeat_key
        count = sum(1 for record in window if record.repeat_key == latest)
        if count < EXACT_REPEAT_THRESHOLD:
            return None
        return StuckSignal(repeated_tool=latest[0], repeat_count=count, confidence=0.9)

    @staticmethod
    def _detect_exact_repeat(window: list[ToolCallRecord]) -> StuckSignal | None:
        """Same tool_name + same args_hash (+ result_hash when set) 3+ times in window."""
        counts: Counter[tuple[str, str, str | None]] = Counter()
        for record in window:
            counts[record.repeat_key] += 1

        for (tool_name, _, _), count in counts.most_common(1):
            if count >= EXACT_REPEAT_THRESHOLD:
                return StuckSignal(
                    repeated_tool=tool_name,
                    repeat_count=count,
                    confidence=0.9,
                )
        return None

    @staticmethod
    def _detect_same_tool_different_args(
        window: list[ToolCallRecord],
    ) -> StuckSignal | None:
        """Same tool_name with different args 4+ times in window."""
        tool_counts: Counter[str] = Counter()
        for record in window:
            tool_counts[record.tool_name] += 1

        for tool_name, count in tool_counts.most_common(1):
            if count >= 4:
                return StuckSignal(
                    repeated_tool=tool_name,
                    repeat_count=count,
                    confidence=0.6,
                )
        return None

    @staticmethod
    def _detect_alternating(window: list[ToolCallRecord]) -> StuckSignal | None:
        """Alternating between exactly 2 tools for 6+ calls."""
        if len(window) < 6:
            return None

        unique_tools = {r.tool_name for r in window}
        if len(unique_tools) != 2:
            return None

        # Check if the pattern is truly alternating
        tools_list = [r.tool_name for r in window]
        for i in range(len(tools_list) - 1):
            if tools_list[i] == tools_list[i + 1]:
                return None

        tool_a, tool_b = sorted(unique_tools)
        return StuckSignal(
            repeated_tool=f"{tool_a}/{tool_b}",
            repeat_count=len(window),
            confidence=0.7,
        )
