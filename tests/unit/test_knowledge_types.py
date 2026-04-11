"""Tests for knowledge bank domain types."""

from __future__ import annotations

import dataclasses

import pytest

from swarmline.memory_bank.knowledge_types import (
    ChecklistItem,
    DocumentMeta,
    ExperimentRecord,
    IndexEntry,
    KnowledgeBankConfig,
    KnowledgeEntry,
    KnowledgeIndex,
    LearnedPattern,
    QualityCriterion,
)


class TestDocumentMeta:
    def test_document_meta_defaults(self) -> None:
        meta = DocumentMeta(kind="note")
        assert meta.kind == "note"
        assert meta.tags == ()
        assert meta.importance == "medium"
        assert meta.created == ""
        assert meta.updated == ""
        assert meta.related == ()
        assert meta.custom == {}

    def test_document_meta_full(self) -> None:
        meta = DocumentMeta(
            kind="status",
            tags=("a", "b"),
            importance="high",
            created="2026-01-01",
            updated="2026-03-29",
            related=("plan.md",),
            custom={"author": "test"},
        )
        assert meta.kind == "status"
        assert meta.tags == ("a", "b")
        assert meta.importance == "high"
        assert meta.custom == {"author": "test"}


class TestKnowledgeEntry:
    def test_knowledge_entry_construction(self) -> None:
        meta = DocumentMeta(kind="note")
        entry = KnowledgeEntry(path="notes/test.md", meta=meta, content="hello")
        assert entry.path == "notes/test.md"
        assert entry.meta is meta
        assert entry.content == "hello"
        assert entry.size_bytes == 0

    def test_knowledge_entry_with_size(self) -> None:
        meta = DocumentMeta(kind="report")
        entry = KnowledgeEntry(path="r.md", meta=meta, content="x", size_bytes=42)
        assert entry.size_bytes == 42


class TestIndexEntry:
    def test_index_entry_construction(self) -> None:
        ie = IndexEntry(path="notes/a.md", kind="note")
        assert ie.path == "notes/a.md"
        assert ie.kind == "note"
        assert ie.tags == ()
        assert ie.importance == "medium"
        assert ie.summary == ""
        assert ie.updated == ""

    def test_index_entry_full(self) -> None:
        ie = IndexEntry(
            path="p.md",
            kind="plan",
            tags=("x",),
            importance="high",
            summary="A plan",
            updated="2026-03-29",
        )
        assert ie.summary == "A plan"
        assert ie.tags == ("x",)


class TestKnowledgeIndex:
    def test_knowledge_index_default(self) -> None:
        idx = KnowledgeIndex()
        assert idx.version == 1
        assert idx.updated == ""
        assert idx.entries == ()

    def test_knowledge_index_with_entries(self) -> None:
        e = IndexEntry(path="a.md", kind="note")
        idx = KnowledgeIndex(entries=(e,))
        assert len(idx.entries) == 1


class TestChecklistItem:
    def test_checklist_item_default_not_done(self) -> None:
        item = ChecklistItem(text="Do something")
        assert item.text == "Do something"
        assert item.done is False
        assert item.tags == ()

    def test_checklist_item_done(self) -> None:
        item = ChecklistItem(text="Done task", done=True, tags=("release",))
        assert item.done is True
        assert item.tags == ("release",)


class TestQualityCriterion:
    def test_quality_criterion_default_not_met(self) -> None:
        qc = QualityCriterion(name="Coverage")
        assert qc.name == "Coverage"
        assert qc.description == ""
        assert qc.met is False
        assert qc.evidence == ""


class TestExperimentRecord:
    def test_experiment_record_default_pending(self) -> None:
        exp = ExperimentRecord(id="EXP-001", hypothesis="H1")
        assert exp.id == "EXP-001"
        assert exp.hypothesis == "H1"
        assert exp.method == ""
        assert exp.result == ""
        assert exp.outcome == "pending"
        assert exp.tags == ()

    def test_experiment_record_confirmed(self) -> None:
        exp = ExperimentRecord(
            id="EXP-002",
            hypothesis="H2",
            outcome="confirmed",
            tags=("ml",),
        )
        assert exp.outcome == "confirmed"


class TestLearnedPattern:
    def test_learned_pattern_default_pattern(self) -> None:
        lp = LearnedPattern(id="LP-001", pattern="Always validate input")
        assert lp.id == "LP-001"
        assert lp.pattern == "Always validate input"
        assert lp.context == ""
        assert lp.recommendation == ""
        assert lp.kind == "pattern"
        assert lp.tags == ()

    def test_learned_pattern_antipattern(self) -> None:
        lp = LearnedPattern(
            id="LP-002",
            pattern="God class",
            kind="antipattern",
            recommendation="Split by responsibility",
        )
        assert lp.kind == "antipattern"


class TestKnowledgeBankConfig:
    def test_knowledge_bank_config_defaults(self) -> None:
        cfg = KnowledgeBankConfig()
        assert cfg.enabled is False
        assert "STATUS.md" in cfg.core_documents
        assert "plan.md" in cfg.core_documents
        assert "checklist.md" in cfg.core_documents
        assert "plans" in cfg.directories
        assert "notes" in cfg.directories
        assert cfg.auto_index is True
        assert cfg.verification_enabled is False


ALL_TYPES = [
    DocumentMeta(kind="note"),
    KnowledgeEntry(path="a.md", meta=DocumentMeta(kind="note"), content="c"),
    IndexEntry(path="a.md", kind="note"),
    KnowledgeIndex(),
    ChecklistItem(text="t"),
    QualityCriterion(name="n"),
    ExperimentRecord(id="e", hypothesis="h"),
    LearnedPattern(id="l", pattern="p"),
    KnowledgeBankConfig(),
]


@pytest.mark.parametrize("instance", ALL_TYPES, ids=lambda x: type(x).__name__)
def test_all_types_frozen(instance: object) -> None:
    """All knowledge types must be frozen dataclasses."""
    assert dataclasses.is_dataclass(instance)
    fields = dataclasses.fields(instance)  # type: ignore[arg-type]
    assert len(fields) > 0
    first_field = fields[0].name
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(instance, first_field, "MUTATED")
