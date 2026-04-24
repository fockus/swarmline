"""Agent-pack manifest and resource resolver."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]


_LEGACY_LAYER_KEYS = ("identity", "guardrails", "role", "skill")


@dataclass(frozen=True)
class AgentPackResource:
    """Resolved text resource from an agent pack."""

    name: str
    path: Path
    content: str


@dataclass(frozen=True)
class ResolvedAgentPack:
    """Agent pack with all declared text resources loaded and validated."""

    name: str
    root: Path
    manifest_path: Path
    layers: Mapping[str, AgentPackResource]
    services: Mapping[str, AgentPackResource] = field(default_factory=dict)
    resources: Mapping[str, AgentPackResource] = field(default_factory=dict)
    layer_order: tuple[str, ...] = ()

    def render_prompt(self, *, service: str | None = None) -> str:
        """Render ordered layers, optionally followed by a service contract."""
        parts = [self.layers[name].content for name in self.layer_order]
        if service is not None:
            if service not in self.services:
                raise KeyError(f"Unknown agent pack service: {service}")
            parts.append(self.services[service].content)
        return "\n\n".join(part.strip() for part in parts if part.strip())


class AgentPackResolver:
    """Resolve agent-pack manifests relative to a project/package root.

    The resolver supports a generic manifest:

    ```yaml
    name: my_agent
    layers:
      identity: prompts/identity.md
      role: prompts/roles/analyst.md
    services:
      answer: prompts/answer.md
    resources:
      rubric: resources/rubric.md
    ```

    It also accepts the older flat keys used by existing projects:
    ``identity``, ``guardrails``, ``role`` and ``skill``.
    """

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).resolve()

    def load(self, manifest_path: str | Path = "agent_pack.yaml") -> ResolvedAgentPack:
        """Load and resolve an agent-pack manifest."""
        manifest = self._resolve_path(manifest_path)
        raw = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError("agent pack manifest must be a mapping")

        name = str(raw.get("name", "")).strip()
        if not name:
            raise ValueError("agent pack manifest requires non-empty 'name'")

        layer_refs, layer_order = self._collect_layer_refs(raw)
        service_refs = _as_mapping(raw.get("services", {}), field_name="services")
        resource_refs = _as_mapping(raw.get("resources", {}), field_name="resources")

        return ResolvedAgentPack(
            name=name,
            root=self._root,
            manifest_path=manifest,
            layers=self._resolve_resource_map(layer_refs),
            services=self._resolve_resource_map(service_refs),
            resources=self._resolve_resource_map(resource_refs),
            layer_order=layer_order,
        )

    def _collect_layer_refs(self, raw: dict[str, Any]) -> tuple[dict[str, str], tuple[str, ...]]:
        generic_layers = raw.get("layers")
        if generic_layers is not None:
            layers = _as_mapping(generic_layers, field_name="layers")
            return layers, tuple(layers)

        layers = {
            key: str(raw[key])
            for key in _LEGACY_LAYER_KEYS
            if raw.get(key) is not None
        }
        if not layers:
            raise ValueError("agent pack manifest requires 'layers' or legacy layer keys")
        return layers, tuple(key for key in _LEGACY_LAYER_KEYS if key in layers)

    def _resolve_resource_map(
        self,
        refs: Mapping[str, str],
    ) -> dict[str, AgentPackResource]:
        return {
            name: self._read_resource(name, relative_path)
            for name, relative_path in refs.items()
        }

    def _read_resource(self, name: str, relative_path: str) -> AgentPackResource:
        path = self._resolve_path(relative_path)
        if not path.is_file():
            raise FileNotFoundError(f"agent pack resource does not exist: {relative_path}")
        return AgentPackResource(
            name=name,
            path=path,
            content=path.read_text(encoding="utf-8").strip(),
        )

    def _resolve_path(self, path: str | Path) -> Path:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self._root / candidate
        if candidate.is_symlink():
            raise ValueError(f"agent pack path must not be a symlink: {path}")
        resolved = candidate.resolve()
        if not resolved.is_relative_to(self._root):
            raise ValueError(f"agent pack path is outside agent pack root: {path}")
        return resolved


def _as_mapping(value: Any, *, field_name: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError(f"agent pack '{field_name}' must be a mapping")
    return {str(key): str(item) for key, item in value.items()}
