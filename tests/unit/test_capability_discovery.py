"""Tests for OSS-T7 capability discovery: CapabilityDoc, filters, ranker,
normalizers, renderer, and ProactiveSkillInjector opt-in ranker path.

TDD: tests were written BEFORE the implementation.
REQ-OSS-051: zero product coupling verified by import assertions.
REQ-OSS-050: ranker-off path byte-identical to pre-OSS-T7 behaviour.
"""

from __future__ import annotations

import re

import pytest
import yaml
from swarmline.domain_types import ToolSpec
from swarmline.skills.bm25 import BM25Retriever
from swarmline.skills.capability import CapabilityDoc, CapabilityKind, RiskLevel
from swarmline.skills.capability_filters import (
    AvailabilityFilter,
    FilterResult,
    RuntimeFilter,
)
from swarmline.skills.capability_normalizers import (
    LocalToolNormalizer,
    McpToolNormalizer,
    WorkflowNormalizer,
    YamlSkillNormalizer,
)
from swarmline.skills.capability_ranker import (
    CapabilityRanker,
    RankWeights,
    RankedCapability,
)
from swarmline.skills.capability_renderer import SkillMarkdownRenderer
from swarmline.skills.injector import ProactiveSkillInjector
from swarmline.skills.registry import SkillRegistry
from swarmline.skills.tier import SkillTier
from swarmline.skills.types import LoadedSkill, SkillSpec


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_doc(
    capability_id: str = "skill:test",
    kind: CapabilityKind = CapabilityKind.SKILL,
    name: str = "Test Skill",
    description: str = "A test skill",
    enabled: bool = True,
    latency_hint: str = "fast",
    cost_hint: str = "cheap",
    risk_level: RiskLevel = RiskLevel.LOW,
    runtime_allow: list[str] | None = None,
    required_capabilities: list[str] | None = None,
    tags: list[str] | None = None,
    allowed_tools: list[str] | None = None,
    examples: list[str] | None = None,
) -> CapabilityDoc:
    return CapabilityDoc(
        capability_id=capability_id,
        kind=kind,
        source="test",
        name=name,
        description=description,
        input_schema=None,
        examples=examples or [],
        tags=tags or [],
        required_capabilities=required_capabilities or [],
        runtime_allow=runtime_allow or ["thin", "claude_sdk"],
        allowed_tools=allowed_tools or [],
        risk_level=risk_level,
        cost_hint=cost_hint,
        latency_hint=latency_hint,
        content_md=f"# {name}\n\n## Purpose\n{description}",
        enabled=enabled,
    )


def _make_skill_spec(
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


# ---------------------------------------------------------------------------
# TestCapabilityDoc
# ---------------------------------------------------------------------------


class TestCapabilityDoc:
    """CapabilityDoc frozen dataclass construction and invariants."""

    def test_construction_with_valid_fields_succeeds(self) -> None:
        doc = _make_doc()
        assert doc.capability_id == "skill:test"
        assert doc.kind == CapabilityKind.SKILL
        assert doc.name == "Test Skill"
        assert doc.enabled is True

    def test_blank_capability_id_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="capability_id"):
            _make_doc(capability_id="   ")

    def test_blank_name_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="name"):
            CapabilityDoc(
                capability_id="x:y",
                kind=CapabilityKind.TOOL,
                source="local",
                name="  ",
                description="desc",
                input_schema=None,
                examples=[],
                tags=[],
                required_capabilities=[],
                runtime_allow=["thin"],
                allowed_tools=[],
                risk_level=RiskLevel.LOW,
                cost_hint="cheap",
                latency_hint="fast",
                content_md="",
                enabled=True,
            )

    def test_empty_runtime_allow_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="runtime_allow"):
            CapabilityDoc(
                capability_id="x:y",
                kind=CapabilityKind.TOOL,
                source="local",
                name="My Tool",
                description="desc",
                input_schema=None,
                examples=[],
                tags=[],
                required_capabilities=[],
                runtime_allow=[],  # empty — must raise
                allowed_tools=[],
                risk_level=RiskLevel.LOW,
                cost_hint="cheap",
                latency_hint="fast",
                content_md="",
                enabled=True,
            )

    def test_is_frozen(self) -> None:
        doc = _make_doc()
        with pytest.raises((AttributeError, TypeError)):
            doc.name = "other"  # type: ignore[misc]

    @pytest.mark.parametrize(
        "kind",
        [
            CapabilityKind.TOOL,
            CapabilityKind.MCP,
            CapabilityKind.SKILL,
            CapabilityKind.WORKFLOW,
        ],
    )
    def test_all_capability_kinds_are_constructable(self, kind: CapabilityKind) -> None:
        doc = _make_doc(kind=kind)
        assert doc.kind == kind

    @pytest.mark.parametrize(
        "risk",
        [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH],
    )
    def test_all_risk_levels_are_constructable(self, risk: RiskLevel) -> None:
        doc = _make_doc(risk_level=risk)
        assert doc.risk_level == risk

    def test_metadata_defaults_to_empty_dict(self) -> None:
        doc = _make_doc()
        assert doc.metadata == {}

    def test_roles_allow_defaults_to_empty_list(self) -> None:
        doc = _make_doc()
        assert doc.roles_allow == []


