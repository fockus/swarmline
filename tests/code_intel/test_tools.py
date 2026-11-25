"""Unit tests for code intelligence tool factory — TDD red phase first.

Tests cover: tool creation, structured output, all 5 tools.
"""

from __future__ import annotations

import json
import os
import textwrap

import pytest

from swarmline.code_intel.coverage_checker import ImportBasedCoverageAnalyzer
from swarmline.code_intel.impact_analyzer import GraphImpactAnalyzer
from swarmline.code_intel.language_parsers import (
    CompositeLanguageParser,
    PythonSeamParser,
)
from swarmline.code_intel.repo_mapper import ASTRepoMapper


@pytest.fixture()
def sample_repo(tmp_path: object) -> str:
    """Create a temp repo with multiple Python files."""
    root = str(tmp_path)

    main_py = os.path.join(root, "main.py")
    with open(main_py, "w") as f:
        f.write(
            textwrap.dedent("""\
            from utils import helper

            def main() -> None:
                helper()
        """)
        )

    utils_py = os.path.join(root, "utils.py")
    with open(utils_py, "w") as f:
        f.write(
            textwrap.dedent("""\
            def helper() -> str:
                return "ok"
        """)
        )

    test_py = os.path.join(root, "test_utils.py")
    with open(test_py, "w") as f:
        f.write(
            textwrap.dedent("""\
            from utils import helper

            def test_helper() -> None:
                assert helper() == "ok"
        """)
        )

    return root


@pytest.fixture()
def tools(sample_repo: str) -> dict[str, object]:
    """Build code intel tools for the sample repo."""
    from swarmline.code_intel.tools import create_code_intel_tools

    mapper = ASTRepoMapper()
    impact = GraphImpactAnalyzer()
    parser = CompositeLanguageParser()
    parser.register_parser(PythonSeamParser())
    coverage = ImportBasedCoverageAnalyzer()

    specs, executors = create_code_intel_tools(
        repo_mapper=mapper,
        impact_analyzer=impact,
        language_parser=parser,
        coverage_analyzer=coverage,
    )
    return {"specs": specs, "executors": executors, "repo": sample_repo}


class TestToolFactory:
    def test_creates_five_tools(self, tools: dict[str, object]) -> None:
        specs = tools["specs"]
        assert len(specs) == 5

    def test_tool_names(self, tools: dict[str, object]) -> None:
        specs = tools["specs"]
        expected = {
            "repo_map",
            "impact_analysis",
            "find_seams",
            "plan_edit",
            "check_coverage",
        }
        assert set(specs.keys()) == expected

    def test_each_tool_has_name_and_description(self, tools: dict[str, object]) -> None:
        specs = tools["specs"]
        for name, spec in specs.items():
            assert spec.name == name
            assert len(spec.description) > 0


class TestRepoMapTool:
    def test_repo_map_returns_structured_json(self, tools: dict[str, object]) -> None:
        executors = tools["executors"]
        repo = tools["repo"]
        result = executors["repo_map"]({"root_path": repo})
        parsed = json.loads(result)
        assert "root_path" in parsed
        assert "files" in parsed
        assert "symbols" in parsed
        assert "imports" in parsed

    def test_repo_map_with_extensions(self, tools: dict[str, object]) -> None:
        executors = tools["executors"]
        repo = tools["repo"]
        result = executors["repo_map"]({"root_path": repo, "extensions": [".py"]})
        parsed = json.loads(result)
        assert len(parsed["files"]) >= 2


class TestImpactAnalysisTool:
    def test_impact_analysis_returns_structured_json(
        self, tools: dict[str, object]
    ) -> None:
        executors = tools["executors"]
        repo = tools["repo"]
        result = executors["impact_analysis"](
            {
                "root_path": repo,
                "target_files": [os.path.join(repo, "utils.py")],
            }
        )
        parsed = json.loads(result)
        assert "target_files" in parsed
        assert "directly_affected" in parsed
        assert "blast_radius_score" in parsed


class TestFindSeamsTool:
    def test_find_seams_returns_list(self, tools: dict[str, object]) -> None:
        executors = tools["executors"]
        repo = tools["repo"]
        result = executors["find_seams"](
            {
                "file_path": os.path.join(repo, "utils.py"),
            }
        )
        parsed = json.loads(result)
        assert isinstance(parsed, list)
        assert len(parsed) > 0
        assert "signature" in parsed[0]


class TestPlanEditTool:
    def test_plan_edit_returns_structured_json(self, tools: dict[str, object]) -> None:
        executors = tools["executors"]
        repo = tools["repo"]
        result = executors["plan_edit"](
            {
                "root_path": repo,
                "target_files": [os.path.join(repo, "utils.py")],
            }
        )
        parsed = json.loads(result)
        assert "target_files" in parsed
        assert "ordered_edit_files" in parsed
        assert "impact" in parsed
        assert "suggested_test_commands" in parsed


class TestCheckCoverageTool:
    def test_check_coverage_returns_structured_json(
        self, tools: dict[str, object]
    ) -> None:
        executors = tools["executors"]
        repo = tools["repo"]
        result = executors["check_coverage"](
            {
                "root_path": repo,
                "target_files": [os.path.join(repo, "utils.py")],
            }
        )
        parsed = json.loads(result)
        assert "seam_to_tests" in parsed
