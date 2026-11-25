"""In-memory EvidenceCollector — implements EvidenceSurfacePort."""

from __future__ import annotations

from swarmline.hitl.timeline_types import EvidenceSurface


class InMemoryEvidenceCollector:
    """In-memory storage for collected evidence surfaces."""

    def __init__(self) -> None:
        self._evidence: dict[str, EvidenceSurface] = {}

    def collect_evidence(
        self,
        run_id: str,
        *,
        test_results: tuple[str, ...] = (),
        logs: tuple[str, ...] = (),
        artifacts: tuple[str, ...] = (),
        changed_files: tuple[str, ...] = (),
        plan_state: str | None = None,
    ) -> EvidenceSurface:
        """Collect evidence for a run, storing and returning the surface."""
        ev = EvidenceSurface(
            run_id=run_id,
            test_results=test_results,
            logs=logs,
            artifacts=artifacts,
            changed_files=changed_files,
            plan_state=plan_state,
        )
        self._evidence[run_id] = ev
        return ev

    def get_evidence(self, run_id: str) -> EvidenceSurface | None:
        """Return stored evidence or None if not found."""
        return self._evidence.get(run_id)
