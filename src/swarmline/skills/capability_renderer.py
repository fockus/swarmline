"""SkillMarkdownRenderer — renders a CapabilityDoc to SKILL.md format.

Produces valid YAML frontmatter followed by a Markdown body.
The output is round-trippable: parse the frontmatter back with
``yaml.safe_load`` and all key fields are recoverable.
"""

from __future__ import annotations

import yaml

from swarmline.skills.capability import CapabilityDoc


class SkillMarkdownRenderer:
    """Renders a CapabilityDoc to SKILL.md (YAML frontmatter + Markdown body).

    Round-trip guarantee: ``render(doc)`` produces a string whose YAML
    frontmatter block, when parsed with ``yaml.safe_load``, reproduces
    the original field values for: name, description, kind, tags,
    allowed-tools, required-capabilities, risk-level, cost-hint,
    and latency-hint.
    """

    def render(self, capability: CapabilityDoc) -> str:
        """Produce SKILL.md text for the given capability."""
        frontmatter_data: dict[str, object] = {
            "name": capability.name,
            "description": capability.description,
            "kind": capability.kind.value,
            "tags": list(capability.tags),
            "allowed-tools": list(capability.allowed_tools),
            "required-capabilities": list(capability.required_capabilities),
            "risk-level": capability.risk_level.value,
            "cost-hint": capability.cost_hint,
            "latency-hint": capability.latency_hint,
        }
        if capability.roles_allow:
            frontmatter_data["roles-allow"] = list(capability.roles_allow)

        frontmatter_str = yaml.dump(
            frontmatter_data,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=True,
        )

        body = (
            capability.content_md.strip()
            if capability.content_md.strip()
            else self._default_body(capability)
        )

        sections = [
            "---",
            frontmatter_str.rstrip(),
            "---",
            "",
            body,
            "",
            "## When to use",
        ]

        if capability.examples:
            sections.extend(f"- {ex}" for ex in capability.examples)
        else:
            sections.append("- When the task matches the description")

        sections += [
            "",
            "## Do not use",
            "- When runtime requirements are unavailable",
            "",
            "## Limitations",
            "- Respect capability policy and runtime constraints",
        ]

        return "\n".join(sections)

    @staticmethod
    def _default_body(capability: CapabilityDoc) -> str:
        return f"# {capability.name}\n\n## Purpose\n{capability.description}"