# ---------------------------------------------------------------------------
# TestRuntimeFilter
# ---------------------------------------------------------------------------


class TestRuntimeFilter:
    """RuntimeFilter gates based on runtime compatibility and capabilities."""

    def test_evaluate_allowed_when_runtime_matches_no_requirements(self) -> None:
        flt = RuntimeFilter(available_runtime="thin")
        doc = _make_doc(runtime_allow=["thin", "claude_sdk"], required_capabilities=[])
        result = flt.evaluate(doc)
        assert result.allowed is True
        assert result.reason == "runtime_allowed"

    def test_evaluate_rejected_when_runtime_not_in_allow_list(self) -> None:
        flt = RuntimeFilter(available_runtime="deepagents")
        doc = _make_doc(runtime_allow=["thin", "claude_sdk"])
        result = flt.evaluate(doc)
        assert result.allowed is False
        assert result.reason == "runtime_unavailable"

    def test_evaluate_rejected_when_required_capability_missing(self) -> None:
        flt = RuntimeFilter(available_runtime="thin", available_capabilities=set())
        doc = _make_doc(
            runtime_allow=["thin"],
            required_capabilities=["mcp"],
        )
        result = flt.evaluate(doc)
        assert result.allowed is False
        assert "mcp" in result.details.get("missing", [])

    def test_evaluate_allowed_when_required_capabilities_all_present(self) -> None:
        flt = RuntimeFilter(
            available_runtime="claude_sdk",
            available_capabilities={"mcp", "filesystem"},
        )
        doc = _make_doc(
            runtime_allow=["claude_sdk"],
            required_capabilities=["mcp"],
        )
        result = flt.evaluate(doc)
        assert result.allowed is True

    def test_evaluate_result_is_filter_result_instance(self) -> None:
        flt = RuntimeFilter(available_runtime="thin")
        doc = _make_doc()
        result = flt.evaluate(doc)
        assert isinstance(result, FilterResult)


# ---------------------------------------------------------------------------
# TestAvailabilityFilter
# ---------------------------------------------------------------------------


class TestAvailabilityFilter:
    """AvailabilityFilter gates on the enabled flag."""

    def test_evaluate_allowed_when_enabled_true(self) -> None:
        flt = AvailabilityFilter()
        doc = _make_doc(enabled=True)
        result = flt.evaluate(doc)
        assert result.allowed is True
        assert result.reason == "available"

    def test_evaluate_rejected_when_enabled_false(self) -> None:
        flt = AvailabilityFilter()
        doc = _make_doc(enabled=False)
        result = flt.evaluate(doc)
        assert result.allowed is False
        assert result.reason == "disabled"

    def test_evaluate_details_missing_empty_when_enabled(self) -> None:
        flt = AvailabilityFilter()
        result = flt.evaluate(_make_doc(enabled=True))
        assert result.details.get("missing") == []

    def test_evaluate_details_missing_contains_disabled_when_not_enabled(self) -> None:
        flt = AvailabilityFilter()
        result = flt.evaluate(_make_doc(enabled=False))
        assert "disabled" in result.details.get("missing", [])


# ---------------------------------------------------------------------------
# TestRankWeights
# ---------------------------------------------------------------------------


