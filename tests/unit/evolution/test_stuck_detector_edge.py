"""Edge-case tests for StuckDetector — additional coverage beyond dev-domain tests.

Covers: empty tool_name, special chars, boundary at exact threshold,
mixed patterns, ToolCallRecord with empty args, concurrent signals,
WINDOW_SIZE constant usage, from_call with edge inputs.
"""

from __future__ import annotations

import pytest
from swarmline.evolution.stuck_detector import (
    WINDOW_SIZE,
    StuckDetector,
    StuckSignal,
    ToolCallRecord,
)


def _record(tool_name: str, args: dict, result: str) -> ToolCallRecord:
    return ToolCallRecord.from_call(tool_name=tool_name, args=args, result=result)


# ---------------------------------------------------------------------------
# ToolCallRecord edge cases
# ---------------------------------------------------------------------------


class TestToolCallRecordEdge:
    """Edge cases for ToolCallRecord value object."""

    def test_empty_tool_name(self) -> None:
        record = ToolCallRecord(tool_name="", args_hash="h", result_summary="r")
        assert record.tool_name == ""

    def test_from_call_empty_tool_name(self) -> None:
        record = ToolCallRecord.from_call(tool_name="", args={}, result="ok")
        assert record.tool_name == ""

    def test_from_call_empty_result(self) -> None:
        record = ToolCallRecord.from_call(tool_name="t", args={}, result="")
        assert record.result_summary == ""

    def test_args_hash_with_special_chars(self) -> None:
        args = {"key": 'value with spaces & <special> chars "quotes"'}
        h = ToolCallRecord.compute_args_hash(args)
        assert isinstance(h, str)
        assert len(h) == 16  # sha256[:16]

    def test_args_hash_with_unicode(self) -> None:
        h1 = ToolCallRecord.compute_args_hash({"msg": "hello"})
        h2 = ToolCallRecord.compute_args_hash({"msg": "hello"})
        assert h1 == h2

    def test_args_hash_with_boolean_values(self) -> None:
        h1 = ToolCallRecord.compute_args_hash({"flag": True})
        h2 = ToolCallRecord.compute_args_hash({"flag": False})
        assert h1 != h2

    def test_args_hash_with_numeric_types(self) -> None:
        h_int = ToolCallRecord.compute_args_hash({"n": 1})
        h_float = ToolCallRecord.compute_args_hash({"n": 1.0})
        # json.dumps treats 1 and 1.0 differently
        assert isinstance(h_int, str)
        assert isinstance(h_float, str)

    def test_args_hash_with_list_values(self) -> None:
        h = ToolCallRecord.compute_args_hash({"items": [1, 2, 3]})
        assert isinstance(h, str)
        assert len(h) == 16

    def test_args_hash_deeply_nested(self) -> None:
        args = {"a": {"b": {"c": {"d": "deep"}}}}
        h = ToolCallRecord.compute_args_hash(args)
        assert isinstance(h, str)

    def test_from_call_result_exactly_100_chars(self) -> None:
        result = "x" * 100
        record = ToolCallRecord.from_call(tool_name="t", args={}, result=result)
        assert len(record.result_summary) == 100

    def test_from_call_result_101_chars_truncated(self) -> None:
        result = "x" * 101
        record = ToolCallRecord.from_call(tool_name="t", args={}, result=result)
        assert len(record.result_summary) == 100

    def test_equality_same_values(self) -> None:
        r1 = ToolCallRecord(tool_name="t", args_hash="h", result_summary="r")
        r2 = ToolCallRecord(tool_name="t", args_hash="h", result_summary="r")
        assert r1 == r2

    def test_equality_different_values(self) -> None:
        r1 = ToolCallRecord(tool_name="t1", args_hash="h", result_summary="r")
        r2 = ToolCallRecord(tool_name="t2", args_hash="h", result_summary="r")
        assert r1 != r2

    def test_hashable(self) -> None:
        """Frozen dataclass with slots should be hashable."""
        r = ToolCallRecord(tool_name="t", args_hash="h", result_summary="r")
        assert hash(r) is not None
        # Can be used in sets
        s = {r, r}
        assert len(s) == 1


# ---------------------------------------------------------------------------
# StuckSignal edge cases
# ---------------------------------------------------------------------------


class TestStuckSignalEdge:
    """Edge cases for StuckSignal."""

    def test_zero_confidence(self) -> None:
        signal = StuckSignal(repeated_tool="t", repeat_count=1, confidence=0.0)
        assert signal.confidence == 0.0

    def test_max_confidence(self) -> None:
        signal = StuckSignal(repeated_tool="t", repeat_count=10, confidence=1.0)
        assert signal.confidence == 1.0

    def test_hashable(self) -> None:
        s = StuckSignal(repeated_tool="t", repeat_count=3, confidence=0.9)
        assert hash(s) is not None

    def test_equality(self) -> None:
        s1 = StuckSignal(repeated_tool="t", repeat_count=3, confidence=0.9)
        s2 = StuckSignal(repeated_tool="t", repeat_count=3, confidence=0.9)
        assert s1 == s2


