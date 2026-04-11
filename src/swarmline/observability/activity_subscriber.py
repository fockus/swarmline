"""ActivityLogSubscriber — EventBus to ActivityLog bridge.

Subscribes to EventBus topics and auto-creates ActivityEntry records
for graph/pipeline lifecycle events.
"""

from __future__ import annotations

import uuid
from typing import Any, Callable

from swarmline.observability.activity_types import ActivityEntry, ActorType


# ---------------------------------------------------------------------------
# Default topic → ActivityEntry mappers
# ---------------------------------------------------------------------------


def _default_mapper(action: str) -> Callable[[dict[str, Any]], ActivityEntry]:
    """Create a standard mapper for a given action name."""

    def _map(data: dict[str, Any]) -> ActivityEntry:
        return ActivityEntry(
            id=uuid.uuid4().hex[:12],
            actor_type=ActorType.SYSTEM,
            actor_id=data.get("actor_id", "system"),
            action=action,
            entity_type=data.get("entity_type", "unknown"),
            entity_id=data.get("entity_id", "unknown"),
            details={k: v for k, v in data.items() if k not in ("actor_id", "entity_type", "entity_id")},
        )

    return _map


_DEFAULT_TOPIC_MAP: dict[str, Callable[[dict[str, Any]], ActivityEntry]] = {
    "graph.orchestrator.started": _default_mapper("orchestrator.started"),
    "graph.orchestrator.delegated": _default_mapper("task.delegated"),
    "graph.orchestrator.agent_completed": _default_mapper("agent.completed"),
    "graph.orchestrator.escalated": _default_mapper("agent.escalated"),
    "graph.message.direct": _default_mapper("message.sent"),
    "pipeline.started": _default_mapper("pipeline.started"),
    "pipeline.phase.completed": _default_mapper("phase.completed"),
    "pipeline.phase.failed": _default_mapper("phase.failed"),
    "pipeline.budget.warning": _default_mapper("budget.warning"),
}


# ---------------------------------------------------------------------------
# Subscriber
# ---------------------------------------------------------------------------


class ActivityLogSubscriber:
    """Bridge between EventBus and ActivityLog.

    Subscribes to EventBus topics and auto-creates ActivityEntry records.
    Uses either the default topic map or a custom one provided at construction.
    """

    def __init__(
        self,
        activity_log: Any,
        event_bus: Any,
        topic_map: dict[str, Callable[[dict[str, Any]], ActivityEntry]] | None = None,
    ) -> None:
        self._activity_log = activity_log
        self._event_bus = event_bus
        self._topic_map = topic_map if topic_map is not None else _DEFAULT_TOPIC_MAP

    def subscribe_defaults(self) -> None:
        """Subscribe to all topics defined in the topic map."""
        for topic, mapper in self._topic_map.items():
            self._event_bus.subscribe(topic, self._make_handler(mapper))

    def _make_handler(
        self, mapper: Callable[[dict[str, Any]], ActivityEntry],
    ) -> Callable[[dict[str, Any]], Any]:
        """Create an async callback that maps event data to an ActivityEntry and logs it."""

        async def _handler(data: dict[str, Any]) -> None:
            entry = mapper(data)
            await self._activity_log.log(entry)

        return _handler
