"""Skills module - SkillRegistry + types + protocols.

YamlSkillLoader has been moved to the application's infrastructure layer.
This module contains only the pure registry without IO.

Phase 58: adds SkillStore/SkillRetriever protocols, tier/health types,
and optional retriever/injector exports.

OSS-T7: capability discovery — CapabilityDoc, filters, ranker,
normalizers, and SkillMarkdownRenderer are directly exported (no lazy
load needed; they have no heavy optional dependencies).
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

from swarmline.skills.capability import CapabilityDoc, CapabilityKind, RiskLevel
from swarmline.skills.capability_filters import (
    AvailabilityFilter,
    CapabilityFilter,
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
from swarmline.skills.protocols import ScoredSkill, SkillRetriever, SkillStore
from swarmline.skills.registry import SkillRegistry
from swarmline.skills.tier import SkillHealthStatus, SkillTier
from swarmline.skills.types import LoadedSkill, McpServerSpec, SkillSpec

__all__ = [
    # pre-OSS-T7
    "LoadedSkill",
    "McpServerSpec",
    "ScoredSkill",
    "SkillHealthStatus",
    "SkillRegistry",
    "SkillRetriever",
    "SkillSpec",
    "SkillStore",
    "SkillTier",
    # OSS-T7 capability discovery
    "AvailabilityFilter",
    "CapabilityDoc",
    "CapabilityFilter",
    "CapabilityKind",
    "CapabilityRanker",
    "FilterResult",
    "LocalToolNormalizer",
    "McpToolNormalizer",
    "RankWeights",
    "RankedCapability",
    "RiskLevel",
    "RuntimeFilter",
    "SkillMarkdownRenderer",
    "WorkflowNormalizer",
    "YamlSkillNormalizer",
]

_OPTIONAL_EXPORTS: dict[str, tuple[str, str, str]] = {
    "YamlSkillLoader": (
        "swarmline.skills.loader",
        "YamlSkillLoader",
        "Install PyYAML to use YamlSkillLoader.",
    ),
    "load_mcp_from_settings": (
        "swarmline.skills.loader",
        "load_mcp_from_settings",
        "Install PyYAML to use load_mcp_from_settings.",
    ),
    "BM25Retriever": (
        "swarmline.skills.bm25",
        "BM25Retriever",
        "BM25Retriever not yet available.",
    ),
    "HybridSkillRetriever": (
        "swarmline.skills.hybrid_retriever",
        "HybridSkillRetriever",
        "HybridSkillRetriever not yet available.",
    ),
    "EmbeddingRetriever": (
        "swarmline.skills.embedding_retriever",
        "EmbeddingRetriever",
        "EmbeddingRetriever not yet available.",
    ),
    "ProactiveSkillInjector": (
        "swarmline.skills.injector",
        "ProactiveSkillInjector",
        "ProactiveSkillInjector not yet available.",
    ),
    "SkillInjectionHook": (
        "swarmline.skills.injector",
        "SkillInjectionHook",
        "SkillInjectionHook not yet available.",
    ),
}


def __getattr__(name: str) -> Any:
    optional = _OPTIONAL_EXPORTS.get(name)
    if optional is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name, hint = optional
    try:
        module = import_module(module_name)
        value = getattr(module, attr_name)
    except (ImportError, AttributeError) as exc:
        raise ImportError(f"{attr_name} is unavailable. {hint}") from exc

    globals()[name] = value
    return value