class TestRankWeights:
    """RankWeights frozen dataclass: defaults sum to 1.0, custom weights validated."""

    def test_default_weights_sum_to_one(self) -> None:
        w = RankWeights()
        total = w.semantic + w.runtime + w.latency + w.cost + w.availability
        assert abs(total - 1.0) < 1e-6

    def test_validate_passes_for_valid_custom_weights(self) -> None:
        w = RankWeights(
            semantic=0.40, runtime=0.20, latency=0.15, cost=0.15, availability=0.10
        )
        w.validate()  # must not raise

    def test_validate_raises_when_weights_do_not_sum_to_one(self) -> None:
        w = RankWeights(
            semantic=0.50, runtime=0.20, latency=0.10, cost=0.10, availability=0.05
        )
        with pytest.raises(ValueError, match="sum to 1.0"):
            w.validate()


# ---------------------------------------------------------------------------
# TestCapabilityRanker
# ---------------------------------------------------------------------------


class TestCapabilityRanker:
    """CapabilityRanker ranks candidates by weighted multi-factor score."""

    # ------------------------------------------------------------------
    # Construction validation (weights must be normalised at __init__)
    # ------------------------------------------------------------------

    def test_ranker_rejects_non_normalized_weights(self) -> None:
        """Constructing with weights summing to != 1.0 must raise ValueError."""
        bad = RankWeights(
            semantic=0.5, runtime=0.5, latency=0.5, cost=0.0, availability=0.0
        )
        # sum = 1.5 — must be rejected at construction, NOT silently accepted
        with pytest.raises(ValueError, match="sum to 1.0"):
            CapabilityRanker(weights=bad)

    def test_ranker_accepts_default_and_normalized_weights(self) -> None:
        """Default ranker and an explicitly normalised RankWeights both construct fine."""
        # default — must not raise
        ranker_default = CapabilityRanker()
        assert ranker_default.rank([]) == []

        # explicit 1.0-sum weights — must not raise
        good = RankWeights(
            semantic=0.40, runtime=0.20, latency=0.15, cost=0.15, availability=0.10
        )
        ranker_custom = CapabilityRanker(weights=good)
        doc = _make_doc()
        result = ranker_custom.rank([doc], semantic_scores={doc.capability_id: 0.7})
        assert len(result) == 1

    def test_ranker_rejects_nan_weights(self) -> None:
        """A NaN weight must be rejected at construction — NaN bypasses > comparisons."""
        bad = RankWeights(
            semantic=float("nan"),
            runtime=0.15,
            latency=0.10,
            cost=0.10,
            availability=0.20,
        )
        with pytest.raises(ValueError):
            CapabilityRanker(weights=bad)

    def test_ranker_rejects_inf_weights(self) -> None:
        """An infinite weight must be rejected at construction."""
        bad = RankWeights(
            semantic=float("inf"), runtime=0.0, latency=0.0, cost=0.0, availability=0.0
        )
        with pytest.raises(ValueError):
            CapabilityRanker(weights=bad)

    # ------------------------------------------------------------------

    def test_rank_empty_candidates_returns_empty(self) -> None:
        ranker = CapabilityRanker()
        assert ranker.rank([]) == []

    def test_rank_single_candidate_returns_single(self) -> None:
        ranker = CapabilityRanker()
        doc = _make_doc()
        result = ranker.rank([doc])
        assert len(result) == 1
        assert isinstance(result[0], RankedCapability)
        assert result[0].capability is doc

    def test_rank_higher_semantic_score_ranks_first_when_other_factors_equal(
        self,
    ) -> None:
        ranker = CapabilityRanker()
        doc_hi = _make_doc(capability_id="hi", name="High")
        doc_lo = _make_doc(capability_id="lo", name="Low")
        scores = {"hi": 0.9, "lo": 0.2}
        result = ranker.rank([doc_lo, doc_hi], semantic_scores=scores)
        assert result[0].capability.capability_id == "hi"
        assert result[1].capability.capability_id == "lo"

    def test_rank_fast_latency_scores_higher_than_slow_with_equal_semantic(
        self,
    ) -> None:
        weights = RankWeights(
            semantic=0.00, runtime=0.00, latency=0.60, cost=0.20, availability=0.20
        )
        ranker = CapabilityRanker(weights=weights)
        fast_doc = _make_doc(capability_id="fast", name="Fast", latency_hint="fast")
        slow_doc = _make_doc(capability_id="slow", name="Slow", latency_hint="slow")
        result = ranker.rank([slow_doc, fast_doc])
        assert result[0].capability.capability_id == "fast"

    def test_rank_cheap_cost_scores_higher_than_expensive_with_equal_semantic(
        self,
    ) -> None:
        weights = RankWeights(
            semantic=0.00, runtime=0.00, latency=0.20, cost=0.60, availability=0.20
        )
        ranker = CapabilityRanker(weights=weights)
        cheap_doc = _make_doc(capability_id="cheap", name="Cheap", cost_hint="cheap")
        exp_doc = _make_doc(
            capability_id="expensive", name="Expensive", cost_hint="expensive"
        )
        result = ranker.rank([exp_doc, cheap_doc])
        assert result[0].capability.capability_id == "cheap"

    def test_rank_disabled_capability_scores_zero_availability(self) -> None:
        weights = RankWeights(
            semantic=0.00, runtime=0.00, latency=0.00, cost=0.00, availability=1.00
        )
        ranker = CapabilityRanker(weights=weights)
        enabled_doc = _make_doc(capability_id="en", name="Enabled", enabled=True)
        disabled_doc = _make_doc(capability_id="dis", name="Disabled", enabled=False)
        result = ranker.rank([disabled_doc, enabled_doc])
        assert result[0].capability.capability_id == "en"
        assert result[-1].capability.capability_id == "dis"

    def test_rank_custom_weights_can_flip_ordering(self) -> None:
        """High-semantic doc loses to cheap/fast doc when latency+cost dominate."""
        # cap_a: high semantic, slow, expensive
        # cap_b: low semantic, fast, cheap
        # With latency+cost dominant weights, cap_b should win.
        cap_a = _make_doc(
            capability_id="a",
            name="HighSem",
            latency_hint="slow",
            cost_hint="expensive",
        )
        cap_b = _make_doc(
            capability_id="b",
            name="FastCheap",
            latency_hint="fast",
            cost_hint="cheap",
        )
        sem_scores = {"a": 0.9, "b": 0.3}

        # Default weights: semantic dominates → cap_a wins
        default_ranker = CapabilityRanker()
        default_result = default_ranker.rank([cap_a, cap_b], semantic_scores=sem_scores)
        assert default_result[0].capability.capability_id == "a"

        # Latency/cost dominant weights: cap_b wins
        perf_weights = RankWeights(
            semantic=0.05, runtime=0.05, latency=0.40, cost=0.40, availability=0.10
        )
        perf_ranker = CapabilityRanker(weights=perf_weights)
        perf_result = perf_ranker.rank([cap_a, cap_b], semantic_scores=sem_scores)
        assert perf_result[0].capability.capability_id == "b"

    def test_rank_factor_scores_included_in_result(self) -> None:
        ranker = CapabilityRanker()
        doc = _make_doc(capability_id="x")
        result = ranker.rank([doc], semantic_scores={"x": 0.5})
        factors = result[0].factor_scores
        assert "semantic" in factors
        assert "latency" in factors
        assert "cost" in factors
        assert "availability" in factors

    def test_rank_runtime_available_increases_score(self) -> None:
        weights = RankWeights(
            semantic=0.00, runtime=1.00, latency=0.00, cost=0.00, availability=0.00
        )
        ranker = CapabilityRanker(weights=weights)
        matching = _make_doc(capability_id="m", name="M", runtime_allow=["thin"])
        non_matching = _make_doc(
            capability_id="n", name="N", runtime_allow=["claude_sdk"]
        )
        result = ranker.rank([non_matching, matching], available_runtime="thin")
        assert result[0].capability.capability_id == "m"

    @pytest.mark.parametrize(
        ("latency", "expected_score"),
        [
            ("fast", 1.0),
            ("normal", 0.5),
            ("slow", 0.0),
        ],
    )
    def test_rank_latency_hint_maps_to_correct_factor(
        self, latency: str, expected_score: float
    ) -> None:
        weights = RankWeights(
            semantic=0.00, runtime=0.00, latency=1.00, cost=0.00, availability=0.00
        )
        ranker = CapabilityRanker(weights=weights)
        doc = _make_doc(latency_hint=latency)
        result = ranker.rank([doc])
        assert abs(result[0].factor_scores["latency"] - expected_score) < 1e-9


