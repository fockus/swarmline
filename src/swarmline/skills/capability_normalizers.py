"""Source normalizers: map each capability source kind to a CapabilityDoc.

REQ-OSS-051: no tenant / workspace ids, no product coupling.
One normalizer per source kind:
  LocalToolNormalizer  — local Python tool (tool_name, description, schema)
  McpToolNormalizer    — MCP server + tool pair
  YamlSkillNormalizer  — YAML frontmatter + markdown body (SKILL.md / skill.yaml)
  WorkflowNormalizer   — workflow name, description, steps, tool list
"""

from __future__ import annotations

from typing import Any

from swarmline.skills.capability import CapabilityDoc, CapabilityKind, RiskLevel


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _list_of_str(value: object, *, default: tuple[str, ...] = ()) -> list[str]:
    """Coerce *value* to ``list[str]``, falling back to *default*."""
    if value is None:
        return list(default)
    if isinstance(value, str):
        return [value]
    if isinstance(value, list | tuple | set):
        return [str(item) for item in value]
    return list(default)


# ---------------------------------------------------------------------------
# Normalizers
# ---------------------------------------------------------------------------


class LocalToolNormalizer:
    """Normalizes a local Python tool into a CapabilityDoc(kind=TOOL).

    Stateless — no constructor arguments required. Subclass to override
    defaults such as ``runtime_allow`` or ``risk_level``.
    """

    def normalize(
        self,
        tool_name: str,
        description: str,
        input_schema: dict[str, object] | None = None,
    ) -> CapabilityDoc:
        """Map a local tool into a CapabilityDoc."""
        human_name = tool_name.replace("_", " ").title()
        return CapabilityDoc(
            capability_id=f"tool:{tool_name}",
            kind=CapabilityKind.TOOL,
            source="local",
            name=human_name,
            description=description,
            input_schema=input_schema or {},
            examples=[f"Use {tool_name} for {description.lower()}"],
            tags=[tool_name, "local"],
            required_capabilities=[],
            runtime_allow=["thin", "claude_sdk", "deepagents"],
            allowed_tools=[tool_name],
            risk_level=RiskLevel.LOW,
            cost_hint="cheap",
            latency_hint="fast",
            content_md=f"# {human_name}\n\n## Purpose\n{description}",
            enabled=True,
        )


class McpToolNormalizer:
    """Normalizes an MCP server + tool pair into a CapabilityDoc(kind=MCP).

    Stateless — no constructor arguments required. MCP tools require the
    ``mcp`` capability and are restricted to the ``claude_sdk`` runtime
    by default (the runtime that supports MCP servers natively).
    """

    def normalize(
        self,
        server_name: str,
        tool_name: str,
        description: str,
        input_schema: dict[str, object],
    ) -> CapabilityDoc:
        """Map an MCP tool into a CapabilityDoc."""
        capability_id = f"mcp:{server_name}.{tool_name}"
        human_name = f"{server_name} {tool_name}".replace("_", " ").title()
        return CapabilityDoc(
            capability_id=capability_id,
            kind=CapabilityKind.MCP,
            source=f"mcp:{server_name}",
            name=human_name,
            description=description,
            input_schema=input_schema,
            examples=[
                f"Call {server_name} {tool_name} when external API access is required"
            ],
            tags=[server_name, tool_name, "mcp"],
            required_capabilities=["mcp"],
            runtime_allow=["claude_sdk"],
            allowed_tools=[capability_id],
            risk_level=RiskLevel.MEDIUM,
            cost_hint="normal",
            latency_hint="normal",
            content_md=f"# {capability_id}\n\n## Purpose\n{description}",
            enabled=True,
            metadata={"server_name": server_name},
        )


class YamlSkillNormalizer:
    """Normalizes a YAML frontmatter dict + body string into a CapabilityDoc(kind=SKILL).

    Compatible with both the Swarmline native ``skill.yaml`` format and the
    Claude Code ``SKILL.md`` format (same field names, parsed externally).
    """

    def normalize(
        self,
        slug: str,
        frontmatter: dict[str, Any],
        body: str,
    ) -> CapabilityDoc:
        """Map parsed YAML frontmatter and body into a CapabilityDoc."""
        name = str(frontmatter.get("name", slug))
        description = str(frontmatter.get("description", slug))
        return CapabilityDoc(
            capability_id=f"skill:{slug}",
            kind=CapabilityKind.SKILL,
            source="yaml",
            name=name,
            description=description,
            input_schema=None,
            examples=_list_of_str(frontmatter.get("examples")),
            tags=_list_of_str(frontmatter.get("tags")),
            required_capabilities=_list_of_str(
                frontmatter.get("required-capabilities")
            ),
            runtime_allow=_list_of_str(
                frontmatter.get("runtime-allow"),
                default=("thin", "claude_sdk"),
            ),
            allowed_tools=_list_of_str(frontmatter.get("allowed-tools")),
            risk_level=RiskLevel(str(frontmatter.get("risk-level", "low"))),
            cost_hint=str(frontmatter.get("cost-hint", "cheap")),
            latency_hint=str(frontmatter.get("latency-hint", "fast")),
            content_md=body,
            enabled=True,
            roles_allow=_list_of_str(frontmatter.get("roles-allow")),
            metadata={"frontmatter": frontmatter},
        )


class WorkflowNormalizer:
    """Normalizes a workflow definition into a CapabilityDoc(kind=WORKFLOW).

    Stateless — no constructor arguments required.
    """

    def normalize(
        self,
        workflow_name: str,
        description: str,
        steps: list[str],
        tools: list[str],
    ) -> CapabilityDoc:
        """Map a workflow into a CapabilityDoc."""
        human_name = workflow_name.replace("-", " ").title()
        steps_md = "\n".join(f"- {step}" for step in steps) if steps else "- (no steps)"
        return CapabilityDoc(
            capability_id=f"workflow:{workflow_name}",
            kind=CapabilityKind.WORKFLOW,
            source="workflow",
            name=human_name,
            description=description,
            input_schema={
                "type": "object",
                "properties": {"task": {"type": "string"}},
            },
            examples=[description],
            tags=["workflow", workflow_name],
            required_capabilities=[],
            runtime_allow=["thin", "claude_sdk"],
            allowed_tools=list(tools),
            risk_level=RiskLevel.LOW,
            cost_hint="normal",
            latency_hint="normal",
            content_md=f"# {human_name}\n\n## Steps\n{steps_md}",
            enabled=True,
            metadata={"steps": steps},
        )
