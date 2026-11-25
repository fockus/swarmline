"""Proactive skill injection — discovers and injects relevant tools at turn 0."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from swarmline.domain_types import ToolSpec
from swarmline.skills.protocols import SkillRetriever
from swarmline.skills.registry import SkillRegistry
from swarmline.skills.tier import SkillTier, filter_by_tier

if TYPE_CHECKING:
    from swarmline.skills.capability import CapabilityDoc
    from swarmline.skills.capability_ranker import CapabilityRanker
    from swarmline.skills.types import SkillSpec


def _skill_spec_to_capability_doc(spec: SkillSpec) -> CapabilityDoc:
    """Default SkillSpec → CapabilityDoc conversion for the ranker path.

    Uses skill_id directly as capability_id (no prefix) so that the
    registry's get_tool_allowlist(matched_ids) lookup continues to work
    without remapping.
    """
    from swarmline.skills.capability import CapabilityDoc, CapabilityKind, RiskLevel

    return CapabilityDoc(
        capability_id=spec.skill_id,
        kind=CapabilityKind.SKILL,
        source="registry",
        name=spec.title or spec.skill_id,
        description=spec.description or spec.skill_id,
        input_schema=None,
        examples=[],
        tags=list(spec.keywords) + list(spec.intents),
        required_capabilities=[],
        runtime_allow=["thin", "claude_sdk", "deepagents"],
        allowed_tools=list(spec.tool_include) + list(spec.local_tools),
        risk_level=RiskLevel.LOW,
        cost_hint="cheap",
        latency_hint="fast",
        content_md=spec.description or "",
        enabled=spec.tier < SkillTier.T4_DISABLED,
    )


class ProactiveSkillInjector:
    """Discovers relevant skills for a task and injects their tools.

    Default behaviour (REQ-OSS-050 — byte-identical when ranker is off):
    1. Filters candidates (excludes T4_DISABLED)
    2. Retrieves top-k relevant skills via SkillRetriever
    3. Resolves matched skills → ToolSpecs via registry
    4. Merges with existing tools (dedup by name)

    Opt-in weighted ranker (pass ``ranker=CapabilityRanker(...)``):
    Steps 2–3 are replaced by multi-factor scoring via CapabilityRanker.
    Steps 1 and 4 are unchanged.
    """

    def __init__(
        self,
        retriever: SkillRetriever,
        registry: SkillRegistry,
        top_k: int = 8,
        min_score: float = 0.6,
        ranker: CapabilityRanker | None = None,
        skill_to_doc: Callable[[SkillSpec], CapabilityDoc] | None = None,
    ) -> None:
        self._retriever = retriever
        self._registry = registry
        self._top_k = top_k
        self._min_score = min_score
        self._ranker = ranker
        self._skill_to_doc = skill_to_doc
        self._last_report: dict[str, Any] = {"matched_skills": []}

    def inject(
        self, task_context: str, current_tools: list[ToolSpec]
    ) -> list[ToolSpec]:
        """Discover relevant skills and return merged tool list."""
        if not task_context.strip():
            return list(current_tools)

        # 1. Get candidates, exclude T4_DISABLED
        all_skills = [s.spec for s in self._registry.list_all()]
        candidates = filter_by_tier(all_skills, SkillTier.T3_DISCOVERABLE)

        if not candidates:
            return list(current_tools)

        # 2. Retrieve relevant skills
        scored = self._retriever.retrieve(task_context, candidates, top_k=self._top_k)

        if self._ranker is None:
            # DEFAULT PATH — byte-identical to pre-OSS-T7 behaviour (REQ-OSS-050)
            # 3. Filter by min_score
            matched = [s for s in scored if s.score >= self._min_score]

            # 4. Build report
            self._last_report = {
                "matched_skills": [
                    {
                        "skill_id": s.skill.skill_id,
                        "score": s.score,
                        "source": s.source,
                    }
                    for s in matched
                ],
            }

            if not matched:
                return list(current_tools)

            # 5. Resolve to ToolSpecs via registry allowlist + descriptions
            matched_ids = [s.skill.skill_id for s in matched]

        else:
            # WEIGHTED RANKER PATH (opt-in, REQ-OSS-050 keeps default off)
            to_doc = self._skill_to_doc or _skill_spec_to_capability_doc
            docs = {s.skill.skill_id: to_doc(s.skill) for s in scored}
            sem_scores = {s.skill.skill_id: s.score for s in scored}

            ranked = self._ranker.rank(
                list(docs.values()),
                semantic_scores=sem_scores,
            )
            matched_ranked = [r for r in ranked if r.score >= self._min_score]

            self._last_report = {
                "matched_skills": [
                    {
                        "skill_id": r.capability.capability_id,
                        "score": r.score,
                        "source": "ranker",
                    }
                    for r in matched_ranked
                ],
            }

            if not matched_ranked:
                return list(current_tools)

            matched_ids = [r.capability.capability_id for r in matched_ranked]

        # 6. Resolve to ToolSpecs via registry allowlist + descriptions
        new_tool_names = self._registry.get_tool_allowlist(matched_ids)
        tool_descriptions = self._registry.get_tool_descriptions(matched_ids)

        # 7. Merge with dedup
        existing_names = {t.name for t in current_tools}
        merged = list(current_tools)
        for name in sorted(new_tool_names):
            if name not in existing_names:
                desc = tool_descriptions.get(name, "")
                merged.append(ToolSpec(name=name, description=desc, parameters={}))
                existing_names.add(name)

        return merged

    def get_injection_report(self) -> dict[str, Any]:
        """Return stats from the last inject() call (defensive copy)."""
        return dict(self._last_report)


class SkillInjectionHook:
    """Hook that fires ProactiveSkillInjector on the first LLM turn."""

    def __init__(self, injector: ProactiveSkillInjector) -> None:
        self.injector = injector

    def should_fire(self, turn_number: int) -> bool:
        """Only fire on turn 0 (first LLM call)."""
        return turn_number == 0
