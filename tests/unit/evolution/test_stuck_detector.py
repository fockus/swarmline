"""Tests for StuckDetector — semantic loop detection.

TDD Red phase: all tests written before implementation.
Covers: exact repeat, same-tool-different-args, alternating tools, edge cases.
"""

from __future__ import annotations

import pytest
from swarmline.evolution.stuck_detector import (
    StuckDetector,
    StuckDetectorLike,
    StuckSignal,
    ToolCallRecord,
)

# ---------------------------------------------------------------------------
# ToolCallRecord — frozen dataclass
# ---------------------------------------------------------------------------


class TestToolCallRecord:
    """ToolCallRecord value object tests."""

    def test_frozen(self) -> None:
        record = ToolCallRecord(
            tool_name="read_file",
            args_hash="abc123",
            result_summary="file contents...",
        )
        with pytest.raises(AttributeError):
            record.tool_name = "other"  # type: ignore[misc]

    def test_args_hash_deterministic(self) -> None:
        args = {"path": "/a.py", "line": 10}
        h1 = ToolCallRecord.compute_args_hash(args)
        h2 = ToolCallRecord.compute_args_hash(args)
        assert h1 == h2

    def test_args_hash_key_order_independent(self) -> None:
        args1 = {"b": 2, "a": 1}
        args2 = {"a": 1, "b": 2}
        assert ToolCallRecord.compute_args_hash(
            args1
        ) == ToolCallRecord.compute_args_hash(args2)

    def test_args_hash_different_values_differ(self) -> None:
        h1 = ToolCallRecord.compute_args_hash({"x": 1})
        h2 = ToolCallRecord.compute_args_hash({"x": 2})
        assert h1 != h2

    def test_args_hash_empty_dict(self) -> None:
        h = ToolCallRecord.compute_args_hash({})
        assert isinstance(h, str)
        assert len(h) > 0

    def test_result_summary_truncated(self) -> None:
        record = ToolCallRecord(
            tool_name="t",
            args_hash="h",
            result_summary="x" * 200,
        )
        assert len(record.result_summary) <= 200

    def test_from_call_factory(self) -> None:
        record = ToolCallRecord.from_call(
            tool_name="grep",
            args={"pattern": "foo", "path": "/src"},
            result="found 3 matches in file.py",
        )
        assert record.tool_name == "grep"
        assert isinstance(record.args_hash, str)
        assert record.result_summary == "found 3 matches in file.py"

    def test_from_call_truncates_result(self) -> None:
        record = ToolCallRecord.from_call(
            tool_name="read",
            args={},
            result="a" * 500,
        )
        assert len(record.result_summary) <= 100


# ---------------------------------------------------------------------------
# StuckSignal — frozen dataclass
# ---------------------------------------------------------------------------


class TestStuckSignal:
    """StuckSignal value object tests."""

    def test_frozen(self) -> None:
        signal = StuckSignal(
            repeated_tool="read_file",
            repeat_count=3,
            confidence=0.9,
        )
        with pytest.raises(AttributeError):
            signal.confidence = 0.5  # type: ignore[misc]

    def test_confidence_range(self) -> None:
        signal = StuckSignal(repeated_tool="t", repeat_count=3, confidence=0.9)
        assert 0.0 <= signal.confidence <= 1.0


# ---------------------------------------------------------------------------
# StuckDetector — Protocol conformance
# ---------------------------------------------------------------------------


class TestStuckDetectorProtocol:
    """Verify StuckDetector satisfies StuckDetectorLike protocol."""

    def test_implements_protocol(self) -> None:
        detector = StuckDetector()
        assert isinstance(detector, StuckDetectorLike)


# ---------------------------------------------------------------------------
# StuckDetector — no stuck (normal operation)
# ---------------------------------------------------------------------------


class TestStuckDetectorNoStuck:
    """Normal operation — no stuck patterns detected."""

    def test_empty_history_returns_none(self) -> None:
        detector = StuckDetector()
        assert detector.detect([]) is None

    def test_single_call_returns_none(self) -> None:
        detector = StuckDetector()
        history = [_record("read_file", {"path": "/a.py"}, "contents")]
        assert detector.detect(history) is None

    def test_two_calls_same_tool_same_args_returns_none(self) -> None:
        detector = StuckDetector()
        history = [
            _record("read_file", {"path": "/a.py"}, "contents"),
            _record("read_file", {"path": "/a.py"}, "contents"),
        ]
        assert detector.detect(history) is None

    def test_different_tools_returns_none(self) -> None:
        detector = StuckDetector()
        history = [
            _record("read_file", {"path": "/a.py"}, "ok"),
            _record("write_file", {"path": "/b.py"}, "ok"),
            _record("grep", {"pattern": "foo"}, "ok"),
            _record("list_files", {}, "ok"),
            _record("run_test", {}, "ok"),
            _record("deploy", {}, "ok"),
        ]
        assert detector.detect(history) is None

    def test_same_tool_same_args_two_times_no_stuck(self) -> None:
        detector = StuckDetector()
        history = [
            _record("read_file", {"path": "/a.py"}, "contents"),
            _record("write_file", {"path": "/b.py"}, "ok"),
            _record("read_file", {"path": "/a.py"}, "contents"),
        ]
        assert detector.detect(history) is None


