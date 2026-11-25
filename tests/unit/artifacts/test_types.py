"""Tests ArtifactType directory routing + Artifact/is_live classification - TDD."""

from __future__ import annotations

import pytest
from swarmline.artifacts.types import Artifact, ArtifactType, StepJournalEntry


class TestArtifactTypeClassification:
    @pytest.mark.parametrize(
        "artifact_type",
        [
            ArtifactType.GOAL,
            ArtifactType.PLAN,
            ArtifactType.TODO,
            ArtifactType.STATUS,
            ArtifactType.SOURCES,
            ArtifactType.CONSTRAINTS,
        ],
    )
    def test_live_types_report_is_live_true(self, artifact_type: ArtifactType) -> None:
        assert artifact_type.is_live() is True
        assert artifact_type.is_immutable() is False

    @pytest.mark.parametrize(
        "artifact_type",
        [
            ArtifactType.TOOL_OUTPUT,
            ArtifactType.STEP_NOTE,
            ArtifactType.CHART,
            ArtifactType.FINAL,
        ],
    )
    def test_immutable_types_report_is_immutable_true(
        self, artifact_type: ArtifactType
    ) -> None:
        assert artifact_type.is_immutable() is True
        assert artifact_type.is_live() is False


class TestArtifactTypeDirectoryRouting:
    @pytest.mark.parametrize(
        ("artifact_type", "expected_directory"),
        [
            (ArtifactType.GOAL, ""),
            (ArtifactType.TODO, ""),
            (ArtifactType.TOOL_OUTPUT, "tool_outputs"),
            (ArtifactType.STEP_NOTE, "notes"),
            (ArtifactType.WEB_SNAPSHOT, "snapshots/web"),
            (ArtifactType.RAW_DATA, "data/raw"),
            (ArtifactType.CLEAN_DATA, "data/clean"),
            (ArtifactType.CODE_SCRIPT, "code"),
            (ArtifactType.CODE_OUTPUT, "code/runs"),
            (ArtifactType.CHART, "charts"),
            (ArtifactType.DRAFT, "drafts"),
            (ArtifactType.FINAL, "final"),
        ],
    )
    def test_get_directory_routes_to_expected_subdirectory(
        self, artifact_type: ArtifactType, expected_directory: str
    ) -> None:
        assert artifact_type.get_directory() == expected_directory


class TestArtifact:
    def test_artifact_is_live_delegates_to_type(self, tmp_path) -> None:
        artifact = Artifact(
            id="a1", type=ArtifactType.GOAL, title="Goal", path=tmp_path / "goal.md"
        )

        assert artifact.is_live() is True
        assert artifact.is_immutable() is False

    def test_artifact_is_frozen(self, tmp_path) -> None:
        artifact = Artifact(
            id="a1", type=ArtifactType.FINAL, title="Report", path=tmp_path / "r.md"
        )

        with pytest.raises(AttributeError):
            artifact.title = "changed"  # type: ignore[misc]


class TestStepJournalEntryRoundtrip:
    def test_to_dict_from_dict_roundtrip_preserves_fields(self) -> None:
        entry = StepJournalEntry(
            step_id=1,
            task="do the thing",
            tool_name="workspace.write",
            tool_args={"filename": "notes/a.md"},
            status="ok",
            summary="wrote a note",
            raw_output_path="tool_outputs/step_001.json",
            artifacts_created=("art_1",),
            mutations=("todo.md",),
            notes_path="notes/step_001.md",
        )

        restored = StepJournalEntry.from_dict(entry.to_dict())

        assert restored.step_id == entry.step_id
        assert restored.task == entry.task
        assert restored.tool_args == entry.tool_args
        assert restored.artifacts_created == entry.artifacts_created
        assert restored.mutations == entry.mutations
        assert restored.notes_path == entry.notes_path