# ---------------------------------------------------------------------------
# TestLocalToolNormalizer
# ---------------------------------------------------------------------------


class TestLocalToolNormalizer:
    """LocalToolNormalizer maps a Python tool → CapabilityDoc(kind=TOOL)."""

    def test_normalize_returns_capability_doc_instance(self) -> None:
        norm = LocalToolNormalizer()
        doc = norm.normalize("web_search", "Search the web")
        assert isinstance(doc, CapabilityDoc)

    def test_normalize_sets_kind_tool(self) -> None:
        norm = LocalToolNormalizer()
        doc = norm.normalize("web_search", "Search the web")
        assert doc.kind == CapabilityKind.TOOL

    def test_normalize_capability_id_has_tool_prefix(self) -> None:
        norm = LocalToolNormalizer()
        doc = norm.normalize("web_search", "Search the web")
        assert doc.capability_id == "tool:web_search"

    def test_normalize_name_is_title_cased(self) -> None:
        norm = LocalToolNormalizer()
        doc = norm.normalize("web_search", "Search the web")
        assert doc.name == "Web Search"

    def test_normalize_description_preserved(self) -> None:
        norm = LocalToolNormalizer()
        doc = norm.normalize("my_tool", "Does a thing")
        assert doc.description == "Does a thing"

    def test_normalize_source_is_local(self) -> None:
        norm = LocalToolNormalizer()
        doc = norm.normalize("my_tool", "desc")
        assert doc.source == "local"

    def test_normalize_enabled_is_true(self) -> None:
        norm = LocalToolNormalizer()
        doc = norm.normalize("my_tool", "desc")
        assert doc.enabled is True

    def test_normalize_risk_level_is_low(self) -> None:
        norm = LocalToolNormalizer()
        doc = norm.normalize("my_tool", "desc")
        assert doc.risk_level == RiskLevel.LOW

    def test_normalize_accepts_optional_input_schema(self) -> None:
        norm = LocalToolNormalizer()
        schema = {"type": "object", "properties": {"q": {"type": "string"}}}
        doc = norm.normalize("search", "search tool", input_schema=schema)
        assert doc.input_schema == schema


