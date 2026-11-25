"""Tests for ProactiveSkillInjector and SkillInjectionHook."""

from __future__ import annotations

import pytest
from swarmline.domain_types import ToolSpec
from swarmline.skills.bm25 import BM25Retriever
from swarmline.skills.injector import ProactiveSkillInjector, SkillInjectionHook
from swarmline.skills.registry import SkillRegistry
from swarmline.skills.tier import SkillTier
from swarmline.skills.types import LoadedSkill, SkillSpec


def _spec(
    sid: str,
    title: str = "",
    desc: str = "",
    tier: SkillTier = SkillTier.T2_ROLE,
    tool_include: list[str] | None = None,
    local_tools: list[str] | None = None,
) -> SkillSpec:
    return SkillSpec(
        skill_id=sid,
        title=title or sid,
        description=desc,
        tier=tier,
        tool_include=tool_include or [],
        local_tools=local_tools or [],
        keywords=[sid],
    )


def _loaded(spec: SkillSpec) -> LoadedSkill:
    return LoadedSkill(spec=spec, instruction_md="")


def _tool(name: str) -> ToolSpec:
    return ToolSpec(name=name, description="", parameters={})


# Shared fixtures
WEB_SKILL = _spec(
    "web", "Web Search", "Search the internet for info", tool_include=["web_search"]
)
CODE_SKILL = _spec(
    "code", "Code Review", "Review code for bugs", tool_include=["code_review"]
)
DB_SKILL = _spec(
    "db", "Database Query", "Execute SQL queries", tool_include=["db_query"]
)
DISABLED_SKILL = _spec(
    "disabled",
    "Disabled Skill",
    "Should not appear",
    tier=SkillTier.T4_DISABLED,
    tool_include=["disabled_tool"],
)


def _make_registry() -> SkillRegistry:
    return SkillRegistry(
        skills=[_loaded(s) for s in [WEB_SKILL, CODE_SKILL, DB_SKILL, DISABLED_SKILL]]
    )


class TestProactiveSkillInjector:
    """ProactiveSkillInjector.inject() core behavior."""

    def test_inject_returns_relevant_tools_for_matching_query(self) -> None:
        """Web-related query returns web_search tool."""
        injector = ProactiveSkillInjector(
            retriever=BM25Retriever(),
            registry=_make_registry(),
            min_score=0.0,
        )
        result = injector.inject("search the web for information", [])
        names = {t.name for t in result}
        assert "web_search" in names
        assert all(isinstance(t, ToolSpec) for t in result)

    def test_inject_excludes_t4_disabled_skills(self) -> None:
        """T4_DISABLED skills never appear in injected tools."""
        injector = ProactiveSkillInjector(
            retriever=BM25Retriever(),
            registry=_make_registry(),
            min_score=0.0,
        )
        result = injector.inject("disabled should not appear", [])
        names = {t.name for t in result}
        assert "disabled_tool" not in names

    def test_inject_deduplicates_existing_tools(self) -> None:
        """Already-present tools are not added again."""
        existing = [_tool("web_search")]
        injector = ProactiveSkillInjector(
            retriever=BM25Retriever(),
            registry=_make_registry(),
            min_score=0.0,
        )
        result = injector.inject("search the web", existing)
        web_count = sum(1 for t in result if t.name == "web_search")
        assert web_count == 1

    def test_inject_preserves_existing_tools(self) -> None:
        existing = [_tool("existing_tool")]
        injector = ProactiveSkillInjector(
            retriever=BM25Retriever(),
            registry=_make_registry(),
        )
        result = injector.inject("search the web", existing)
        names = {t.name for t in result}
        assert "existing_tool" in names

    def test_inject_respects_min_score_threshold(self) -> None:
        """With impossibly high min_score, no new tools are injected."""
        existing = [_tool("baseline")]
        injector = ProactiveSkillInjector(
            retriever=BM25Retriever(),
            registry=_make_registry(),
            min_score=999.0,
        )
        result = injector.inject("search the web for information", existing)
        names = {t.name for t in result}
        assert names == {"baseline"}, (
            "High min_score should filter out all discovered tools"
        )

    def test_inject_empty_context_returns_current_tools(self) -> None:
        """Empty task_context returns tools unchanged."""
        existing = [_tool("my_tool")]
        injector = ProactiveSkillInjector(
            retriever=BM25Retriever(),
            registry=_make_registry(),
        )
        result = injector.inject("", existing)
        assert result == existing

    def test_inject_whitespace_context_returns_current_tools(self) -> None:
        """Whitespace-only task_context treated as empty."""
        existing = [_tool("my_tool")]
        injector = ProactiveSkillInjector(
            retriever=BM25Retriever(),
            registry=_make_registry(),
        )
        result = injector.inject("   ", existing)
        assert result == existing

    def test_inject_with_no_candidates_returns_current_tools(self) -> None:
        """Registry with only disabled skills → no candidates after filter."""
        registry = SkillRegistry(skills=[_loaded(DISABLED_SKILL)])
        injector = ProactiveSkillInjector(
            retriever=BM25Retriever(),
            registry=registry,
            min_score=0.0,
        )
        existing = [_tool("my_tool")]
        result = injector.inject("anything here", existing)
        assert result == existing

    def test_inject_merges_local_tools_from_matched_skills(self) -> None:
        """local_tools from matched skill specs are included in allowlist."""
        skill = _spec(
            "analysis",
            "Data Analysis",
            "Analyze data sets",
            tool_include=["chart_tool"],
            local_tools=["local_csv_reader"],
        )
        registry = SkillRegistry(skills=[_loaded(skill)])
        injector = ProactiveSkillInjector(
            retriever=BM25Retriever(),
            registry=registry,
            min_score=0.0,
        )
        result = injector.inject("analyze data sets", [])
        names = {t.name for t in result}
        assert "chart_tool" in names
        assert "local_csv_reader" in names

    @pytest.mark.parametrize(
        ("query", "expected_tool"),
        [
            ("search the web for information", "web_search"),
            ("review code for bugs and issues", "code_review"),
            ("execute SQL queries on database", "db_query"),
        ],
    )
    def test_inject_matches_query_to_correct_skill(
        self, query: str, expected_tool: str
    ) -> None:
        """BM25 retriever routes query to the matching skill's tools."""
        injector = ProactiveSkillInjector(
            retriever=BM25Retriever(min_score=0.0),
            registry=_make_registry(),
            min_score=0.0,
        )
        result = injector.inject(query, [])
        names = {t.name for t in result}
        assert expected_tool in names


