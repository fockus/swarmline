"""In-memory procedural memory — learned tool sequences."""

from __future__ import annotations

from dataclasses import replace

from swarmline.memory.procedural_types import Procedure


class InMemoryProceduralMemory:
    """Procedural memory backed by a dict. Word-overlap + success-rate ranking."""

    def __init__(self) -> None:
        self._procedures: dict[str, Procedure] = {}

    async def store(self, procedure: Procedure) -> None:
        self._procedures[procedure.id] = procedure

    async def suggest(self, query: str, *, top_k: int = 3) -> list[Procedure]:
        query_words = set(query.lower().split())
        scored: list[tuple[float, Procedure]] = []
        for proc in self._procedures.values():
            text = f"{proc.trigger} {proc.name} {proc.description} {' '.join(proc.tags)}"
            proc_words = set(text.lower().split())
            overlap = len(query_words & proc_words)
            if overlap > 0:
                # Combine relevance (overlap) with success rate
                score = overlap + proc.success_rate
                scored.append((score, proc))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [proc for _, proc in scored[:top_k]]

    async def record_outcome(self, proc_id: str, *, success: bool) -> None:
        proc = self._procedures.get(proc_id)
        if proc is None:
            return
        if success:
            self._procedures[proc_id] = replace(proc, success_count=proc.success_count + 1)
        else:
            self._procedures[proc_id] = replace(proc, failure_count=proc.failure_count + 1)

    async def get(self, proc_id: str) -> Procedure | None:
        return self._procedures.get(proc_id)

    async def count(self) -> int:
        return len(self._procedures)
