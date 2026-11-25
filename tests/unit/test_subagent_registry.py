"""SubagentRegistry — role/toolset/briefing catalog + capability lookup.

TDD (RED -> GREEN). Covers REQ-ORC-100/101:

- REQ-ORC-100: a `SubagentRegistry` lists each subagent type with its role,
  scoped toolset, and briefing template; a `researcher` entry is registered
  by default, scoped to `ToolsetPolicy.researcher()`.
- REQ-ORC-101: skill/MCP capability lookup is routed through the EXISTING
  `SkillRegistry.search` + ranker — never reimplemented. Proven here via a
  spy `SkillRetriever` wired into a real `SkillRegistry`.
"""

from __future__ import annotations

from swarmline.orchestration.subagent_registry import (
    SubagentEntry,
    SubagentRegistry,
    default_subagent_registry,
)
from swarmline.policy.toolset_policy import RESEARCHER_TOOLS, ToolsetPolicy
from swarmline.skills.protocols import ScoredSkill
from swarmline.skills.registry import SkillRegistry
from swarmline.skills.types import LoadedSkill, SkillSpec


def _make_entry(role: str = "reviewer") -> SubagentEntry:
    return SubagentEntry(
        role=role,
        scoped_toolset=ToolsetPolicy(roles={role: frozenset({"read"})}),
        briefing_template="Goal: {goal}. Constraints: {constraints}.",
    )


def _make_loaded_skill(skill_id: str = "s1") -> LoadedSkill:
    return LoadedSkill(
        spec=SkillSpec(skill_id=skill_id, title=skill_id.upper()),
        instruction_md="",
    )


class _SpyRetriever:
    """Records `retrieve` calls and returns a fixed, known result."""

    def __init__(self, result: list[ScoredSkill]) -> None:
        self._result = result
        self.calls: list[tuple[str, list[SkillSpec], int]] = []

    def retrieve(
        self, query: str, candidates: list[SkillSpec], top_k: int = 5
    ) -> list[ScoredSkill]:
        self.calls.append((query, candidates, top_k))
        return self._result


def test_register_then_get_returns_registered_entry() -> None:
    """register() followed by get(role) returns the same entry."""
    registry = SubagentRegistry()
    entry = _make_entry()

    registry.register(entry)

    assert registry.get(entry.role) is entry


def test_register_then_list_entries_contains_registered_entry() -> None:
    """register() followed by list_entries() includes the entry."""
    registry = SubagentRegistry()
    entry = _make_entry()

    registry.register(entry)

    assert entry in registry.list_entries()


def test_get_unregistered_role_returns_none() -> None:
    """get() for a role that was never registered returns None."""
    registry = SubagentRegistry()

    assert registry.get("nonexistent-role") is None


def test_default_registry_researcher_entry_scoped_to_researcher_tools() -> None:
    """default_subagent_registry() has a researcher entry scoped to RESEARCHER_TOOLS."""
    registry = default_subagent_registry()

    researcher = registry.get("researcher")

    assert researcher is not None
    assert researcher.role == "researcher"
    allowed = researcher.scoped_toolset.allowed_tools("researcher")
    assert allowed
    assert allowed == RESEARCHER_TOOLS
    assert isinstance(researcher.briefing_template, str)
    assert researcher.briefing_template != ""


def test_find_skills_delegates_to_existing_skill_registry_search_and_ranker() -> None:
    """find_skills() routes through the real SkillRegistry.search -> ranker (REQ-ORC-101).

    No discovery/ranking is reimplemented in SubagentRegistry: the spy proves
    the query reaches the injected SkillRegistry's retriever unmodified, and
    the spy's result is returned verbatim.
    """
    skill_registry = SkillRegistry([_make_loaded_skill("s1")])
    expected = [
        ScoredSkill(skill=_make_loaded_skill("s1").spec, score=0.9, source="spy")
    ]
    spy = _SpyRetriever(expected)
    skill_registry.set_retriever(spy)
    registry = SubagentRegistry(skill_store=skill_registry)

    result = registry.find_skills("some query")

    assert len(spy.calls) == 1
    called_query, _candidates, _top_k = spy.calls[0]
    assert called_query == "some query"
    assert result == expected


def test_find_skills_without_skill_store_returns_empty_list() -> None:
    """find_skills() on a registry with no skill_store returns [] without crashing."""
    registry = SubagentRegistry()

    assert registry.find_skills("anything") == []
