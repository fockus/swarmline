"""Tests for YAML frontmatter parser and serializer."""

from __future__ import annotations

from swarmline.memory_bank.frontmatter import parse_frontmatter, render_frontmatter
from swarmline.memory_bank.knowledge_types import DocumentMeta


class TestParseFrontmatter:
    def test_parse_with_frontmatter(self) -> None:
        text = "---\nkind: note\ntags: [a, b]\nimportance: high\n---\nHello world"
        meta, body = parse_frontmatter(text)
        assert meta is not None
        assert meta.kind == "note"
        assert meta.tags == ("a", "b")
        assert meta.importance == "high"
        assert body == "Hello world"

    def test_parse_without_frontmatter(self) -> None:
        text = "Just plain text"
        meta, body = parse_frontmatter(text)
        assert meta is None
        assert body == "Just plain text"

    def test_parse_invalid_yaml(self) -> None:
        text = "---\n: : : invalid\n---\nBody"
        meta, body = parse_frontmatter(text)
        assert meta is None
        assert body == text

    def test_parse_no_closing_delimiter(self) -> None:
        text = "---\nkind: note\nNo closing"
        meta, body = parse_frontmatter(text)
        assert meta is None
        assert body == text

    def test_parse_non_dict_yaml(self) -> None:
        text = "---\n- item1\n- item2\n---\nBody"
        meta, body = parse_frontmatter(text)
        assert meta is None
        assert body == text

    def test_tags_as_list(self) -> None:
        text = "---\nkind: report\ntags: [tag1, tag2, tag3]\n---\nContent"
        meta, body = parse_frontmatter(text)
        assert meta is not None
        assert meta.tags == ("tag1", "tag2", "tag3")

    def test_empty_body(self) -> None:
        text = "---\nkind: status\n---\n"
        meta, body = parse_frontmatter(text)
        assert meta is not None
        assert meta.kind == "status"
        assert body == ""

    def test_custom_fields_preserved(self) -> None:
        text = "---\nkind: note\nauthor: Alice\nversion: 3\n---\nBody"
        meta, body = parse_frontmatter(text)
        assert meta is not None
        assert meta.custom == {"author": "Alice", "version": 3}

    def test_parse_with_created_updated(self) -> None:
        text = "---\nkind: plan\ncreated: 2026-01-01\nupdated: 2026-03-29\n---\nPlan"
        meta, body = parse_frontmatter(text)
        assert meta is not None
        assert meta.created == "2026-01-01"
        assert meta.updated == "2026-03-29"

    def test_parse_with_related(self) -> None:
        text = "---\nkind: note\nrelated: [plan.md, status.md]\n---\nBody"
        meta, body = parse_frontmatter(text)
        assert meta is not None
        assert meta.related == ("plan.md", "status.md")


class TestRenderFrontmatter:
    def test_render_minimal(self) -> None:
        meta = DocumentMeta(kind="note")
        result = render_frontmatter(meta, "Hello")
        assert result.startswith("---\n")
        assert "kind: note" in result
        assert result.endswith("\n\nHello")

    def test_render_with_tags(self) -> None:
        meta = DocumentMeta(kind="note", tags=("a", "b"))
        result = render_frontmatter(meta, "Body")
        assert "tags:" in result
        assert "- a" in result
        assert "- b" in result

    def test_render_skips_defaults(self) -> None:
        meta = DocumentMeta(kind="note")
        result = render_frontmatter(meta, "Body")
        assert "importance" not in result
        assert "created" not in result
        assert "updated" not in result
        assert "related" not in result

    def test_render_includes_non_defaults(self) -> None:
        meta = DocumentMeta(kind="status", importance="high", created="2026-01-01")
        result = render_frontmatter(meta, "Body")
        assert "importance: high" in result
        assert "created: '2026-01-01'" in result or "created: 2026-01-01" in result


class TestRoundtrip:
    def test_roundtrip(self) -> None:
        original = DocumentMeta(
            kind="experiment",
            tags=("ml", "nlp"),
            importance="high",
            created="2026-01-01",
            updated="2026-03-29",
            related=("plan.md",),
        )
        body = "Experiment content here."
        rendered = render_frontmatter(original, body)
        parsed_meta, parsed_body = parse_frontmatter(rendered)

        assert parsed_meta is not None
        assert parsed_meta.kind == original.kind
        assert parsed_meta.tags == original.tags
        assert parsed_meta.importance == original.importance
        assert parsed_meta.created == original.created
        assert parsed_meta.updated == original.updated
        assert parsed_meta.related == original.related
        assert parsed_body == body

    def test_roundtrip_with_custom(self) -> None:
        original = DocumentMeta(kind="note", custom={"author": "Bob"})
        body = "Content"
        rendered = render_frontmatter(original, body)
        parsed_meta, parsed_body = parse_frontmatter(rendered)

        assert parsed_meta is not None
        assert parsed_meta.custom.get("author") == "Bob"
        assert parsed_body == body
