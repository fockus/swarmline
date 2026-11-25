"""EditPlanner — composes ports to produce an ordered edit plan.

Pure domain logic: no I/O, no external deps. Orchestrates impact analysis,
seam finding, coverage mapping, and dependency-based file ordering.
"""

from __future__ import annotations

from collections import deque

from swarmline.code_intel.protocols import (
    CoverageAnalyzerPort,
    ImpactAnalyzerPort,
    LanguageParserPort,
)
from swarmline.code_intel.types import (
    CoverageMapping,
    EditPlan,
    LanguageSeam,
    RepoMap,
    file_to_module,
)


def plan_edit(
    *,
    target_files: set[str],
    repo_map: RepoMap,
    impact_analyzer: ImpactAnalyzerPort,
    coverage_analyzer: CoverageAnalyzerPort | None,
    language_parser: LanguageParserPort,
) -> EditPlan:
    """Produce an ordered edit plan for the given target files.

    Steps:
    1. Analyze impact (blast radius)
    2. Find seams in all affected files
    3. Map coverage (if analyzer provided)
    4. Order files by dependency (imports-first)
    5. Suggest test commands
    """
    # 1. Impact analysis
    impact = impact_analyzer.analyze_impact(repo_map, target_files)

    # 2. Collect all affected files (targets + directly + transitively)
    all_affected = (
        set(impact.target_files)
        | set(impact.directly_affected)
        | set(impact.transitively_affected)
    )

    # 3. Find seams in affected files
    all_seams: list[LanguageSeam] = []
    for file_path in sorted(all_affected):
        try:
            seams = language_parser.find_seams(file_path)
            all_seams.extend(seams)
        except (ValueError, OSError):
            continue

    # 4. Map coverage
    coverage: CoverageMapping | None = None
    if coverage_analyzer is not None:
        coverage = coverage_analyzer.map_coverage(repo_map, all_seams)

    # 5. Order files by dependency (imports-first via topological sort)
    ordered = _order_by_dependency(all_affected, repo_map)

    # 6. Suggest test commands
    test_commands = _suggest_test_commands(coverage, all_affected)

    return EditPlan(
        target_files=tuple(sorted(target_files)),
        ordered_edit_files=tuple(ordered),
        impact=impact,
        suggested_test_commands=tuple(test_commands),
        coverage=coverage,
    )


def _order_by_dependency(files: set[str], repo_map: RepoMap) -> list[str]:
    """Order files so that imported files come before importing files.

    Uses Kahn's algorithm (topological sort). Files not in the import graph
    are appended at the end in sorted order.
    """
    file_set = set(files)

    # Build adjacency: file -> set of files it imports (that are in our set)
    # We need to map module names back to file paths
    module_to_file: dict[str, str] = {}
    for f in repo_map.files:
        module = file_to_module(f, repo_map.root_path)
        module_to_file[module] = f

    # Build graph: importing_file -> set of imported_files (within file_set)
    graph: dict[str, set[str]] = {f: set() for f in file_set}
    in_degree: dict[str, int] = {f: 0 for f in file_set}

    for edge in repo_map.imports:
        if edge.source_file not in file_set:
            continue
        target_file = module_to_file.get(edge.target_module)
        if target_file is not None and target_file in file_set:
            graph[edge.source_file].add(target_file)
            in_degree[target_file] = in_degree.get(target_file, 0) + 1

    # Kahn's: note we want imported files FIRST, so we track reverse:
    # if A imports B, B should come before A
    # In our graph, source_file has edge to target_file (it imports target)
    # So we want target before source -> reverse the edges for topo sort
    reverse_graph: dict[str, set[str]] = {f: set() for f in file_set}
    reverse_in_degree: dict[str, int] = {f: 0 for f in file_set}

    for source, targets in graph.items():
        for target in targets:
            reverse_graph[target].add(source)
            reverse_in_degree[source] = reverse_in_degree.get(source, 0) + 1

    # BFS topo sort on reverse graph
    queue: deque[str] = deque(
        sorted(f for f in file_set if reverse_in_degree.get(f, 0) == 0)
    )
    result: list[str] = []
    visited: set[str] = set()

    while queue:
        node = queue.popleft()
        if node in visited:
            continue
        visited.add(node)
        result.append(node)
        for neighbor in sorted(reverse_graph.get(node, set())):
            reverse_in_degree[neighbor] -= 1
            if reverse_in_degree[neighbor] == 0 and neighbor not in visited:
                queue.append(neighbor)

    # Add any remaining files (cycle or disconnected)
    for f in sorted(file_set):
        if f not in visited:
            result.append(f)

    return result


def _suggest_test_commands(
    coverage: CoverageMapping | None, affected_files: set[str]
) -> list[str]:
    """Generate suggested pytest commands based on coverage and affected files."""
    test_files: set[str] = set()

    if coverage is not None:
        for tests in coverage.seam_to_tests.values():
            test_files.update(tests)

    if test_files:
        return [f"pytest {' '.join(sorted(test_files))}"]

    # Fallback: suggest running tests for affected file names
    commands: list[str] = []
    for f in sorted(affected_files):
        basename = f.rsplit("/", 1)[-1] if "/" in f else f
        if basename.endswith(".py"):
            module = basename[:-3]
            commands.append(f"pytest -k {module}")

    return commands if commands else ["pytest"]
