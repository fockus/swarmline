"""Code Intelligence package — repository mapping, impact analysis, edit planning.

Lazy exports via __getattr__ to keep import cost minimal.
"""

from __future__ import annotations

_TYPE_EXPORTS = {
    "SymbolKind",
    "SymbolInfo",
    "ImportEdge",
    "RepoMap",
    "ImpactResult",
    "LanguageSeam",
    "CoverageMapping",
    "EditPlan",
}

_PROTOCOL_EXPORTS = {
    "RepoMapperPort",
    "ImpactAnalyzerPort",
    "LanguageParserPort",
    "CoverageAnalyzerPort",
}

_REPO_MAPPER_EXPORTS = {
    "ASTRepoMapper",
}

_IMPACT_ANALYZER_EXPORTS = {
    "GraphImpactAnalyzer",
}

_COVERAGE_CHECKER_EXPORTS = {
    "ImportBasedCoverageAnalyzer",
}

_LANGUAGE_PARSERS_EXPORTS = {
    "PythonSeamParser",
    "TypeScriptSeamParser",
    "CompositeLanguageParser",
}

_EDIT_PLANNER_EXPORTS = {
    "plan_edit",
}

_TOOLS_EXPORTS = {
    "create_code_intel_tools",
}

_ALL_EXPORTS = (
    _TYPE_EXPORTS
    | _PROTOCOL_EXPORTS
    | _REPO_MAPPER_EXPORTS
    | _IMPACT_ANALYZER_EXPORTS
    | _COVERAGE_CHECKER_EXPORTS
    | _LANGUAGE_PARSERS_EXPORTS
    | _EDIT_PLANNER_EXPORTS
    | _TOOLS_EXPORTS
)

__all__ = list(_ALL_EXPORTS)

_MODULE_MAP: dict[str, str] = {
    **{name: "types" for name in _TYPE_EXPORTS},
    **{name: "protocols" for name in _PROTOCOL_EXPORTS},
    **{name: "repo_mapper" for name in _REPO_MAPPER_EXPORTS},
    **{name: "impact_analyzer" for name in _IMPACT_ANALYZER_EXPORTS},
    **{name: "coverage_checker" for name in _COVERAGE_CHECKER_EXPORTS},
    **{name: "language_parsers" for name in _LANGUAGE_PARSERS_EXPORTS},
    **{name: "edit_planner" for name in _EDIT_PLANNER_EXPORTS},
    **{name: "tools" for name in _TOOLS_EXPORTS},
}


def __getattr__(name: str) -> object:
    module_name = _MODULE_MAP.get(name)
    if module_name is not None:
        import importlib

        mod = importlib.import_module(f"swarmline.code_intel.{module_name}")
        return getattr(mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
