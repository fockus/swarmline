"""Append-only JSONL telemetry sink."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


DEFAULT_REDACT_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "password",
        "secret",
        "token",
    }
)


class JsonlTelemetrySink:
    """Write event telemetry as append-only JSONL records.

    The sink is intentionally small and provider-agnostic: it can be called
    directly via ``record()`` or attached to any Swarmline event bus for a
    selected list of event types.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        redact_keys: Iterable[str] = DEFAULT_REDACT_KEYS,
        schema_version: int = 1,
    ) -> None:
        self._path = Path(path)
        self._redact_keys = frozenset(key.lower() for key in redact_keys)
        self._schema_version = schema_version
        self._subscriptions: list[tuple[Any, str]] = []

    @property
    def path(self) -> Path:
        """JSONL output path."""
        return self._path

    async def record(self, event_type: str, data: dict[str, Any]) -> None:
        """Append a telemetry record for one event."""
        record = {
            "schema_version": self._schema_version,
            "timestamp": datetime.now(tz=UTC).isoformat(),
            "event_type": event_type,
            "data": _make_json_safe(_redact(data, self._redact_keys)),
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
            handle.write("\n")

    def attach(self, event_bus: Any, *, event_types: Iterable[str]) -> None:
        """Subscribe this sink to selected event types on an EventBus."""
        for event_type in event_types:
            event_name = str(event_type)

            async def _callback(data: dict[str, Any], *, _event_name: str = event_name) -> None:
                await self.record(_event_name, data)

            subscription_id = event_bus.subscribe(event_name, _callback)
            self._subscriptions.append((event_bus, subscription_id))

    def detach(self) -> None:
        """Unsubscribe from all event buses this sink was attached to."""
        for event_bus, subscription_id in self._subscriptions:
            event_bus.unsubscribe(subscription_id)
        self._subscriptions.clear()


def _redact(value: Any, redact_keys: frozenset[str]) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text.lower() in redact_keys:
                result[key_text] = "[REDACTED]"
            else:
                result[key_text] = _redact(item, redact_keys)
        return result
    if isinstance(value, list):
        return [_redact(item, redact_keys) for item in value]
    if isinstance(value, tuple):
        return [_redact(item, redact_keys) for item in value]
    return value


def _make_json_safe(value: Any) -> Any:
    try:
        json.dumps(value)
    except TypeError:
        if isinstance(value, dict):
            return {str(key): _make_json_safe(item) for key, item in value.items()}
        if isinstance(value, list):
            return [_make_json_safe(item) for item in value]
        return str(value)
    return value