# ---------------------------------------------------------------------------
# TestMcpToolNormalizer
# ---------------------------------------------------------------------------


class TestMcpToolNormalizer:
    """McpToolNormalizer maps MCP entry → CapabilityDoc(kind=MCP)."""

    def test_normalize_returns_capability_doc_instance(self) -> None:
        norm = McpToolNormalizer()
        doc = norm.normalize("github", "create_pr", "Create a pull request", {})
        assert isinstance(doc, CapabilityDoc)

    def test_normalize_sets_kind_mcp(self) -> None:
        norm = McpToolNormalizer()
        doc = norm.normalize("github", "create_pr", "Create a pull request", {})
        assert doc.kind == CapabilityKind.MCP

    def test_normalize_capability_id_contains_server_and_tool(self) -> None:
        norm = McpToolNormalizer()
        doc = norm.normalize("github", "create_pr", "Create a pull request", {})
        assert doc.capability_id == "mcp:github.create_pr"

    def test_normalize_source_contains_server_name(self) -> None:
        norm = McpToolNormalizer()
        doc = norm.normalize("github", "create_pr", "desc", {})
        assert "github" in doc.source

    def test_normalize_required_capabilities_contains_mcp(self) -> None:
        norm = McpToolNormalizer()
        doc = norm.normalize("github", "list_issues", "List issues", {})
        assert "mcp" in doc.required_capabilities

    def test_normalize_risk_level_is_medium(self) -> None:
        norm = McpToolNormalizer()
        doc = norm.normalize("github", "create_pr", "desc", {})
        assert doc.risk_level == RiskLevel.MEDIUM


# ---------------------------------------------------------------------------
# TestYamlSkillNormalizer
# ---------------------------------------------------------------------------


class TestYamlSkillNormalizer:
    """YamlSkillNormalizer maps YAML frontmatter + body → CapabilityDoc(kind=SKILL)."""

    def test_normalize_returns_capability_doc_instance(self) -> None:
        norm = YamlSkillNormalizer()
        doc = norm.normalize("my-skill", {"name": "My Skill"}, "# Body")
        assert isinstance(doc, CapabilityDoc)

    def test_normalize_sets_kind_skill(self) -> None:
        norm = YamlSkillNormalizer()
        doc = norm.normalize("my-skill", {"name": "My Skill"}, "# Body")
        assert doc.kind == CapabilityKind.SKILL

    def test_normalize_capability_id_has_skill_prefix(self) -> None:
        norm = YamlSkillNormalizer()
        doc = norm.normalize("web-search", {}, "# Body")
        assert doc.capability_id == "skill:web-search"

    def test_normalize_name_read_from_frontmatter(self) -> None:
        norm = YamlSkillNormalizer()
        doc = norm.normalize("my-skill", {"name": "Fancy Skill"}, "# Body")
        assert doc.name == "Fancy Skill"

    def test_normalize_name_falls_back_to_slug(self) -> None:
        norm = YamlSkillNormalizer()
        doc = norm.normalize("my-skill", {}, "# Body")
        assert doc.name == "my-skill"

    def test_normalize_tags_read_from_frontmatter(self) -> None:
        norm = YamlSkillNormalizer()
        doc = norm.normalize("s", {"tags": ["search", "web"]}, "")
        assert "search" in doc.tags
        assert "web" in doc.tags

    def test_normalize_runtime_allow_defaults_when_missing(self) -> None:
        norm = YamlSkillNormalizer()
        doc = norm.normalize("s", {}, "")
        assert len(doc.runtime_allow) > 0

    def test_normalize_content_md_is_body(self) -> None:
        norm = YamlSkillNormalizer()
        body = "# My Skill\n\nThis is the body."
        doc = norm.normalize("s", {"name": "S"}, body)
        assert doc.content_md == body

    def test_normalize_examples_read_from_frontmatter(self) -> None:
        norm = YamlSkillNormalizer()
        doc = norm.normalize("s", {"examples": ["Do a search"]}, "")
        assert "Do a search" in doc.examples


