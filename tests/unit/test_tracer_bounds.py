"""Tests for ConsoleTracer bounded span storage -- ended spans must be removed."""

from __future__ import annotations

from cognitia.observability.tracer import ConsoleTracer


class TestTracerRemovesEndedSpans:

    def test_tracer_removes_ended_spans(self) -> None:
        """Start 3 spans, end 2 -- _spans should only contain the 1 active span."""
        tracer = ConsoleTracer()

        s1 = tracer.start_span("op1")
        s2 = tracer.start_span("op2")
        s3 = tracer.start_span("op3")

        assert len(tracer._spans) == 3

        tracer.end_span(s1)
        tracer.end_span(s3)

        # Only s2 should remain
        assert len(tracer._spans) == 1
        assert s2 in tracer._spans
        assert s1 not in tracer._spans
        assert s3 not in tracer._spans

    def test_tracer_end_span_nonexistent_is_noop(self) -> None:
        """Ending a non-existent span should not raise."""
        tracer = ConsoleTracer()
        tracer.end_span("nonexistent_id")  # no error
        assert len(tracer._spans) == 0

    def test_tracer_add_event_to_ended_span_is_noop(self) -> None:
        """After ending a span, adding events to it should be a no-op."""
        tracer = ConsoleTracer()
        s1 = tracer.start_span("op1")
        tracer.end_span(s1)

        # Span was removed, add_event should silently skip
        tracer.add_event(s1, "some_event")
        assert s1 not in tracer._spans
