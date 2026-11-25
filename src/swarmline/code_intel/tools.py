"""Code Intelligence tool factory — agent-callable tools for code analysis.

Creates 5 tools: repo_map, impact_analysis, find_seams, plan_edit, check_coverage.
All return JSON-serialized results. Follows workspace/tools.py pattern.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from swarmline.code_intel.edit_planner import plan_edit
from swarmline.code_intel.protocols import (
    CoverageAnalyzerPort,
    ImpactAnalyzerPort,
    LanguageParserPort,
    RepoMapperPort,
)
from swarmline.code_intel.types import RepoMap
from swarmline.domain_types import ToolSpec

if TYPE_CHECKING:
    from swarmline.code_intel.ranked_repo_mapper import RankedSymbol

# ---------------------------------------------------------------------------
# JSON Schemas
# ---------------------------------------------------------------------------

_REPO_MAP_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "root_path": {"type": "string", "description": "Repository root path"},
        "extensions": {
            "type": "array",
            "items": {"type": "string"},
            "description": 'File extensions to scan (default: [".py"])',
        },
    },
    "required": ["root_path"],
}

_IMPACT_ANALYSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "root_path": {"type": "string", "description": "Repository root path"},
        "target_files": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Files to analyze impact for",
        },
    },
    "required": ["root_path", "target_files"],
}

_FIND_SEAMS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "file_path": {"type": "string", "description": "File to find seams in"},
    },
    "required": ["file_path"],
}

_PLAN_EDIT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "root_path": {"type": "string", "description": "Repository root path"},
        "target_files": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Files to plan edits for",
        },
    },
    "required": ["root_path", "target_files"],
}

_CHECK_COVERAGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "root_path": {"type": "string", "description": "Repository root path"},
        "target_files": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Files to check coverage for",
        },
    },
    "required": ["root_path", "target_files"],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _error_json(error_type: str, message: str) -> str:
    return json.dumps({"status": "error", "error_type": error_type, "message": message})


def serialize_repo_map(
    repo_map: RepoMap,
    *,
    ranking: tuple[RankedSymbol, ...] | None = None,
) -> str:
    """Serialize a RepoMap to the canonical repo_map tool JSON.

    The DEFAULT path (``ranking=None``) is byte-identical to the legacy ``_repo_map``
    output: symbols carry exactly ``name/kind/file_path/line/signature`` — no ``rank``
    key ever appears. When ``ranking`` is supplied (Task 3 ranked branch), symbols are
    taken from the already rank-sorted, budget-truncated ``RankedSymbol`` tuple and each
    additionally carries its ``rank`` (sorted by rank descending).
    """
    if ranking is None:
        symbols = [
            {
                "name": s.name,
                "kind": s.kind.value,
                "file_path": s.file_path,
                "line": s.line,
                "signature": s.signature,
            }
            for s in repo_map.symbols
        ]
    else:
        symbols = [
            {
                "name": rs.symbol.name,
                "kind": rs.symbol.kind.value,
                "file_path": rs.symbol.file_path,
                "line": rs.symbol.line,
                "signature": rs.symbol.signature,
                "rank": rs.rank,
            }
            for rs in ranking
        ]

    return json.dumps(
        {
            "root_path": repo_map.root_path,
            "files": list(repo_map.files),
            "symbols": symbols,
            "imports": [
                {
                    "source_file": e.source_file,
                    "target_module": e.target_module,
                    "imported_names": list(e.imported_names),
                }
                for e in repo_map.imports
            ],
        }
    )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_code_intel_tools(
    *,
    repo_mapper: RepoMapperPort,
    impact_analyzer: ImpactAnalyzerPort,
    language_parser: LanguageParserPort,
    coverage_analyzer: CoverageAnalyzerPort,
) -> tuple[dict[str, ToolSpec], dict[str, Callable[..., Any]]]:
    """Create 5 code intelligence tools for agent use.

    Returns (specs dict, executors dict) matching the workspace tools pattern.
    """
    specs: dict[str, ToolSpec] = {}
    executors: dict[str, Callable[..., Any]] = {}

    # 1. repo_map
    def _repo_map(args: dict[str, Any]) -> str:
        root_path = args.get("root_path", "")
        if not root_path:
            return _error_json("validation", "root_path is required")

        extensions = set(args.get("extensions", [".py"]))
        repo_map = repo_mapper.scan_repo(root_path, extensions)

        return serialize_repo_map(repo_map)

    specs["repo_map"] = ToolSpec(
        name="repo_map",
        description="Scan repository for files, symbols, and import relationships",
        parameters=_REPO_MAP_SCHEMA,
    )
    executors["repo_map"] = _repo_map

    # 2. impact_analysis
    def _impact_analysis(args: dict[str, Any]) -> str:
        root_path = args.get("root_path", "")
        target_files = args.get("target_files", [])
        if not root_path or not target_files:
            return _error_json("validation", "root_path and target_files are required")

        repo_map = repo_mapper.scan_repo(
            root_path, language_parser.supported_extensions
        )
        result = impact_analyzer.analyze_impact(repo_map, set(target_files))

        return json.dumps(
            {
                "target_files": list(result.target_files),
                "directly_affected": list(result.directly_affected),
                "transitively_affected": list(result.transitively_affected),
                "blast_radius_score": result.blast_radius_score,
            }
        )

    specs["impact_analysis"] = ToolSpec(
        name="impact_analysis",
        description="Analyze blast radius of changes to target files",
        parameters=_IMPACT_ANALYSIS_SCHEMA,
    )
    executors["impact_analysis"] = _impact_analysis

    # 3. find_seams
    def _find_seams(args: dict[str, Any]) -> str:
        file_path = args.get("file_path", "")
        if not file_path:
            return _error_json("validation", "file_path is required")

        try:
            seams = language_parser.find_seams(file_path)
        except ValueError as e:
            return _error_json("unsupported_extension", str(e))

        return json.dumps(
            [
                {
                    "file_path": s.file_path,
                    "line": s.line,
                    "kind": s.kind.value,
                    "signature": s.signature,
                    "references_count": s.references_count,
                }
                for s in seams
            ]
        )

    specs["find_seams"] = ToolSpec(
        name="find_seams",
        description="Find public API seams (functions, classes, methods) in a file",
        parameters=_FIND_SEAMS_SCHEMA,
    )
    executors["find_seams"] = _find_seams

    # 4. plan_edit
    def _plan_edit(args: dict[str, Any]) -> str:
        root_path = args.get("root_path", "")
        target_files = args.get("target_files", [])
        if not root_path or not target_files:
            return _error_json("validation", "root_path and target_files are required")

        repo_map = repo_mapper.scan_repo(
            root_path, language_parser.supported_extensions
        )
        result = plan_edit(
            target_files=set(target_files),
            repo_map=repo_map,
            impact_analyzer=impact_analyzer,
            coverage_analyzer=coverage_analyzer,
            language_parser=language_parser,
        )

        coverage_data = None
        if result.coverage is not None:
            coverage_data = {
                k: list(v) for k, v in result.coverage.seam_to_tests.items()
            }

        return json.dumps(
            {
                "target_files": list(result.target_files),
                "ordered_edit_files": list(result.ordered_edit_files),
                "impact": {
                    "target_files": list(result.impact.target_files),
                    "directly_affected": list(result.impact.directly_affected),
                    "transitively_affected": list(result.impact.transitively_affected),
                    "blast_radius_score": result.impact.blast_radius_score,
                },
                "suggested_test_commands": list(result.suggested_test_commands),
                "coverage": coverage_data,
            }
        )

    specs["plan_edit"] = ToolSpec(
        name="plan_edit",
        description="Plan file edits with impact analysis and dependency ordering",
        parameters=_PLAN_EDIT_SCHEMA,
    )
    executors["plan_edit"] = _plan_edit

    # 5. check_coverage
    def _check_coverage(args: dict[str, Any]) -> str:
        root_path = args.get("root_path", "")
        target_files = args.get("target_files", [])
        if not root_path or not target_files:
            return _error_json("validation", "root_path and target_files are required")

        repo_map = repo_mapper.scan_repo(
            root_path, language_parser.supported_extensions
        )

        all_seams = []
        for f in target_files:
            try:
                seams = language_parser.find_seams(f)
                all_seams.extend(seams)
            except (ValueError, OSError):
                continue

        result = coverage_analyzer.map_coverage(repo_map, all_seams)

        return json.dumps(
            {"seam_to_tests": {k: list(v) for k, v in result.seam_to_tests.items()}}
        )

    specs["check_coverage"] = ToolSpec(
        name="check_coverage",
        description="Check test coverage mapping for target files",
        parameters=_CHECK_COVERAGE_SCHEMA,
    )
    executors["check_coverage"] = _check_coverage

    return specs, executors