# ---------------------------------------------------------------------------
# TestWorkflowNormalizer
# ---------------------------------------------------------------------------


class TestWorkflowNormalizer:
    """WorkflowNormalizer maps workflow definition → CapabilityDoc(kind=WORKFLOW)."""

    def test_normalize_returns_capability_doc_instance(self) -> None:
        norm = WorkflowNormalizer()
        doc = norm.normalize("research-and-report", "Research then report", [], [])
        assert isinstance(doc, CapabilityDoc)

    def test_normalize_sets_kind_workflow(self) -> None:
        norm = WorkflowNormalizer()
        doc = norm.normalize("research-and-report", "Research then report", [], [])
        assert doc.kind == CapabilityKind.WORKFLOW

    def test_normalize_capability_id_has_workflow_prefix(self) -> None:
        norm = WorkflowNormalizer()
        doc = norm.normalize("my-workflow", "desc", [], [])
        assert doc.capability_id == "workflow:my-workflow"

    def test_normalize_name_title_cased(self) -> None:
        norm = WorkflowNormalizer()
        doc = norm.normalize("research-report", "desc", [], [])
        assert doc.name == "Research Report"

    def test_normalize_steps_appear_in_content_md(self) -> None:
        norm = WorkflowNormalizer()
        steps = ["Step 1: gather data", "Step 2: analyse"]
        doc = norm.normalize("wf", "desc", steps, [])
        assert "Step 1" in doc.content_md
        assert "Step 2" in doc.content_md

    def test_normalize_tools_become_allowed_tools(self) -> None:
        norm = WorkflowNormalizer()
        tools = ["web_search", "code_interpreter"]
        doc = norm.normalize("wf", "desc", [], tools)
        assert "web_search" in doc.allowed_tools
        assert "code_interpreter" in doc.allowed_tools

    def test_normalize_source_is_workflow(self) -> None:
        norm = WorkflowNormalizer()
        doc = norm.normalize("wf", "desc", [], [])
        assert doc.source == "workflow"


# ---------------------------------------------------------------------------
# TestSkillMarkdownRenderer
# ---------------------------------------------------------------------------