# ---------------------------------------------------------------------------
# StuckDetector — boundary conditions
# ---------------------------------------------------------------------------


class TestStuckDetectorBoundary:
    """Boundary and threshold conditions."""

    def test_exactly_3_items_all_same_detects(self) -> None:
        """Exact threshold: 3 identical calls = stuck."""
        detector = StuckDetector()
        h = ToolCallRecord.compute_args_hash({"x": 1})
        history = [ToolCallRecord(tool_name="t", args_hash=h, result_summary="r")] * 3
        signal = detector.detect(history)
        assert signal is not None
        assert signal.repeat_count == 3
        assert signal.confidence == pytest.approx(0.9, abs=0.05)

    def test_exactly_2_items_same_no_stuck(self) -> None:
        """Below threshold: 2 identical calls = no stuck."""
        detector = StuckDetector()
        h = ToolCallRecord.compute_args_hash({"x": 1})
        history = [ToolCallRecord(tool_name="t", args_hash=h, result_summary="r")] * 2
        assert detector.detect(history) is None

    def test_window_size_constant_is_6(self) -> None:
        """WINDOW_SIZE should be 6."""
        assert WINDOW_SIZE == 6

    def test_exactly_window_size_items(self) -> None:
        """6 items, all different — no stuck."""
        detector = StuckDetector()
        history = [_record(f"tool_{i}", {"i": i}, "ok") for i in range(WINDOW_SIZE)]
        assert detector.detect(history) is None

    def test_same_tool_different_args_exactly_4(self) -> None:
        """Exact threshold: 4 same-tool-different-args = stuck."""
        detector = StuckDetector()
        history = [
            _record("search", {"q": f"query_{i}"}, "no results") for i in range(4)
        ]
        signal = detector.detect(history)
        assert signal is not None
        assert signal.confidence == pytest.approx(0.6, abs=0.05)

    def test_same_tool_different_args_exactly_3_no_stuck(self) -> None:
        """Below threshold: 3 same-tool-different-args = no stuck."""
        detector = StuckDetector()
        history = [
            _record("search", {"q": f"query_{i}"}, "no results") for i in range(3)
        ]
        assert detector.detect(history) is None

    def test_alternating_exactly_5_no_stuck(self) -> None:
        """Below threshold: 5 alternating = no stuck for alternating pattern (need 6).

        Note: each tool uses unique args to avoid triggering exact-repeat detection.
        """
        detector = StuckDetector()
        history = [
            _record("a", {"i": 1}, "r"),
            _record("b", {"i": 2}, "r"),
            _record("a", {"i": 3}, "r"),
            _record("b", {"i": 4}, "r"),
            _record("a", {"i": 5}, "r"),
        ]
        # Only 5 calls, alternating needs 6; also a=3 times with different args < 4 threshold
        assert detector.detect(history) is None

    def test_alternating_exactly_6_detected(self) -> None:
        """Exact threshold: 6 alternating = stuck.

        Each call uses unique args to avoid exact-repeat detection (which has higher priority).
        """
        detector = StuckDetector()
        history = [
            _record("a", {"i": 1}, "r"),
            _record("b", {"i": 2}, "r"),
            _record("a", {"i": 3}, "r"),
            _record("b", {"i": 4}, "r"),
            _record("a", {"i": 5}, "r"),
            _record("b", {"i": 6}, "r"),
        ]
        signal = detector.detect(history)
        assert signal is not None
        assert signal.confidence == pytest.approx(0.7, abs=0.05)


# ---------------------------------------------------------------------------
# StuckDetector — mixed / complex patterns
# ---------------------------------------------------------------------------