# ---------------------------------------------------------------------------
# Pattern 1: Exact repeat 3+ times (same tool + same args)
# ---------------------------------------------------------------------------


class TestStuckDetectorExactRepeat:
    """Same tool_name + same args_hash 3+ times in last 6 calls."""

    def test_exact_repeat_3_times_detected(self) -> None:
        detector = StuckDetector()
        h = ToolCallRecord.compute_args_hash({"path": "/a.py"})
        history = [
            ToolCallRecord(tool_name="read_file", args_hash=h, result_summary="ok"),
            ToolCallRecord(tool_name="read_file", args_hash=h, result_summary="ok"),
            ToolCallRecord(tool_name="read_file", args_hash=h, result_summary="ok"),
        ]
        signal = detector.detect(history)
        assert signal is not None
        assert signal.repeated_tool == "read_file"
        assert signal.repeat_count >= 3
        assert signal.confidence == pytest.approx(0.9, abs=0.05)

    def test_exact_repeat_4_times_detected(self) -> None:
        detector = StuckDetector()
        h = ToolCallRecord.compute_args_hash({"x": 1})
        history = [
            ToolCallRecord(tool_name="grep", args_hash=h, result_summary="r")
        ] * 4
        signal = detector.detect(history)
        assert signal is not None
        assert signal.repeat_count >= 4
        assert signal.confidence >= 0.9

    def test_exact_repeat_outside_window_not_detected(self) -> None:
        detector = StuckDetector()
        h = ToolCallRecord.compute_args_hash({"path": "/a.py"})
        # 3 repeats spread across >6 calls — only 2 in last 6
        history = [
            ToolCallRecord(tool_name="read_file", args_hash=h, result_summary="ok"),
            _record("other1", {}, "ok"),
            _record("other2", {}, "ok"),
            _record("other3", {}, "ok"),
            _record("other4", {}, "ok"),
            ToolCallRecord(tool_name="read_file", args_hash=h, result_summary="ok"),
            ToolCallRecord(tool_name="read_file", args_hash=h, result_summary="ok"),
        ]
        # Last 6: [other1, other2, other3, other4, read_file, read_file] — only 2 repeats
        signal = detector.detect(history)
        assert signal is None

    def test_exact_repeat_within_window_detected(self) -> None:
        detector = StuckDetector()
        h = ToolCallRecord.compute_args_hash({"path": "/a.py"})
        # 3 repeats within last 6 calls
        history = [
            _record("setup", {}, "ok"),
            _record("other", {}, "ok"),
            _record("other2", {}, "ok"),
            ToolCallRecord(tool_name="read_file", args_hash=h, result_summary="ok"),
            ToolCallRecord(tool_name="read_file", args_hash=h, result_summary="ok"),
            ToolCallRecord(tool_name="read_file", args_hash=h, result_summary="ok"),
        ]
        signal = detector.detect(history)
        assert signal is not None
        assert signal.repeated_tool == "read_file"


# ---------------------------------------------------------------------------
# Pattern 2: Same tool, different args 4+ times
# ---------------------------------------------------------------------------


class TestStuckDetectorSameToolDifferentArgs:
    """Same tool_name but different args_hash 4+ times → possible stuck."""

    def test_same_tool_different_args_4_times(self) -> None:
        detector = StuckDetector()
        history = [
            _record("grep", {"pattern": "a"}, "no match"),
            _record("grep", {"pattern": "b"}, "no match"),
            _record("grep", {"pattern": "c"}, "no match"),
            _record("grep", {"pattern": "d"}, "no match"),
        ]
        signal = detector.detect(history)
        assert signal is not None
        assert signal.repeated_tool == "grep"
        assert signal.repeat_count >= 4
        assert signal.confidence == pytest.approx(0.6, abs=0.05)

    def test_same_tool_different_args_3_times_no_stuck(self) -> None:
        detector = StuckDetector()
        history = [
            _record("grep", {"pattern": "a"}, "no match"),
            _record("grep", {"pattern": "b"}, "no match"),
            _record("grep", {"pattern": "c"}, "no match"),
        ]
        assert detector.detect(history) is None

    def test_same_tool_5_times_mixed_args(self) -> None:
        detector = StuckDetector()
        history = [
            _record("write_file", {"path": "/a"}, "ok"),
            _record("write_file", {"path": "/b"}, "ok"),
            _record("write_file", {"path": "/a"}, "ok"),
            _record("write_file", {"path": "/c"}, "ok"),
            _record("write_file", {"path": "/d"}, "ok"),
        ]
        signal = detector.detect(history)
        assert signal is not None
        assert signal.repeated_tool == "write_file"