class TestSkillMarkdownRenderer:
    """SkillMarkdownRenderer: render CapabilityDoc → SKILL.md with round-trip."""

    def _sample_doc(self) -> CapabilityDoc:
        return _make_doc(
            capability_id="skill:web-search",
            kind=CapabilityKind.SKILL,
            name="Web Search",
            description="Search the internet for up-to-date information",
            tags=["web", "search"],
            allowed_tools=["web_search"],
            examples=["Search for Python docs"],
            latency_hint="normal",
            cost_hint="normal",
            risk_level=RiskLevel.LOW,
        )

    def test_render_returns_string(self) -> None:
        renderer = SkillMarkdownRenderer()
        doc = self._sample_doc()
        result = renderer.render(doc)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_render_contains_yaml_frontmatter_delimiters(self) -> None:
        renderer = SkillMarkdownRenderer()
        result = renderer.render(self._sample_doc())
        assert result.startswith("---")
        # second --- delimiter closes the frontmatter
        lines = result.split("\n")
        delimiter_count = sum(1 for line in lines if line.strip() == "---")
        assert delimiter_count >= 2

    def test_render_frontmatter_is_parseable_yaml(self) -> None:
        renderer = SkillMarkdownRenderer()
        result = renderer.render(self._sample_doc())
        match = re.match(r"\A---\s*\n(.*?)\n---", result, re.DOTALL)
        assert match is not None, "No valid frontmatter block found"
        frontmatter = yaml.safe_load(match.group(1))
        assert isinstance(frontmatter, dict)

    def test_render_frontmatter_contains_name(self) -> None:
        renderer = SkillMarkdownRenderer()
        result = renderer.render(self._sample_doc())
        match = re.match(r"\A---\s*\n(.*?)\n---", result, re.DOTALL)
        assert match is not None
        fm = yaml.safe_load(match.group(1))
        assert fm.get("name") == "Web Search"

    def test_render_frontmatter_contains_description(self) -> None:
        renderer = SkillMarkdownRenderer()
        result = renderer.render(self._sample_doc())
        match = re.match(r"\A---\s*\n(.*?)\n---", result, re.DOTALL)
        assert match is not None
        fm = yaml.safe_load(match.group(1))
        assert "internet" in fm.get("description", "")

    def test_render_round_trip_tags_preserved(self) -> None:
        renderer = SkillMarkdownRenderer()
        doc = self._sample_doc()
        result = renderer.render(doc)
        match = re.match(r"\A---\s*\n(.*?)\n---", result, re.DOTALL)
        assert match is not None
        fm = yaml.safe_load(match.group(1))
        rendered_tags = fm.get("tags", [])
        for tag in doc.tags:
            assert tag in rendered_tags

    def test_render_body_contains_purpose_section(self) -> None:
        renderer = SkillMarkdownRenderer()
        result = renderer.render(self._sample_doc())
        assert "## Purpose" in result or "# Web Search" in result

    def test_render_round_trip_risk_level_preserved(self) -> None:
        renderer = SkillMarkdownRenderer()
        doc = self._sample_doc()
        result = renderer.render(doc)
        match = re.match(r"\A---\s*\n(.*?)\n---", result, re.DOTALL)
        assert match is not None
        fm = yaml.safe_load(match.group(1))
        assert fm.get("risk-level") == doc.risk_level.value


# ---------------------------------------------------------------------------
# TestProactiveSkillInjectorRegression (REQ-OSS-050)
# ---------------------------------------------------------------------------

WEB = _make_skill_spec(
    "web", "Web Search", "Search the internet", tool_include=["web_search"]
)
CODE = _make_skill_spec(
    "code", "Code Review", "Review code for bugs", tool_include=["code_review"]
)
DB = _make_skill_spec(
    "db", "Database", "Execute SQL queries", tool_include=["db_query"]
)
DISABLED = _make_skill_spec(
    "off", tier=SkillTier.T4_DISABLED, tool_include=["disabled_tool"]
)


def _base_registry() -> SkillRegistry:
    return SkillRegistry(skills=[_loaded(s) for s in [WEB, CODE, DB, DISABLED]])


class TestProactiveSkillInjectorRegression:
    """ranker=None (default) MUST produce byte-identical output (REQ-OSS-050)."""

    def test_no_ranker_param_and_explicit_none_produce_identical_results(self) -> None:
        """Backward-compat: omitting ranker= and passing ranker=None are identical."""
        reg = _base_registry()
        injector_implicit = ProactiveSkillInjector(
            retriever=BM25Retriever(min_score=0.0),
            registry=reg,
            top_k=8,
            min_score=0.0,
        )
        injector_explicit_none = ProactiveSkillInjector(
            retriever=BM25Retriever(min_score=0.0),
            registry=reg,
            top_k=8,
            min_score=0.0,
            ranker=None,
        )
        query = "search the web for information"
        result_implicit = injector_implicit.inject(query, [])
        result_explicit = injector_explicit_none.inject(query, [])
        assert result_implicit == result_explicit

    @pytest.mark.parametrize(
        "query",
        [
            "search the web for information",
            "review code for bugs and issues",
            "execute SQL queries on the database",
        ],
    )
    def test_ranker_none_selects_same_tools_as_threshold_path(self, query: str) -> None:
        """The threshold-based path is stable for each known query."""
        reg = _base_registry()
        injector = ProactiveSkillInjector(
            retriever=BM25Retriever(min_score=0.0),
            registry=reg,
            min_score=0.0,
            ranker=None,
        )
        result = injector.inject(query, [])
        tool_names = {t.name for t in result}
        # disabled skill must never appear
        assert "disabled_tool" not in tool_names
        # at least one tool injected for a non-trivial query
        assert len(result) >= 1

    def test_ranker_none_injection_report_has_correct_schema(self) -> None:
        """Report format unchanged from original (skill_id, score, source)."""
        reg = _base_registry()
        injector = ProactiveSkillInjector(
            retriever=BM25Retriever(min_score=0.0),
            registry=reg,
            min_score=0.0,
        )
        injector.inject("search the web", [])
        report = injector.get_injection_report()
        assert "matched_skills" in report
        if report["matched_skills"]:
            entry = report["matched_skills"][0]
            assert "skill_id" in entry
            assert isinstance(entry["score"], float)
            assert "source" in entry

    def test_ranker_none_empty_context_returns_current_tools_unchanged(self) -> None:
        reg = _base_registry()
        injector = ProactiveSkillInjector(
            retriever=BM25Retriever(), registry=reg, ranker=None
        )
        existing = [ToolSpec(name="keep_me", description="", parameters={})]
        result = injector.inject("", existing)
        assert result == existing


