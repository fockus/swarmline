"""GraphImpactAnalyzer — BFS-based blast radius analysis through reverse import graph.

Implements ImpactAnalyzerPort. Builds reverse adjacency from RepoMap.imports,
then traverses it via BFS to compute directly and transitively affected files.
"""

from __future__ import annotations

from collections import defaultdict, deque

from swarmline.code_intel.types import ImpactResult, RepoMap, file_to_module


class GraphImpactAnalyzer:
    """Analyzes change impact by BFS through reverse import graph."""

    def analyze_impact(self, repo_map: RepoMap, target_files: set[str]) -> ImpactResult:
        reverse_graph = _build_reverse_graph(repo_map)
        file_to_module = _build_file_to_module(repo_map)

        target_modules: set[str] = set()
        for f in target_files:
            module = file_to_module.get(f)
            if module is not None:
                target_modules.add(module)

        directly_affected: set[str] = set()
        visited: set[str] = set(target_files)
        queue: deque[str] = deque()

        for module in target_modules:
            for dep_file in reverse_graph.get(module, set()):
                if dep_file not in visited:
                    directly_affected.add(dep_file)
                    visited.add(dep_file)
                    queue.append(dep_file)

        transitively_affected: set[str] = set()
        while queue:
            current_file = queue.popleft()
            current_module = file_to_module.get(current_file)
            if current_module is None:
                continue
            for dep_file in reverse_graph.get(current_module, set()):
                if dep_file not in visited:
                    transitively_affected.add(dep_file)
                    visited.add(dep_file)
                    queue.append(dep_file)

        total = len(repo_map.files)
        all_affected = len(directly_affected) + len(transitively_affected)
        score = all_affected / total if total > 0 else 0.0

        return ImpactResult(
            target_files=tuple(sorted(target_files)),
            directly_affected=tuple(sorted(directly_affected)),
            transitively_affected=tuple(sorted(transitively_affected)),
            blast_radius_score=score,
        )


def _build_reverse_graph(repo_map: RepoMap) -> dict[str, set[str]]:
    """Build reverse import adjacency: module_name -> set of files that import it."""
    reverse: dict[str, set[str]] = defaultdict(set)
    for edge in repo_map.imports:
        reverse[edge.target_module].add(edge.source_file)
    return dict(reverse)


def _build_file_to_module(repo_map: RepoMap) -> dict[str, str]:
    """Map each file path to its Python module name."""
    result: dict[str, str] = {}
    for f in repo_map.files:
        result[f] = file_to_module(f, repo_map.root_path)
    return result
