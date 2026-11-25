"""``LlmFactExtractor`` + ``ObservationLog`` — observational memory
(Stage C2.3, opt-in, Mastra parity).

``LlmFactExtractor`` implements the existing ``consolidation.FactExtractor``
Protocol via an optional LLM seam (mirrors ``LlmSummaryGenerator``'s
``llm_call`` style): with no ``llm_call`` it delegates entirely to
``KeywordFactExtractor`` (the ``ConsolidationPipeline`` default stays
unchanged -- this class is only used when explicitly injected). LLM
failures never raise: any ``llm_call`` error, too-short output, or
unparseable output falls back to the configured ``fallback`` extractor
instead. A broken ``fallback`` extractor's own errors DO propagate --
that is a configuration error on the caller's part, not a runtime
condition this class is responsible for hiding.

``ObservationLog`` is a thread/resource-scoped observation log over an
existing ``FactStore`` (same reserved-``key_prefix`` pattern as
``WorkingMemory``, Stage C2.1). ``FactStore`` (``swarmline.protocols.memory``)
exposes only ``upsert_fact``/``get_facts`` -- there is no delete-by-key
method, and provider code is out of scope for this stage. ``aclear`` is
therefore an honest **tombstone-watermark** design, not a physical delete:
it records the current write-index as a "cleared before" watermark; ``aget``
only ever returns entries at or after that watermark. Nothing is ever
removed from the underlying store -- indices keep growing monotonically
(computed from the max index ever written, visible or not), so a later
``arecord`` after ``aclear`` can never collide with an old, now-hidden key.

Concurrency: ``arecord``/``aclear`` each do a read-modify-write of the next
index (read via ``get_facts``, then ``upsert_fact``); a per-instance
``asyncio.Lock`` serializes this critical section so concurrent ``arecord``
calls on the SAME ``ObservationLog`` instance never race and silently
overwrite each other. This lock only protects one Python process's one
instance -- ``FactStore`` has no CAS/transaction primitive, so concurrent
writers across separate instances/processes sharing the same ``scope_id``
are NOT supported (the same class of limitation as any ``FactStore``-backed
structure); single-writer-per-scope is the documented assumption.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from swarmline.memory.consolidation import FactExtractor, KeywordFactExtractor
from swarmline.memory.episodic_types import Episode

if TYPE_CHECKING:
    # Deferred for the same reason as memory/working.py: `swarmline.protocols`
    # package init pulls in `protocols.memory`, which imports from
    # `swarmline.memory.types` -- an eager import from `swarmline.protocols`
    # here (this module is eagerly re-exported via `swarmline.memory.__init__`)
    # risks a circular import. `FactStore` is only ever used as a type hint.
    from swarmline.protocols.memory import FactStore

logger = logging.getLogger(__name__)

_OBSERVE_PROMPT = """\
Извлеки краткие наблюдения (повторяющиеся факты, паттерны, решения) из
приведённых кратких описаний эпизодов.

