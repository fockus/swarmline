"""JournalSubscriber -- EventBus to EventJournal bridge (REQ-008).

Mirrors the attach/detach pattern already established by ``OTelExporter``
(otel_exporter.py) and ``ActivityLogSubscriber`` (activity_subscriber.py):
subscribe to a fixed set of bus topics, map every observed event straight
into the configured ``EventJournal``, unsubscribe cleanly on ``detach()``.

Scope v1: local, in-process bus only (``InMemoryEventBus`` /
``NamespacedEventBus``). A distributed bus (redis/nats) is only ever
observed from the process running this subscriber -- events published by
other processes on the same distributed topic are invisible to it.

Default topics cover the graph-orchestrator and pipeline lifecycle events
actually emitted today (see ``multi_agent/graph_orchestrator.py``,
``multi_agent/graph_communication*.py``, ``pipeline/pipeline.py``,
``pipeline/budget.py``, ``pipeline/budget_store.py``) -- producers are not
modified by this module.

Out of scope for ``DEFAULT_TOPICS`` (verified present, but outside the
graph./pipeline. namespaces REQ-008 asks for -- pass an explicit ``topics``
list to ``attach()`` if you need these too):

- ``workspace.created`` / ``workspace.cleaned`` (multi_agent/workspace.py)
- ``persistent.goal.submitted`` / ``.completed`` / ``.failed`` (multi_agent/persistent_graph.py)
- ``worktree:*`` / ``<namespace>:budget_exceeded`` / ``global:budget_warning``
  (colon-namespaced, dynamic per-goal/per-partition topics --
  multi_agent/worktree_orchestrator.py, pipeline/partitioned_budget.py --
  cannot be enumerated statically since the namespace segment is a runtime value)
- ``pipeline_stage_start`` / ``pipeline_stage_end`` / ``parallel_stage_start`` /
  ``parallel_stage_join`` / ``branch_*`` / ``loop_iteration_*`` (legacy
  underscore-style names, not the ``pipeline.`` dot namespace --
  pipeline/typed.py's ``_LEGACY_EVENT_NAMES`` adapter)
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Callable

import structlog

from swarmline.observability.journal import EventJournal

_logger = structlog.get_logger(component="journal_subscriber")

# Real topics emitted today by graph orchestration + pipeline producers, enumerated
# by grepping every `.emit("graph.*"/"pipeline.*", ...)` call site under
# multi_agent/ and pipeline/ (no central topic-name constant/enum exists to import
# from instead -- every producer inlines its own literal).
#
# ponytail: this list is BRITTLE BY CONSTRUCTION -- InMemoryEventBus/NamespacedEventBus
# only match exact topic strings (no "graph.orchestrator.*" glob support for
# dot-separated names), so a new producer topic silently never reaches the journal
# via attach()'s default until it is added here too. A wildcard-capable bus (or a
# central topic registry the producers themselves populate) would remove this
# maintenance burden entirely -- follow-up, not in scope for this module.
DEFAULT_TOPICS: tuple[str, ...] = (
    # multi_agent/graph_orchestrator.py -- orchestrator + per-agent lifecycle
    "graph.orchestrator.started",  # graph_orchestrator.py:129
    "graph.orchestrator.denied",  # graph_orchestrator.py:164
    "graph.orchestrator.delegated",  # graph_orchestrator.py:185
    "graph.orchestrator.stopped",  # graph_orchestrator.py:259
    "graph.orchestrator.agent_completed",  # graph_orchestrator.py:343
    "graph.orchestrator.escalated",  # graph_orchestrator.py:374
    "graph.agent.self_terminated",  # graph_orchestrator.py:416
    "graph.agent.awaiting_review",  # graph_orchestrator.py:419
    "graph.agent.ready",  # graph_orchestrator.py:430
    # multi_agent/graph_communication.py + _sqlite/_redis/_nats/_postgres backends
    # (same 3 topics emitted by every backend implementation)
    "graph.message.direct",  # graph_communication.py:25 (+4 backend variants)
    "graph.message.broadcast",  # graph_communication.py:43 (+4 backend variants)
    "graph.message.escalation",  # graph_communication.py:60 (+4 backend variants)
    # pipeline/pipeline.py -- pipeline + phase lifecycle
    "pipeline.started",  # pipeline.py:65
    "pipeline.completed",  # pipeline.py:110
    "pipeline.stopped",  # pipeline.py:145
    "pipeline.phase.started",  # pipeline.py:175
    "pipeline.phase.failed",  # pipeline.py:190,205,232,247,262,277,300
    "pipeline.phase.completed",  # pipeline.py:315
    # pipeline/budget.py + pipeline/budget_store.py -- budget threshold events
    "pipeline.budget.warning",  # budget.py:170
    "pipeline.budget.threshold_exceeded",  # budget_store.py:174,501
)


class JournalSubscriber:
    """Bridge between an EventBus and an EventJournal.

    Subscribes to the given (or default) topics on ``attach()`` and appends
    every observed event as ``(topic, data)`` into the journal. ``detach()``
    unsubscribes from every topic registered by the matching ``attach()``.
    """

    def __init__(self, journal: EventJournal) -> None:
        self._journal = journal
        self._bus: Any | None = None
        self._sub_ids: list[str] = []

    def attach(self, bus: Any, topics: Iterable[str] | None = None) -> None:
        """Subscribe to ``topics`` (default: ``DEFAULT_TOPICS``) on ``bus``."""
        self._bus = bus
        for topic in topics if topics is not None else DEFAULT_TOPICS:
            self._sub_ids.append(bus.subscribe(topic, self._make_handler(topic)))

    def detach(self) -> None:
        """Unsubscribe from every topic registered via ``attach()``. Idempotent."""
        if self._bus is None:
            return
        for sub_id in self._sub_ids:
            self._bus.unsubscribe(sub_id)
        self._sub_ids.clear()
        self._bus = None

    def _make_handler(self, topic: str) -> Callable[[dict[str, Any]], Any]:
        """Create an async callback that appends the event into the journal.

        REQ-015: the bus swallows callback exceptions silently (fire-and-
        forget, event_bus.py), so the try/except + structured log MUST live
        here, inside the callback itself -- relying on the bus would drop
        the failure with no signal at all.
        """

        async def _handler(data: dict[str, Any]) -> None:
            try:
                await self._journal.append(topic, data)
            except Exception as exc:  # noqa: BLE001 -- must never break the bus dispatch
                _logger.warning(
                    "journal_subscriber.append_failed",
                    topic=topic,
                    error=str(exc),
                )

        return _handler
