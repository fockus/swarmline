"""Unit: Result - unified result query Agent facade."""

from __future__ import annotations

from swarmline.agent.result import Result


class TestResultDefaults:
    """Empty Result."""

    def test_empty_result(self) -> None:
        r = Result()
        assert r.text == ""
        assert r.session_id is None
        assert r.total_cost_usd is None
        assert r.usage is None
        assert r.structured_output is None
        assert r.native_metadata is None
        assert r.error is None

    def test_ok_when_no_error(self) -> None:
        r = Result(text="ответ")
        assert r.ok is True

    def test_not_ok_when_error(self) -> None:
        r = Result(error="что-то пошло не так")
        assert r.ok is False


class TestResultWithMetrics:
    """Result with metrics."""

    def test_full_metrics(self) -> None:
        r = Result(
            text="ответ",
            session_id="sess-123",
            total_cost_usd=0.05,
            usage={"input_tokens": 100, "output_tokens": 50},
        )
        assert r.text == "ответ"
        assert r.session_id == "sess-123"
        assert r.total_cost_usd == 0.05
        assert r.usage == {"input_tokens": 100, "output_tokens": 50}


class TestResultStructuredOutput:
    """Structured output."""

    def test_structured_output(self) -> None:
        r = Result(
            text="",
            structured_output={"score": 85, "confidence": 0.92},
        )
        assert r.structured_output == {"score": 85, "confidence": 0.92}

    def test_structured_output_with_text(self) -> None:
        """structured_output and text can coexist."""
        r = Result(
            text="Score: 85",
            structured_output={"score": 85},
        )
        assert r.text == "Score: 85"
        assert r.structured_output == {"score": 85}
        assert r.ok is True

    def test_native_metadata(self) -> None:
        r = Result(
            text="ok",
            native_metadata={
                "thread_id": "thread-1",
                "history_source": "native_thread",
            },
        )
        assert r.native_metadata == {
            "thread_id": "thread-1",
            "history_source": "native_thread",
        }


class TestResultError:
    """Error result."""

    def test_error_result(self) -> None:
        r = Result(error="SDK timeout")
        assert r.ok is False
        assert r.error == "SDK timeout"
        assert r.text == ""

    def test_error_with_partial_text(self) -> None:
        """Error may contain partial text."""
        r = Result(text="partial...", error="connection lost")
        assert r.ok is False
        assert r.text == "partial..."


class TestResultImmutable:
    """Result — frozen dataclass."""

    def test_frozen(self) -> None:
        import dataclasses

        import pytest

        r = Result(text="test")
        with pytest.raises(dataclasses.FrozenInstanceError):
            r.text = "new"  # type: ignore[misc]