Формат: каждое наблюдение на отдельной строке, начиная с "- ".
"""

_MIN_OUTPUT_LEN = 5  # mirrors LlmSummaryGenerator's short-output guard, scaled
# down for a bullet-list of facts rather than a full prose summary.

# Common bullet/numbered-list markers: "-", "*", "•", "1.", "1)" -- marker +
# any whitespace, then the observation text. "1.2 release notes" is NOT a
# marker: a dot followed by another digit is a decimal/version token (r2).
_BULLET_RE = re.compile(r"^(?:[-*•]|\d+\.(?!\d)|\d+\))\s*(.+)$")


def _parse_observations(text: str) -> list[str]:
    """Best-effort parse: prefer bullet/numbered-list lines (see
    ``_BULLET_RE``); if none, treat every non-empty line as one observation
    (prose fallback); ``[]`` if nothing parseable at all (caller falls back
    to the ``FactExtractor`` fallback)."""
    lines = [line.strip() for line in text.splitlines()]
    bullets = [m.group(1).strip() for ln in lines if (m := _BULLET_RE.match(ln))]
    if bullets:
        return bullets
    return [ln for ln in lines if ln]


class LlmFactExtractor:
    """``consolidation.FactExtractor`` implementation with an optional LLM seam.

    ISP: 1 method (``extract``), matching the ``FactExtractor`` Protocol.
    """

    def __init__(
        self,
        llm_call: Callable[..., Any] | None = None,
        *,
        fallback: FactExtractor | None = None,
    ) -> None:
        self._llm_call = llm_call
        self._fallback = fallback or KeywordFactExtractor()

    async def extract(self, episodes: list[Episode]) -> list[str]:
        if not episodes:
            return []
        if not self._llm_call:
            return await self._fallback.extract(episodes)

        summaries = "\n".join(f"- {ep.summary}" for ep in episodes)
        try:
            result = await self._llm_call(_OBSERVE_PROMPT, summaries)
        except Exception:
            logger.warning(
                "LLM fact extraction failed, falling back to %s",
                type(self._fallback).__name__,
                exc_info=True,
            )
            return await self._fallback.extract(episodes)

        text = str(result or "").strip()
        if len(text) < _MIN_OUTPUT_LEN:
            logger.warning(
                "LLM fact extraction output too short (%d chars), falling back",
                len(text),
            )
            return await self._fallback.extract(episodes)

        facts = _parse_observations(text)
        if not facts:
            return await self._fallback.extract(episodes)
        return facts


class ObservationLog:
    """Scope-isolated observation log over a ``FactStore``.

    ISP: 3 methods (``arecord``/``aget``/``aclear``).
    """

    def __init__(
        self, fact_store: FactStore, *, scope_id: str, key_prefix: str = "obs"
    ) -> None:
        self._fact_store = fact_store
        self._scope_id = scope_id
        self._prefix = f"{key_prefix}."
        self._cleared_key = f"{key_prefix}.__cleared__"
        # Serializes the read-next-index -> upsert critical section within
        # THIS instance (see module docstring "Concurrency" paragraph).
        self._lock = asyncio.Lock()

    async def _load(self) -> tuple[dict[int, str], int]:
        """All ever-written {index: observation} pairs (including entries
        hidden by a prior ``aclear``) + the current cleared-watermark."""
        facts = await self._fact_store.get_facts(self._scope_id, topic_id=None)
        entries: dict[int, str] = {}
        for key, value in facts.items():
            if not key.startswith(self._prefix) or key == self._cleared_key:
                continue
            suffix = key[len(self._prefix) :]
            if suffix.isdigit():
                entries[int(suffix)] = value
        cleared = facts.get(self._cleared_key, 0)
        return entries, cleared

    async def arecord(self, observation: str) -> None:
        """Append ``observation`` under the next monotonic index.

        Locked (per-instance) -- see module docstring "Concurrency"."""
        async with self._lock:
            entries, _ = await self._load()
            next_idx = max(entries) + 1 if entries else 0
            await self._fact_store.upsert_fact(
                self._scope_id,
                f"{self._prefix}{next_idx}",
                observation,
                topic_id=None,
                source="observation_log",
            )

    async def aget(self, *, limit: int = 20) -> list[str]:
        """Up to the ``limit`` most recent visible observations, oldest-first."""
        if limit <= 0:
            return []
        entries, cleared = await self._load()
        visible = sorted(idx for idx in entries if idx >= cleared)
        return [entries[idx] for idx in visible[-limit:]]

    async def aclear(self) -> None:
        """Hide every observation recorded so far (tombstone-watermark --
        see module docstring; ``FactStore`` has no delete-by-key). Locked
        (per-instance) -- same critical section shape as ``arecord``."""
        async with self._lock:
            entries, _ = await self._load()
            next_idx = max(entries) + 1 if entries else 0
            await self._fact_store.upsert_fact(
                self._scope_id,
                self._cleared_key,
                next_idx,
                topic_id=None,
                source="observation_log",
            )
