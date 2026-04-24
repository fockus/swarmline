"""Unit tests for AgentPackResolver."""

from __future__ import annotations

from pathlib import Path

import pytest

from swarmline.agent_pack import AgentPackResolver


def _write_pack(root: Path) -> Path:
    (root / "prompts" / "roles").mkdir(parents=True)
    (root / "skills" / "analysis").mkdir(parents=True)
    (root / "resources").mkdir()

    (root / "prompts" / "identity.md").write_text("Identity", encoding="utf-8")
    (root / "prompts" / "guardrails.md").write_text("Guardrails", encoding="utf-8")
    (root / "prompts" / "roles" / "analyst.md").write_text("Role", encoding="utf-8")
    (root / "skills" / "analysis" / "INSTRUCTION.md").write_text("Skill", encoding="utf-8")
    (root / "resources" / "rubric.md").write_text("Rubric", encoding="utf-8")
    (root / "prompts" / "service.md").write_text("Service", encoding="utf-8")

    manifest = root / "agent_pack.yaml"
    manifest.write_text(
        "\n".join(
            [
                "name: credit_report_agent",
                "identity: prompts/identity.md",
                "guardrails: prompts/guardrails.md",
                "role: prompts/roles/analyst.md",
                "skill: skills/analysis/INSTRUCTION.md",
                "services:",
                "  healing: prompts/service.md",
                "resources:",
                "  rubric: resources/rubric.md",
            ]
        ),
        encoding="utf-8",
    )
    return manifest


class TestAgentPackResolver:
    def test_resolves_legacy_manifest_layers_services_and_resources(self, tmp_path: Path) -> None:
        manifest_path = _write_pack(tmp_path)

        pack = AgentPackResolver(tmp_path).load(manifest_path)

        assert pack.name == "credit_report_agent"
        assert pack.layers["identity"].content == "Identity"
        assert pack.layers["guardrails"].content == "Guardrails"
        assert pack.layers["role"].content == "Role"
        assert pack.layers["skill"].content == "Skill"
        assert pack.services["healing"].content == "Service"
        assert pack.resources["rubric"].content == "Rubric"

    def test_render_prompt_preserves_layer_order_and_adds_service(self, tmp_path: Path) -> None:
        manifest_path = _write_pack(tmp_path)
        pack = AgentPackResolver(tmp_path).load(manifest_path)

        prompt = pack.render_prompt(service="healing")

        assert prompt.split("\n\n") == ["Identity", "Guardrails", "Role", "Skill", "Service"]

    def test_generic_layers_manifest_is_supported(self, tmp_path: Path) -> None:
        (tmp_path / "layers").mkdir()
        (tmp_path / "layers" / "base.md").write_text("Base", encoding="utf-8")
        (tmp_path / "layers" / "persona.md").write_text("Persona", encoding="utf-8")
        manifest = tmp_path / "agent_pack.yaml"
        manifest.write_text(
            "\n".join(
                [
                    "name: generic_agent",
                    "layers:",
                    "  base: layers/base.md",
                    "  persona: layers/persona.md",
                ]
            ),
            encoding="utf-8",
        )

        pack = AgentPackResolver(tmp_path).load(manifest)

        assert pack.layer_order == ("base", "persona")
        assert pack.render_prompt() == "Base\n\nPersona"

    def test_rejects_paths_outside_pack_root(self, tmp_path: Path) -> None:
        manifest = tmp_path / "agent_pack.yaml"
        manifest.write_text(
            "name: unsafe\nlayers:\n  base: ../outside.md\n",
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="outside agent pack root"):
            AgentPackResolver(tmp_path).load(manifest)
