"""``DurabilityConfig`` — configuration for the native ``DurableRuntime``
checkpoint-after-step decorator (Stage C1.1, 0 new deps).

``DurabilityMode`` mirrors LangGraph's naming so the three modes read the
same across ecosystems:

- ``"exit"`` (default): persist ONLY the terminal state, at the ``final``
  event.
- ``"async"``: additionally persist a progress checkpoint after each
  finished tool call, in a background task (fire-and-forget; drained by
  ``DurableRuntime.cleanup()``).
- ``"sync"``: same as ``"async"`` but the checkpoint write is awaited before
  the triggering event is yielded (stronger durability, higher latency).

``resume`` (Stage C1.2, default ``True`` -- backward-safe new field) controls
whether ``DurableRuntime.run`` restores state from the last checkpoint on
``thread_id`` before invoking the inner runtime: a ``done`` checkpoint layers
a fresh turn on the restored transcript (continue the conversation); a
``running`` checkpoint replays from the last completed step (crash resume).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

DurabilityMode = Literal["exit", "async", "sync"]


@dataclass(frozen=True)
class DurabilityConfig:
    """Configuration for :class:`swarmline.durable.runtime.DurableRuntime`.

    ``thread_id`` is the checkpoint key (mirrors a ``SessionKey`` string /
    resource thread) and addresses the durable history — an empty value
    cannot address anything, so ``DurableRuntime.__init__`` raises
    ``ValueError`` when it is empty.
    """

    mode: DurabilityMode = "exit"
    thread_id: str = ""
    resource_id: str | None = None
    checkpoint_on_tool: bool = True
    resume: bool = True
