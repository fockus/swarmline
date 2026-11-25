"""Unit: harness spec validation — REQ-003 comprehensive named-error rejection.

harness-composition spec, Task 5 (REQ-003, scenario 4). Written BEFORE the
implementation additions (TDD, RED first): before this task, ``build()``
already rejected an unknown top-level ``kernel``/``composition.mode``/
``infra`` flag (Task 2), but silently ignored an unknown ``HarnessSpec.preset``
reference and never checked a composition worker's OWN ``kernel`` — both
closed here. ``swarmline.harness.validation`` (a standalone validate-only
module) did not exist at all before this task.

Covers:
- ``test_unknown_kernel_or_preset_rejected_with_name`` (scenario 4,
  REQ-003) — the exact required test: unknown kernel/preset/composition/
  infra, each rejected by ``HarnessBuilder.from_spec(spec).build()`` with a
  named error.
- Worker-level kernel gap (REQ-003's literal "a composition spec references
  an unknown kernel" — a worker's kernel, not just the top-level one).
- I-056 regression: a YAML worker mapping missing ``role`` -> clear
  ``ValueError`` naming ``worker.role`` (was a raw ``KeyError``).
- I-057 (partial): an unknown key inside a ``composition``/``infra``/worker
  YAML mapping -> named ``ValueError``.
- ``validate_harness_spec`` — the standalone validate-only entry point,
  exercised directly (not just through ``build()``).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from swarmline.harness.builder import HarnessBuilder
from swarmline.harness.presets import PresetNotFound
from swarmline.harness.registries import CompositionBlockNotFound, InfraBlockNotFound
from swarmline.harness.spec import CompositionSpec, HarnessSpec, InfraSpec, WorkerSpec
from swarmline.harness.validation import validate_harness_spec
from swarmline.harness.yaml_loader import load_harness_yaml
from swarmline.runtime.thin.kernels import KernelNotFound


class TestUnknownKernelOrPresetRejectedWithName:
    """REQ-003 / scenario 4: the exact required test.

    Any unknown kernel/preset/composition-block/infra-block referenced in a
    spec is rejected by ``build()`` — the single funnel point every
    front-end (SDK/YAML/preset) resolves through — with an error naming the
    missing item.
    """

    def test_unknown_top_level_kernel_rejected_with_name(self) -> None:
        spec = HarnessSpec(kernel="definitely-not-a-registered-kernel")

        with pytest.raises(KernelNotFound) as exc_info:
            HarnessBuilder.from_spec(spec).build()

        assert "definitely-not-a-registered-kernel" in str(exc_info.value)

    def test_unknown_preset_referenced_on_spec_rejected_with_name(self) -> None:
        """A spec carrying an unknown ``preset`` name (e.g. as loaded from
        YAML ``{preset: <typo>}``) is rejected, not silently ignored."""
        spec = HarnessSpec(preset="definitely-not-a-registered-preset")

        with pytest.raises(PresetNotFound) as exc_info:
            HarnessBuilder.from_spec(spec).build()

        assert "definitely-not-a-registered-preset" in str(exc_info.value)

    def test_unknown_composition_mode_rejected_with_name(self) -> None:
        spec = HarnessSpec(
            composition=CompositionSpec(mode="definitely-not-a-registered-mode")
        )

        with pytest.raises(CompositionBlockNotFound) as exc_info:
            HarnessBuilder.from_spec(spec).build()

        assert "definitely-not-a-registered-mode" in str(exc_info.value)

    def test_unknown_infra_block_rejected_with_name(self) -> None:
        spec = HarnessSpec(infra=InfraSpec(checkpoint=True))

        with pytest.raises(InfraBlockNotFound) as exc_info:
            HarnessBuilder.from_spec(spec).build()

        assert "checkpoint" in str(exc_info.value)


class TestCompositionWorkerUnknownKernelRejected:
    """REQ-003's literal wording: "a composition spec references an unknown
    kernel" also covers a WORKER's own kernel, not just the top-level one.
    """

    def test_unknown_worker_kernel_rejected_with_name(self) -> None:
        spec = HarnessSpec(
            composition=CompositionSpec(
                mode="supervisor",
                workers=(
                    WorkerSpec(role="w1", kernel="definitely-not-a-worker-kernel"),
                ),
            )
        )

        # Stub the (not-yet-wired, I-052) composition registry so the mode
        # check does not raise first — isolates the worker-kernel check.
        with patch("swarmline.harness.builder.get_composition_registry"):
            with pytest.raises(KernelNotFound) as exc_info:
                HarnessBuilder.from_spec(spec).build()

        assert "definitely-not-a-worker-kernel" in str(exc_info.value)

    def test_valid_worker_kernel_does_not_raise_kernel_not_found(self) -> None:
        spec = HarnessSpec(
            composition=CompositionSpec(
                mode="supervisor", workers=(WorkerSpec(role="w1", kernel="react"),)
            )
        )

        # The composition block itself is still unwired (I-052) — that
        # error is expected; a *valid* worker kernel must not raise
        # KernelNotFound before reaching it.
        with pytest.raises(CompositionBlockNotFound):
            HarnessBuilder.from_spec(spec).build()


class TestValidateHarnessSpecStandaloneEntryPoint:
    """``validate_harness_spec`` performs the same checks WITHOUT building."""

    def test_valid_minimal_spec_does_not_raise(self) -> None:
        validate_harness_spec(HarnessSpec())

    def test_unknown_kernel_raises_without_constructing_agent(self) -> None:
        with pytest.raises(KernelNotFound):
            validate_harness_spec(HarnessSpec(kernel="not-a-kernel"))

    def test_unknown_preset_raises(self) -> None:
        with pytest.raises(PresetNotFound):
            validate_harness_spec(HarnessSpec(preset="not-a-preset"))

    def test_unknown_composition_mode_raises(self) -> None:
        with pytest.raises(CompositionBlockNotFound):
            validate_harness_spec(HarnessSpec(composition=CompositionSpec(mode="x")))

    def test_unknown_infra_block_raises(self) -> None:
        with pytest.raises(InfraBlockNotFound):
            validate_harness_spec(HarnessSpec(infra=InfraSpec(event_record=True)))

    def test_unknown_worker_kernel_raises(self) -> None:
        # validate_harness_spec imports get_composition_registry lazily
        # (inside the function body, from its origin module), so the patch
        # target is swarmline.harness.registries, not swarmline.harness.validation.
        with patch("swarmline.harness.registries.get_composition_registry"):
            with pytest.raises(KernelNotFound):
                validate_harness_spec(
                    HarnessSpec(
                        composition=CompositionSpec(
                            mode="supervisor",
                            workers=(WorkerSpec(role="w1", kernel="nope"),),
                        )
                    )
                )


class TestWorkerRoleMissingRaisesClearError:
    """I-056 regression: worker mapping missing ``role`` used to raw-``KeyError``."""

    def test_worker_mapping_missing_role_raises_value_error_naming_it(
        self, tmp_path
    ) -> None:
        yaml_path = tmp_path / "missing_role.yaml"
        yaml_path.write_text(
            "composition:\n"
            "  mode: supervisor\n"
            "  workers:\n"
            "    - kernel: react\n"  # no 'role' key
        )

        with pytest.raises(ValueError) as exc_info:
            load_harness_yaml(str(yaml_path))

        assert "worker.role" in str(exc_info.value)

    def test_worker_mapping_missing_role_is_not_a_bare_key_error(
        self, tmp_path
    ) -> None:
        """Guards the specific I-056 defect: NOT a raw KeyError."""
        yaml_path = tmp_path / "missing_role2.yaml"
        yaml_path.write_text(
            "composition:\n  mode: supervisor\n  workers:\n    - tools: [search]\n"
        )

        with pytest.raises(ValueError):
            load_harness_yaml(str(yaml_path))


class TestUnknownNestedKeyRejected:
    """I-057 (partial): a typo'd key inside composition/infra/worker mapping."""

    def test_unknown_key_in_composition_block_raises_named_error(
        self, tmp_path
    ) -> None:
        yaml_path = tmp_path / "bad_composition.yaml"
        yaml_path.write_text("composition:\n  mode: supervisor\n  typo_field: true\n")

        with pytest.raises(ValueError) as exc_info:
            load_harness_yaml(str(yaml_path))

        assert "typo_field" in str(exc_info.value)

    def test_unknown_key_in_worker_entry_raises_named_error(self, tmp_path) -> None:
        yaml_path = tmp_path / "bad_worker.yaml"
        yaml_path.write_text(
            "composition:\n"
            "  mode: supervisor\n"
            "  workers:\n"
            "    - role: researcher\n"
            "      typo_field: 1\n"
        )

        with pytest.raises(ValueError) as exc_info:
            load_harness_yaml(str(yaml_path))

        assert "typo_field" in str(exc_info.value)

    def test_unknown_key_in_infra_block_raises_named_error(self, tmp_path) -> None:
        yaml_path = tmp_path / "bad_infra.yaml"
        yaml_path.write_text("infra:\n  checkpoint: true\n  typo_field: 1\n")

        with pytest.raises(ValueError) as exc_info:
            load_harness_yaml(str(yaml_path))

        assert "typo_field" in str(exc_info.value)

    def test_known_keys_in_all_nested_mappings_still_load_fine(self, tmp_path) -> None:
        """Non-regression: every documented key across all 3 mappings still works."""
        yaml_path = tmp_path / "all_known.yaml"
        yaml_path.write_text(
            "composition:\n"
            "  mode: supervisor\n"
            "  blackboard: false\n"
            "  workers:\n"
            "    - role: researcher\n"
            "      kernel: react\n"
            "      tools: [search]\n"
            "infra:\n"
            "  checkpoint: true\n"
            "  event_record: true\n"
            "  replay: false\n"
        )

        spec = load_harness_yaml(str(yaml_path))

        assert spec.composition == CompositionSpec(
            mode="supervisor",
            blackboard=False,
            workers=(WorkerSpec(role="researcher", kernel="react", tools=("search",)),),
        )
        assert spec.infra == InfraSpec(checkpoint=True, event_record=True, replay=False)
