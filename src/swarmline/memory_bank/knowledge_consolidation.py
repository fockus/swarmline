"""Knowledge consolidation -- convert episodic memory to knowledge entries."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from swarmline.memory_bank.knowledge_types import DocumentMeta, KnowledgeEntry


@dataclass(frozen=True)
class ConsolidationResult:
    """Result of knowledge consolidation."""

    entries_created: int
    episodes_processed: int
    patterns_found: int


class KnowledgeConsolidator:
    """Convert episodes to knowledge entries with structured metadata.

    Domain-agnostic: works with any Episode-like objects that have
    summary, key_decisions, tags, tools_used fields.
    """

    def consolidate(
        self,
        episodes: list[Any],
        *,
        min_episodes: int = 3,
    ) -> list[KnowledgeEntry]:
        """Convert episodes to knowledge entries.

        Groups episodes by common tags/tools, creates a knowledge note
        for each group that appears >= min_episodes times.
        """
        if not episodes:
            return []

        tag_groups: dict[str, list[Any]] = {}
        for ep in episodes:
            for tag in getattr(ep, "tags", ()):
                tag_groups.setdefault(tag, []).append(ep)

        entries: list[KnowledgeEntry] = []
        seen_tags: set[str] = set()

        for tag, eps in sorted(tag_groups.items(), key=lambda x: -len(x[1])):
            if len(eps) < min_episodes:
                continue
            if tag in seen_tags:
                continue
            seen_tags.add(tag)

            summaries = [getattr(ep, "summary", "") for ep in eps[:5]]
            decisions: list[str] = []
            for ep in eps[:5]:
                for d in getattr(ep, "key_decisions", []):
                    if d not in decisions:
                        decisions.append(d)

            tools: set[str] = set()
            for ep in eps:
                for t in getattr(ep, "tools_used", []):
                    tools.add(t)

            content_parts = [
                f"Consolidated from {len(eps)} episodes about '{tag}'.",
                "",
                "## Key Observations",
            ]
            for s in summaries:
                if s:
                    content_parts.append(f"- {s}")

            if decisions:
                content_parts.append("")
                content_parts.append("## Key Decisions")
                for d in decisions[:10]:
                    content_parts.append(f"- {d}")

            if tools:
                content_parts.append("")
                content_parts.append(f"## Tools Used: {', '.join(sorted(tools))}")

            content = "\n".join(content_parts)
            now = time.strftime("%Y-%m-%d")
            path = f"notes/{now}_{tag.replace(' ', '-').lower()}.md"

            entries.append(
                KnowledgeEntry(
                    path=path,
                    meta=DocumentMeta(
                        kind="note",
                        tags=(tag,) + tuple(sorted(tools)[:3]),
                        importance="medium",
                        created=now,
                        updated=now,
                    ),
                    content=content,
                    size_bytes=len(content.encode("utf-8")),
                )
            )

        return entries
