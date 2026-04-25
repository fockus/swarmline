"""Unit tests for JSONL telemetry sink."""

from __future__ import annotations

import json
from pathlib import Path

from swarmline.observability.event_bus import InMemoryEventBus
from swarmline.observability.jsonl_sink import JsonlTelemetrySink


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class TestJsonlTelemetrySinkRecord:
    async def test_record_writes_append_only_json_line(self, tmp_path: Path) -> None:
        log_path = tmp_path / "events.jsonl"
        sink = JsonlTelemetrySink(log_path)

        await sink.record("pipeline_stage_end", {"stage": "draft", "ok": True})

        rows = _read_jsonl(log_path)
        assert rows[0]["event_type"] == "pipeline_stage_end"
        assert rows[0]["data"] == {"stage": "draft", "ok": True}
        assert rows[0]["schema_version"] == 1
        assert "timestamp" in rows[0]

    async def test_record_redacts_sensitive_keys_recursively(
        self, tmp_path: Path
    ) -> None:
        log_path = tmp_path / "events.jsonl"
        sink = JsonlTelemetrySink(log_path)

        await sink.record(
            "llm_call_start",
            {
                "api_key": "sk-secret",
                "nested": {"token": "abc", "safe": "value"},
                "items": [{"password": "p", "name": "model"}],
            },
        )

        row = _read_jsonl(log_path)[0]
        assert row["data"]["api_key"] == "[REDACTED]"
        assert row["data"]["nested"] == {"token": "[REDACTED]", "safe": "value"}
        assert row["data"]["items"][0] == {"password": "[REDACTED]", "name": "model"}


class TestJsonlTelemetrySinkAttach:
    async def test_attach_subscribes_to_selected_event_types(
        self, tmp_path: Path
    ) -> None:
        bus = InMemoryEventBus()
        log_path = tmp_path / "events.jsonl"
        sink = JsonlTelemetrySink(log_path)

        sink.attach(bus, event_types=["pipeline_stage_start", "pipeline_stage_end"])
        await bus.emit("pipeline_stage_start", {"stage": "draft"})
        await bus.emit("ignored_event", {"ignored": True})
        await bus.emit("pipeline_stage_end", {"stage": "draft", "ok": True})

        rows = _read_jsonl(log_path)
        assert [row["event_type"] for row in rows] == [
            "pipeline_stage_start",
            "pipeline_stage_end",
        ]

    async def test_detach_unsubscribes_all_attached_events(
        self, tmp_path: Path
    ) -> None:
        bus = InMemoryEventBus()
        log_path = tmp_path / "events.jsonl"
        sink = JsonlTelemetrySink(log_path)
        sink.attach(bus, event_types=["pipeline_stage_start"])

        sink.detach()
        await bus.emit("pipeline_stage_start", {"stage": "draft"})

        assert not log_path.exists()


class TestJsonlTelemetrySinkAsyncCorrectness:
    async def test_record_does_not_block_event_loop(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """async def record() must not block other coroutines.

        Mock _append_line (sync helper) to time.sleep(0.5); concurrently run
        record() + a 0.5s asyncio.sleep. Total time should be ~0.5s, not ~1.0s,
        proving the file I/O is offloaded to a thread.
        """
        import asyncio
        import time

        log_path = tmp_path / "events.jsonl"
        sink = JsonlTelemetrySink(log_path)

        def slow_append(line: str) -> None:
            time.sleep(0.5)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(line)

        monkeypatch.setattr(sink, "_append_line", slow_append)

        start = time.monotonic()
        await asyncio.gather(
            sink.record("evt", {"x": 1}),
            asyncio.sleep(0.5),
        )
        elapsed = time.monotonic() - start

        assert elapsed < 0.9, (
            f"record() blocked the event loop (elapsed={elapsed:.3f}s)"
        )

    async def test_record_serializes_concurrent_writes_with_lock(
        self, tmp_path: Path
    ) -> None:
        """50 concurrent record() calls must produce 50 valid JSONL lines.

        Without a lock, multiple writers could interleave at the byte level and
        produce broken JSON. With asyncio.Lock + to_thread, each write is atomic.
        """
        import asyncio

        log_path = tmp_path / "events.jsonl"
        sink = JsonlTelemetrySink(log_path)

        await asyncio.gather(*[sink.record("burst", {"i": i}) for i in range(50)])

        text = log_path.read_text(encoding="utf-8")
        lines = text.splitlines()
        assert len(lines) == 50, f"expected 50 lines, got {len(lines)}"
        observed = sorted(json.loads(line)["data"]["i"] for line in lines)
        assert observed == list(range(50))
