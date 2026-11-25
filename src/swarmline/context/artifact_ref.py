"""Artifact-ref primitive — REQ-ORC-092.

Contract 3 of the swarmline runtime context guarantees: a large tool/agent
output is stored once and replaced in context by a short, restorable
reference instead of being repeated verbatim in every subsequent turn.
Zero product coupling: only str/dict/stdlib — no taskloom types imported.
"""

from __future__ import annotations

import hashlib


class ArtifactStore:
    """In-memory, content-addressed store for large outputs.

    Equal content always dedupes to the same ``ref_id`` (deterministic
    from content, not random), so repeated identical outputs across turns
    do not grow the store.
    """

    def __init__(self) -> None:
        self._items: dict[str, str] = {}

    def store(self, output: str) -> str:
        """Store *output* and return a short opaque, content-derived ref id."""
        ref_id = hashlib.sha256(output.encode()).hexdigest()
        self._items[ref_id] = output
        return ref_id

    def restore(self, ref_id: str) -> str:
        """Return the output stored under *ref_id*.

        Raises:
            KeyError: if *ref_id* is not present in the store.
        """
        return self._items[ref_id]


def to_artifact_ref(store: ArtifactStore, output: str) -> dict[str, object]:
    """Store *output* in *store* and return a short restorable reference.

    The returned dict is small and embeddable into context in place of the
    full output — the orchestrator holds the reference, never the full
    transcript (REQ-ORC-070/092).

    Args:
        store: The artifact store to persist *output* into.
        output: The large output to replace with a reference.

    Returns:
        ``{"artifact_ref": <ref_id>, "length": <len(output)>}``
    """
    ref_id = store.store(output)
    return {"artifact_ref": ref_id, "length": len(output)}
