"""YAML frontmatter parser and serializer for knowledge documents.

Supports the standard markdown frontmatter format::

    ---
    kind: note
    tags: [tag1, tag2]
    importance: high
    ---
    Content body here...
"""

from __future__ import annotations

from typing import Any

import yaml

from swarmline.memory_bank.knowledge_types import DocumentMeta

_KNOWN_KEYS = frozenset(("kind", "tags", "importance", "created", "updated", "related"))


def parse_frontmatter(text: str) -> tuple[DocumentMeta | None, str]:
    """Parse YAML frontmatter from markdown text.

    Returns (meta, body). If no frontmatter found, returns (None, original_text).
    """
    if not text.startswith("---"):
        return None, text

    end = text.find("---", 3)
    if end == -1:
        return None, text

    yaml_str = text[3:end].strip()
    body = text[end + 3 :].strip()

    try:
        data = yaml.safe_load(yaml_str) or {}
    except yaml.YAMLError:
        return None, text

    if not isinstance(data, dict):
        return None, text

    meta = DocumentMeta(
        kind=data.get("kind", "note"),
        tags=tuple(data.get("tags", ())),
        importance=data.get("importance", "medium"),
        created=str(data.get("created", "")),
        updated=str(data.get("updated", "")),
        related=tuple(data.get("related", ())),
        custom={k: v for k, v in data.items() if k not in _KNOWN_KEYS},
    )
    return meta, body


def render_frontmatter(meta: DocumentMeta, body: str) -> str:
    """Render a document with YAML frontmatter."""
    data: dict[str, Any] = {"kind": meta.kind}
    if meta.tags:
        data["tags"] = list(meta.tags)
    if meta.importance != "medium":
        data["importance"] = meta.importance
    if meta.created:
        data["created"] = meta.created
    if meta.updated:
        data["updated"] = meta.updated
    if meta.related:
        data["related"] = list(meta.related)
    if meta.custom:
        data.update(meta.custom)

    yaml_str = yaml.dump(data, default_flow_style=False, allow_unicode=True).strip()
    return f"---\n{yaml_str}\n---\n\n{body}"
