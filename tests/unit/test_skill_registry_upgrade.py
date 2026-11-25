"""Tests for SkillRegistry upgrade: SkillStore Protocol, tier filtering, health management."""

from __future__ import annotations

from swarmline.skills.protocols import ScoredSkill, SkillStore
from swarmline.skills.registry import SkillRegistry
from swarmline.skills.tier import SkillHealthStatus, SkillTier
from swarmline.skills.types import LoadedSkill, SkillSpec


def _make_spec(
    skill_id: str = "s1",
    title: str = "Skill 1",
    tier: SkillTier = SkillTier.T2_ROLE,
    health: SkillHealthStatus = SkillHealthStatus.HEALTHY,
    keywords: list[str] | None = None,
) -> SkillSpec:
    return SkillSpec(
        skill_id=skill_id,
        title=title,
        tier=tier,
        health_status=health,
        keywords=keywords or [],
    )


def _make_loaded(
    skill_id: str = "s1",
    title: str = "Skill 1",
    tier: SkillTier = SkillTier.T2_ROLE,
    health: SkillHealthStatus = SkillHealthStatus.HEALTHY,
    keywords: list[str] | None = None,
) -> LoadedSkill:
    return LoadedSkill(
        spec=_make_spec(skill_id, title, tier, health, keywords),
        instruction_md="",
    )


class _FakeRetriever:
    """Fake SkillRetriever for testing delegation."""

    def __init__(self, results: list[ScoredSkill] | None = None) -> None:
        self._results = results or []
        self.last_query: str | None = None
        self.last_candidates: list[SkillSpec] | None = None

    def retrieve(
        self, query: str, candidates: list[SkillSpec], top_k: int = 5
    ) -> list[ScoredSkill]:
        self.last_query = query
        self.last_candidates = candidates
        return self._results[:top_k]


class TestSkillRegistryImplementsSkillStore:
    """SkillRegistry must satisfy SkillStore Protocol."""

    def test_isinstance_check(self) -> None:
        registry = SkillRegistry()
        assert isinstance(registry, SkillStore)


class TestSkillRegistrySearch:
    """search() delegates to retriever or returns all skills."""

    def test_search_without_retriever_returns_all_as_scored(self) -> None:
        s1 = _make_loaded("s1", "Web Search")
        s2 = _make_loaded("s2", "Code Exec")
        registry = SkillRegistry([s1, s2])

        results = registry.search("anything", top_k=10)

        assert len(results) == 2
        assert all(isinstance(r, ScoredSkill) for r in results)
        ids = {r.skill.skill_id for r in results}
        assert ids == {"s1", "s2"}

    def test_search_without_retriever_respects_top_k(self) -> None:
        skills = [_make_loaded(f"s{i}", f"Skill {i}") for i in range(5)]
        registry = SkillRegistry(skills)

        results = registry.search("q", top_k=2)

        assert len(results) == 2

    def test_search_delegates_to_retriever(self) -> None:
        s1 = _make_loaded("s1", "Web Search")
        scored = ScoredSkill(skill=s1.spec, score=0.9, source="bm25")
        retriever = _FakeRetriever([scored])
        registry = SkillRegistry([s1])
        registry.set_retriever(retriever)

        results = registry.search("web", top_k=5)

        assert len(results) == 1
        assert results[0].skill.skill_id == "s1"
        assert results[0].score == 0.9
        assert retriever.last_query == "web"

    def test_search_passes_all_specs_as_candidates(self) -> None:
        s1 = _make_loaded("s1", "A")
        s2 = _make_loaded("s2", "B")
        retriever = _FakeRetriever([])
        registry = SkillRegistry([s1, s2])
        registry.set_retriever(retriever)

        registry.search("query")

        assert retriever.last_candidates is not None
        candidate_ids = {c.skill_id for c in retriever.last_candidates}
        assert candidate_ids == {"s1", "s2"}