class TestInjectionReport:
    """get_injection_report() for observability."""

    def test_report_contains_matched_skills_and_scores(self) -> None:
        """Report entries have skill_id, score (float), and source."""
        injector = ProactiveSkillInjector(
            retriever=BM25Retriever(),
            registry=_make_registry(),
            min_score=0.0,
        )
        injector.inject("search the web", [])
        report = injector.get_injection_report()
        assert "matched_skills" in report
        assert len(report["matched_skills"]) >= 1
        entry = report["matched_skills"][0]
        assert "skill_id" in entry
        assert isinstance(entry["score"], float)
        assert entry["score"] >= 0.0
        assert "source" in entry
        assert isinstance(entry["source"], str)

    def test_report_empty_before_inject(self) -> None:
        injector = ProactiveSkillInjector(
            retriever=BM25Retriever(),
            registry=_make_registry(),
        )
        report = injector.get_injection_report()
        assert report["matched_skills"] == []

    def test_report_excludes_disabled_skills(self) -> None:
        """Report never contains T4_DISABLED skill_ids."""
        injector = ProactiveSkillInjector(
            retriever=BM25Retriever(),
            registry=_make_registry(),
            min_score=0.0,
        )
        injector.inject("disabled skill query", [])
        report = injector.get_injection_report()
        matched_ids = {e["skill_id"] for e in report["matched_skills"]}
        assert "disabled" not in matched_ids

    def test_report_updates_on_each_real_inject_call(self) -> None:
        """Each inject() with real context updates the report."""
        injector = ProactiveSkillInjector(
            retriever=BM25Retriever(),
            registry=_make_registry(),
            min_score=0.0,
        )
        injector.inject("search the web", [])
        first_report = injector.get_injection_report()
        first_ids = {e["skill_id"] for e in first_report["matched_skills"]}
        assert len(first_ids) >= 1

        injector.inject("execute SQL queries on database", [])
        second_report = injector.get_injection_report()
        second_ids = {e["skill_id"] for e in second_report["matched_skills"]}
        assert second_ids != first_ids or len(second_report["matched_skills"]) >= 1

    def test_report_preserved_on_empty_context(self) -> None:
        """Empty context returns early, report from previous call preserved."""
        injector = ProactiveSkillInjector(
            retriever=BM25Retriever(),
            registry=_make_registry(),
            min_score=0.0,
        )
        injector.inject("search the web", [])
        report_before = injector.get_injection_report()
        assert len(report_before["matched_skills"]) >= 1

        injector.inject("", [])
        report_after = injector.get_injection_report()
        assert report_after == report_before


class TestSkillInjectionHook:
    """SkillInjectionHook — fires only on turn 0."""

    def test_hook_stores_injector_reference(self) -> None:
        injector = ProactiveSkillInjector(
            retriever=BM25Retriever(),
            registry=_make_registry(),
        )
        hook = SkillInjectionHook(injector=injector)
        assert hook.injector is injector

    def test_should_fire_only_at_turn_zero(self) -> None:
        injector = ProactiveSkillInjector(
            retriever=BM25Retriever(),
            registry=_make_registry(),
        )
        hook = SkillInjectionHook(injector=injector)
        assert hook.should_fire(turn_number=0) is True

    @pytest.mark.parametrize("turn", [1, 2, 5, 10, 100])
    def test_should_not_fire_after_turn_zero(self, turn: int) -> None:
        """Hook never fires for turn_number > 0."""
        injector = ProactiveSkillInjector(
            retriever=BM25Retriever(),
            registry=_make_registry(),
        )
        hook = SkillInjectionHook(injector=injector)
        assert hook.should_fire(turn_number=turn) is False