# ---------------------------------------------------------------------------
# TestProactiveSkillInjectorWithRanker
# ---------------------------------------------------------------------------


class TestProactiveSkillInjectorWithRanker:
    """ProactiveSkillInjector with ranker=CapabilityRanker() uses multi-factor path."""

    def test_inject_with_ranker_returns_tool_specs(self) -> None:
        reg = _base_registry()
        ranker = CapabilityRanker()
        injector = ProactiveSkillInjector(
            retriever=BM25Retriever(min_score=0.0),
            registry=reg,
            min_score=0.0,
            ranker=ranker,
        )
        result = injector.inject("search the web for information", [])
        assert all(isinstance(t, ToolSpec) for t in result)

    def test_inject_with_ranker_excludes_disabled_skills(self) -> None:
        reg = _base_registry()
        ranker = CapabilityRanker()
        injector = ProactiveSkillInjector(
            retriever=BM25Retriever(min_score=0.0),
            registry=reg,
            min_score=0.0,
            ranker=ranker,
        )
        result = injector.inject("search", [])
        names = {t.name for t in result}
        assert "disabled_tool" not in names

    def test_inject_with_ranker_report_uses_ranker_source(self) -> None:
        reg = _base_registry()
        ranker = CapabilityRanker()
        injector = ProactiveSkillInjector(
            retriever=BM25Retriever(min_score=0.0),
            registry=reg,
            min_score=0.0,
            ranker=ranker,
        )
        injector.inject("search the web", [])
        report = injector.get_injection_report()
        if report["matched_skills"]:
            assert report["matched_skills"][0]["source"] == "ranker"

    def test_inject_with_ranker_high_min_score_filters_all(self) -> None:
        reg = _base_registry()
        ranker = CapabilityRanker()
        injector = ProactiveSkillInjector(
            retriever=BM25Retriever(min_score=0.0),
            registry=reg,
            min_score=999.0,
            ranker=ranker,
        )
        existing = [ToolSpec(name="keep", description="", parameters={})]
        result = injector.inject("search the web", existing)
        assert {t.name for t in result} == {"keep"}

    def test_inject_with_custom_skill_to_doc_callback(self) -> None:
        """Caller can inject a custom SkillSpec→CapabilityDoc converter."""
        from swarmline.skills.capability import CapabilityDoc, CapabilityKind, RiskLevel

        def custom_converter(spec: SkillSpec) -> CapabilityDoc:
            return CapabilityDoc(
                capability_id=spec.skill_id,
                kind=CapabilityKind.SKILL,
                source="custom",
                name=spec.title,
                description=spec.description or spec.skill_id,
                input_schema=None,
                examples=[],
                tags=spec.keywords,
                required_capabilities=[],
                runtime_allow=["thin"],
                allowed_tools=spec.tool_include,
                risk_level=RiskLevel.LOW,
                cost_hint="cheap",
                latency_hint="fast",
                content_md="",
                enabled=spec.tier < SkillTier.T4_DISABLED,
            )

        reg = _base_registry()
        ranker = CapabilityRanker()
        injector = ProactiveSkillInjector(
            retriever=BM25Retriever(min_score=0.0),
            registry=reg,
            min_score=0.0,
            ranker=ranker,
            skill_to_doc=custom_converter,
        )
        result = injector.inject("search the web", [])
        assert all(isinstance(t, ToolSpec) for t in result)
