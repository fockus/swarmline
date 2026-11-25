"""Tests FileRegistry: add/search/markdown rendering - TDD."""

from __future__ import annotations

import pytest
from swarmline.artifacts.file_registry import FileRegistry
from swarmline.artifacts.run_root import ArtifactRoot


@pytest.fixture
def root(tmp_path):
    return ArtifactRoot.create(tmp_path, run_id="run_1")


class TestAddAndPersist:
    def test_add_writes_registry_json_and_markdown(self, root) -> None:
        registry = FileRegistry(root)

        registry.add(
            path="notes/step_1.md", description="analysis of X", category="notes"
        )

        assert (root.path / ".registry.json").exists()
        assert (root.path / ".registry.md").exists()

    def test_add_survives_reload_from_disk(self, root) -> None:
        registry = FileRegistry(root)
        registry.add(
            path="notes/step_1.md", description="analysis of X", category="notes"
        )

        reloaded = FileRegistry(root)

        assert reloaded.count() == 1
        assert reloaded.get_by_path("notes/step_1.md") is not None

    def test_add_existing_path_updates_in_place_not_duplicated(self, root) -> None:
        registry = FileRegistry(root)
        registry.add(path="notes/a.md", description="v1", category="notes")

        registry.add(path="notes/a.md", description="v2", category="notes")

        assert registry.count() == 1
        assert registry.get_by_path("notes/a.md").description == "v2"

    def test_remove_deletes_entry(self, root) -> None:
        registry = FileRegistry(root)
        registry.add(path="notes/a.md", description="v1", category="notes")

        removed = registry.remove("notes/a.md")

        assert removed is True
        assert registry.get_by_path("notes/a.md") is None

    def test_remove_missing_path_returns_false(self, root) -> None:
        registry = FileRegistry(root)

        assert registry.remove("does/not/exist.md") is False


class TestMarkdownRendering:
    def test_write_markdown_groups_entries_by_category_order(self, root) -> None:
        registry = FileRegistry(root)
        registry.add(path="charts/c.svg", description="a chart", category="charts")
        registry.add(path="notes/n.md", description="a note", category="notes")

        markdown = registry.get_markdown()

        notes_index = markdown.index("## Notes")
        charts_index = markdown.index("## Charts")
        assert notes_index < charts_index  # CATEGORY_ORDER: notes before charts

    def test_markdown_truncates_long_descriptions(self, root) -> None:
        registry = FileRegistry(root)
        long_description = "x" * 100

        registry.add(path="notes/a.md", description=long_description, category="notes")

        markdown = registry.get_markdown()
        assert "x" * 57 + "..." in markdown

    def test_markdown_includes_total_file_count(self, root) -> None:
        registry = FileRegistry(root)
        registry.add(path="notes/a.md", description="a", category="notes")
        registry.add(path="notes/b.md", description="b", category="notes")

        assert "Total files: 2" in registry.get_markdown()

    def test_unknown_category_rendered_under_other_section(self, root) -> None:
        registry = FileRegistry(root)

        registry.add(path="misc/x.md", description="misc file", category="misc")

        assert "## Misc" in registry.get_markdown()


class TestSearch:
    def test_search_matches_description(self, root) -> None:
        registry = FileRegistry(root)
        registry.add(
            path="notes/a.md",
            description="quarterly revenue analysis",
            category="notes",
        )
        registry.add(path="notes/b.md", description="unrelated topic", category="notes")

        results = registry.search("revenue")

        assert len(results) == 1
        assert results[0].path == "notes/a.md"

    def test_search_matches_path(self, root) -> None:
        registry = FileRegistry(root)
        registry.add(
            path="data/raw/prices.csv", description="raw data", category="data"
        )

        results = registry.search("prices")

        assert len(results) == 1

    def test_search_ranks_path_match_above_description_only_match(self, root) -> None:
        registry = FileRegistry(root)
        registry.add(
            path="notes/other.md",
            description="mentions revenue in passing",
            category="notes",
        )
        registry.add(path="notes/revenue.md", description="unrelated", category="notes")

        results = registry.search("revenue")

        assert results[0].path == "notes/revenue.md"

    def test_search_empty_query_returns_empty_list(self, root) -> None:
        registry = FileRegistry(root)
        registry.add(path="notes/a.md", description="a", category="notes")

        assert registry.search("") == []

    def test_search_respects_max_results(self, root) -> None:
        registry = FileRegistry(root)
        for i in range(5):
            registry.add(
                path=f"notes/n{i}.md", description="matching note", category="notes"
            )

        results = registry.search("matching", max_results=2)

        assert len(results) == 2