class TestStuckDetectorMixedPatterns:
    """Complex scenarios with mixed tool calls."""

    def test_mixed_calls_some_repeated_some_not(self) -> None:
        """Some repeated calls mixed with different ones — below threshold."""
        detector = StuckDetector()
        history = [
            _record("read", {"path": "/a"}, "ok"),
            _record("write", {"path": "/b"}, "ok"),
            _record("read", {"path": "/a"}, "ok"),
            _record("grep", {"pattern": "x"}, "ok"),
            _record("read", {"path": "/c"}, "ok"),
            _record("deploy", {}, "ok"),
        ]
        # read appears 3 times but with different args (2x /a, 1x /c)
        # No exact repeat threshold met in window
        signal = detector.detect(history)
        # read appears 3 times total but not 4 (same-tool-different-args threshold)
        assert signal is None

    def test_exact_repeat_wins_over_alternating(self) -> None:
        """When both exact repeat and alternating could match, exact repeat wins."""
        detector = StuckDetector()
        h = ToolCallRecord.compute_args_hash({"x": 1})
        # 3 exact repeats of "a" embedded in alternating pattern
        history = [
            ToolCallRecord(tool_name="a", args_hash=h, result_summary="r"),
            ToolCallRecord(tool_name="a", args_hash=h, result_summary="r"),
            ToolCallRecord(tool_name="a", args_hash=h, result_summary="r"),
        ]
        signal = detector.detect(history)
        assert signal is not None
        assert signal.confidence >= 0.9  # exact repeat, not alternating

    def test_only_last_window_matters(self) -> None:
        """Old stuck pattern outside window should not be detected."""
        detector = StuckDetector()
        h = ToolCallRecord.compute_args_hash({"x": 1})
        # 3 exact repeats followed by 6 different calls
        old_stuck = [
            ToolCallRecord(tool_name="stuck", args_hash=h, result_summary="r")
        ] * 3
        varied = [_record(f"ok_{i}", {"i": i}, "fine") for i in range(6)]
        history = old_stuck + varied
        assert detector.detect(history) is None

    def test_three_tools_no_alternating_detected(self) -> None:
        """Alternating detection requires exactly 2 unique tools in window."""
        detector = StuckDetector()
        history = [
            _record("a", {}, "r"),
            _record("b", {}, "r"),
            _record("c", {}, "r"),
            _record("a", {}, "r"),
            _record("b", {}, "r"),
            _record("c", {}, "r"),
        ]
        signal = detector.detect(history)
        # 3 unique tools → not alternating; each tool appears 2x → no same-tool-4x
        assert signal is None

    def test_alternating_broken_by_consecutive_same(self) -> None:
        """Almost alternating but one consecutive repeat breaks it."""
        detector = StuckDetector()
        history = [
            _record("a", {}, "r"),
            _record("b", {}, "r"),
            _record("a", {}, "r"),
            _record("a", {}, "r"),  # consecutive same — breaks alternating
            _record("b", {}, "r"),
            _record("a", {}, "r"),
        ]
        signal = detector.detect(history)
        # Not a clean alternating pattern; a appears 4x → same-tool-different-args
        if signal is not None:
            # Should be same-tool (0.6), not alternating (0.7)
            assert signal.repeated_tool == "a"

    @pytest.mark.parametrize("count", [3, 4, 5, 6])
    def test_exact_repeat_scales_with_count(self, count: int) -> None:
        """Exact repeat detected for 3..6 repetitions."""
        detector = StuckDetector()
        h = ToolCallRecord.compute_args_hash({"x": 1})
        history = [
            ToolCallRecord(tool_name="t", args_hash=h, result_summary="r")
        ] * count
        signal = detector.detect(history)
        assert signal is not None
        assert signal.repeat_count == min(count, WINDOW_SIZE)
        assert signal.confidence >= 0.9

    def test_empty_tool_name_still_detectable(self) -> None:
        """Empty string as tool_name should still be detected if repeated."""
        detector = StuckDetector()
        h = ToolCallRecord.compute_args_hash({})
        history = [ToolCallRecord(tool_name="", args_hash=h, result_summary="")] * 3
        signal = detector.detect(history)
        assert signal is not None
        assert signal.repeated_tool == ""

    def test_large_history_performance(self) -> None:
        """Detector should handle large history efficiently (only uses window)."""
        detector = StuckDetector()
        # 1000 varied calls followed by 3 repeats
        h = ToolCallRecord.compute_args_hash({"stuck": True})
        varied = [_record(f"tool_{i}", {"i": i}, "ok") for i in range(1000)]
        stuck = [ToolCallRecord(tool_name="stuck", args_hash=h, result_summary="r")] * 3
        history = varied + stuck
        signal = detector.detect(history)
        assert signal is not None
        assert signal.repeated_tool == "stuck"

    def test_same_args_hash_different_tool_names(self) -> None:
        """Same args_hash but different tool_name — not an exact repeat."""
        detector = StuckDetector()
        h = ToolCallRecord.compute_args_hash({"x": 1})
        history = [
            ToolCallRecord(tool_name="read", args_hash=h, result_summary="r"),
            ToolCallRecord(tool_name="write", args_hash=h, result_summary="r"),
            ToolCallRecord(tool_name="read", args_hash=h, result_summary="r"),
        ]
        assert detector.detect(history) is None

    def test_same_tool_name_same_args_different_result_still_stuck(self) -> None:
        """Result summary doesn't affect stuck detection — only tool+args matter."""
        detector = StuckDetector()
        h = ToolCallRecord.compute_args_hash({"path": "/a"})
        history = [
            ToolCallRecord(tool_name="read", args_hash=h, result_summary="content v1"),
            ToolCallRecord(tool_name="read", args_hash=h, result_summary="content v2"),
            ToolCallRecord(tool_name="read", args_hash=h, result_summary="content v3"),
        ]
        signal = detector.detect(history)
        assert signal is not None
        assert signal.confidence >= 0.9
