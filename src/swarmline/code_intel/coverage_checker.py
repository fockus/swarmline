"""ImportBasedCoverageAnalyzer — coverage mapping via import tracing.

Implements CoverageAnalyzerPort. Identifies test files by naming convention
(test_*.py / *_test.py) and traces their imports to map seams to covering tests.
"""

from __future__ import annotations

import os
from collections import defaultdict

from swarmline.code_intel.types import (
    CoverageMapping,
    LanguageSeam,
    RepoMap,
    file_to_module,
)


class ImportBasedCoverageAnalyzer:
    """Maps language seams to test files that import the seam's module."""

    def map_coverage(
        self, repo_map: RepoMap, seams: list[LanguageSeam]
    ) -> CoverageMapping:
        if not seams:
            return CoverageMapping(seam_to_tests={})

        test_files = _find_test_files(repo_map)
        module_to_tests = _build_module_to_test_files(repo_map, test_files)

        mapping: dict[str, tuple[str, ...]] = {}
        for seam in seams:
            module = file_to_module(seam.file_path, repo_map.root_path)
            tests = tuple(sorted(module_to_tests.get(module, [])))
            mapping[seam.signature] = tests

        return CoverageMapping(seam_to_tests=mapping)


def _find_test_files(repo_map: RepoMap) -> set[str]:
    """Find files matching test_*.py or *_test.py patterns."""
    result: set[str] = set()
    for f in repo_map.files:
        basename = os.path.basename(f)
        if (
            basename.startswith("test_") and basename.endswith(".py")
        ) or basename.endswith("_test.py"):
            result.add(f)
    return result


def _build_module_to_test_files(
    repo_map: RepoMap, test_files: set[str]
) -> dict[str, list[str]]:
    """Map module names to test files that import them."""
    result: dict[str, list[str]] = defaultdict(list)
    for edge in repo_map.imports:
        if edge.source_file in test_files:
            result[edge.target_module].append(edge.source_file)
    return dict(result)