# ---------------------------------------------------------------------------
# Pattern 3: Alternating between 2 tools 6+ times
# ---------------------------------------------------------------------------


class TestStuckDetectorAlternating:
    """Alternating between 2 tools 6+ times → stuck."""

    def test_alternating_6_times_detected(self) -> None:
        detector = StuckDetector()
        # Use different args each time to avoid triggering exact-repeat (0.9)
        history = [
            _record("read_file", {"path": "/a"}, "content"),
            _record("write_file", {"path": "/b"}, "ok"),
            _record("read_file", {"path": "/c"}, "content"),
            _record("write_file", {"path": "/d"}, "ok"),
            _record("read_file", {"path": "/e"}, "content"),
            _record("write_file", {"path": "/f"}, "ok"),
        ]
        signal = detector.detect(history)
        assert signal is not None
        assert signal.confidence == pytest.approx(0.7, abs=0.05)

    def test_alternating_4_times_not_detected(self) -> None:
        detector = StuckDetector()
        history = [
            _record("read_file", {"path": "/a"}, "content"),
            _record("write_file", {"path": "/a"}, "ok"),
            _record("read_file", {"path": "/a"}, "content"),
            _record("write_file", {"path": "/a"}, "ok"),
        ]
        # 4 alternations — not enough (need 6)
        signal = detector.detect(history)
        # Should not trigger alternating pattern (only 4)
        assert signal is None

    def test_alternating_8_times_detected(self) -> None:
        detector = StuckDetector()
        history = [
            _record("a", {}, "r"),
            _record("b", {}, "r"),
            _record("a", {}, "r"),
            _record("b", {}, "r"),
            _record("a", {}, "r"),
            _record("b", {}, "r"),
            _record("a", {}, "r"),
            _record("b", {}, "r"),
        ]
        signal = detector.detect(history)
        assert signal is not None
        assert signal.confidence >= 0.7


# ---------------------------------------------------------------------------
# Priority: exact repeat wins over same-tool-different-args
# ---------------------------------------------------------------------------


class TestStuckDetectorPriority:
    """Higher confidence pattern wins when multiple match."""

    def test_exact_repeat_takes_priority_over_same_tool(self) -> None:
        detector = StuckDetector()
        h = ToolCallRecord.compute_args_hash({"x": 1})
        # 3 exact repeats (0.9) + also 3+ same tool (could trigger 0.6)
        history = [
            ToolCallRecord(tool_name="grep", args_hash=h, result_summary="r"),
            ToolCallRecord(tool_name="grep", args_hash=h, result_summary="r"),
            ToolCallRecord(tool_name="grep", args_hash=h, result_summary="r"),
        ]
        signal = detector.detect(history)
        assert signal is not None
        assert signal.confidence >= 0.9  # exact repeat priority


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestStuckDetectorEdgeCases:
    """Edge cases and boundary conditions."""

    def test_history_longer_than_window(self) -> None:
        detector = StuckDetector()
        # 10 different calls, last 3 are repeats
        h = ToolCallRecord.compute_args_hash({"path": "/x"})
        varied = [_record(f"tool_{i}", {}, "ok") for i in range(7)]
        repeats = [
            ToolCallRecord(tool_name="stuck", args_hash=h, result_summary="r")
        ] * 3
        history = varied + repeats
        signal = detector.detect(history)
        assert signal is not None
        assert signal.repeated_tool == "stuck"

    def test_window_size_is_6(self) -> None:
        detector = StuckDetector()
        # Only looks at last 6 calls
        h = ToolCallRecord.compute_args_hash({"x": 1})
        # 3 repeats then 6 different calls — no stuck in window
        repeats = [
            ToolCallRecord(tool_name="stuck", args_hash=h, result_summary="r")
        ] * 3
        varied = [_record(f"tool_{i}", {}, "ok") for i in range(6)]
        history = repeats + varied
        assert detector.detect(history) is None

    def test_args_hash_with_nested_dict(self) -> None:
        args = {"outer": {"inner": "value"}, "list": [1, 2, 3]}
        h = ToolCallRecord.compute_args_hash(args)
        assert isinstance(h, str)
        assert len(h) > 0

    def test_args_hash_with_none_values(self) -> None:
        h1 = ToolCallRecord.compute_args_hash({"key": None})
        h2 = ToolCallRecord.compute_args_hash({"key": None})
        assert h1 == h2


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _record(tool_name: str, args: dict, result: str) -> ToolCallRecord:
    """Create a ToolCallRecord for testing."""
    return ToolCallRecord.from_call(tool_name=tool_name, args=args, result=result)