class TestSkillRegistryHealth:
    """update_health() and get_health_report() tests."""

    def test_update_health_changes_status(self) -> None:
        s1 = _make_loaded("s1", "Web Search", health=SkillHealthStatus.HEALTHY)
        registry = SkillRegistry([s1])

        registry.update_health("s1", SkillHealthStatus.DEGRADED)

        skill = registry.get("s1")
        assert skill is not None
        assert skill.spec.health_status == SkillHealthStatus.DEGRADED

    def test_update_health_nonexistent_skill_is_noop(self) -> None:
        registry = SkillRegistry()
        registry.update_health("nonexistent", SkillHealthStatus.UNAVAILABLE)

    def test_get_health_report_returns_all_statuses(self) -> None:
        s1 = _make_loaded("s1", "A", health=SkillHealthStatus.HEALTHY)
        s2 = _make_loaded("s2", "B", health=SkillHealthStatus.DEGRADED)
        registry = SkillRegistry([s1, s2])

        report = registry.get_health_report()

        assert report == {
            "s1": SkillHealthStatus.HEALTHY,
            "s2": SkillHealthStatus.DEGRADED,
        }

    def test_get_health_report_reflects_updates(self) -> None:
        s1 = _make_loaded("s1", "A")
        registry = SkillRegistry([s1])

        registry.update_health("s1", SkillHealthStatus.UNAVAILABLE)
        report = registry.get_health_report()

        assert report["s1"] == SkillHealthStatus.UNAVAILABLE

    def test_update_health_to_unavailable_sets_t4_disabled(self) -> None:
        s1 = _make_loaded("s1", "A", tier=SkillTier.T2_ROLE)
        registry = SkillRegistry([s1])

        registry.update_health("s1", SkillHealthStatus.UNAVAILABLE)

        skill = registry.get("s1")
        assert skill is not None
        assert skill.spec.tier == SkillTier.T4_DISABLED


class TestSkillRegistryFilterByTier:
    """filter_by_tier() excludes skills above the specified tier."""

    def test_filter_includes_lower_tiers(self) -> None:
        t1 = _make_loaded("t1", "Always", tier=SkillTier.T1_ALWAYS)
        t2 = _make_loaded("t2", "Role", tier=SkillTier.T2_ROLE)
        t3 = _make_loaded("t3", "Discover", tier=SkillTier.T3_DISCOVERABLE)
        t4 = _make_loaded("t4", "Disabled", tier=SkillTier.T4_DISABLED)
        registry = SkillRegistry([t1, t2, t3, t4])

        result = registry.filter_by_tier(SkillTier.T2_ROLE)

        ids = {s.spec.skill_id for s in result}
        assert ids == {"t1", "t2"}

    def test_filter_t3_includes_discoverable(self) -> None:
        t1 = _make_loaded("t1", "Always", tier=SkillTier.T1_ALWAYS)
        t3 = _make_loaded("t3", "Discover", tier=SkillTier.T3_DISCOVERABLE)
        t4 = _make_loaded("t4", "Disabled", tier=SkillTier.T4_DISABLED)
        registry = SkillRegistry([t1, t3, t4])

        result = registry.filter_by_tier(SkillTier.T3_DISCOVERABLE)

        ids = {s.spec.skill_id for s in result}
        assert ids == {"t1", "t3"}

    def test_filter_excludes_t4_disabled(self) -> None:
        t2 = _make_loaded("t2", "Role", tier=SkillTier.T2_ROLE)
        t4 = _make_loaded("t4", "Disabled", tier=SkillTier.T4_DISABLED)
        registry = SkillRegistry([t2, t4])

        result = registry.filter_by_tier(SkillTier.T3_DISCOVERABLE)

        ids = {s.spec.skill_id for s in result}
        assert "t4" not in ids

    def test_filter_empty_registry(self) -> None:
        registry = SkillRegistry()

        result = registry.filter_by_tier(SkillTier.T3_DISCOVERABLE)

        assert result == []


class TestSkillRegistryBackwardCompat:
    """Existing API must remain unchanged."""

    def test_register_and_get_still_works(self) -> None:
        registry = SkillRegistry()
        skill = _make_loaded("s1", "Test")
        registry.register(skill)

        assert registry.get("s1") is not None
        assert registry.get("s1") == skill

    def test_list_all_still_works(self) -> None:
        s1 = _make_loaded("s1", "A")
        s2 = _make_loaded("s2", "B")
        registry = SkillRegistry([s1, s2])

        result = registry.list_all()

        assert len(result) == 2

    def test_list_ids_still_works(self) -> None:
        s1 = _make_loaded("s1", "A")
        registry = SkillRegistry([s1])

        assert "s1" in registry.list_ids()

    def test_get_mcp_servers_still_works(self) -> None:
        spec = SkillSpec(
            skill_id="s1",
            title="S1",
            mcp_servers=[],
        )
        registry = SkillRegistry([LoadedSkill(spec=spec, instruction_md="")])

        servers = registry.get_mcp_servers_for_skills(["s1"])

        assert isinstance(servers, dict)

    def test_validate_tools_still_works(self) -> None:
        registry = SkillRegistry()

        warnings = registry.validate_tools(set())

        assert isinstance(warnings, list)
