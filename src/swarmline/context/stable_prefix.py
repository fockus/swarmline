"""swarmline-native context primitives — REQ-OSS-060, REQ-ORC-090.

Provides deterministic KV-cache prefix construction, soft tool masking, and
an append-only history helper (Contract 1, REQ-ORC-090). Foundation for
cache_control + assembly order. Zero product coupling: all functions operate
only on str/dict/list/tuple — no taskloom types imported.
"""

from __future__ import annotations

import hashlib
import json
from typing import TypeVar, cast

_HistoryItemT = TypeVar("_HistoryItemT")


def build_stable_prefix(system_prompt: str, user_context: str) -> str:
    """Build a deterministic prefix string for KV-cache stability.

    Identical inputs always produce identical output, maximising cache hit
    rate across agent turns.  The hash covers both fields via a canonical
    JSON serialisation (sort_keys=True, ensure_ascii=True) so key ordering
    in the source dict cannot affect the digest.

    Args:
        system_prompt: The agent system prompt text.
        user_context: Caller-supplied context string.

    Returns:
        A stable string of the form::

            [PREFIX:<16-hex-hash>]<system_prompt>\\n---\\n<user_context>
    """
    raw = json.dumps(
        {"system_prompt": system_prompt, "user_context": user_context},
        sort_keys=True,
        ensure_ascii=True,
    )
    content_hash = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return f"[PREFIX:{content_hash}]{system_prompt}\n---\n{user_context}"


def mask_tools(
    context: dict[str, object], allowed_tools: list[str]
) -> dict[str, object]:
    """Soft-disable tools not in *allowed_tools* without removing them.

    Every tool in the ``"tools"`` list is replaced with a minimal descriptor
    ``{"name": <name>, "enabled": <bool>}``.  Tools absent from
    *allowed_tools* have ``enabled=False``; those present have
    ``enabled=True``.

    The original *context* dict and its nested structures are never mutated;
    a new dict is always returned.

    If the context has no ``"tools"`` key, or if its value is not a
    ``list``, a shallow copy of *context* is returned unchanged.

    Name extraction rules (applied in order):

    - ``str`` tool  — name is the string itself.
    - ``dict`` tool — ``str(tool.get("name", tool))``
    - anything else — ``str(tool)``

    Args:
        context: Agent context dict (read-only).
        allowed_tools: Names of tools that should be enabled.

    Returns:
        New dict with tools replaced by ``{"name": ..., "enabled": bool}``
        descriptors, or a shallow copy of *context* when no masking applies.
    """
    if "tools" not in context:
        return dict(context)

    tools_raw = context["tools"]
    if not isinstance(tools_raw, list):
        return dict(context)

    allowed_set: set[str] = set(allowed_tools)
    masked: list[dict[str, object]] = []
    for tool in tools_raw:
        if isinstance(tool, str):
            name: str = tool
        elif isinstance(tool, dict):
            # ty narrows dict elements from object-typed lists to dict[Never,Never].
            # Cast to the expected shape so .get() resolves correctly.
            tool_d = cast("dict[str, object]", tool)
            name_val: object = tool_d.get("name")
            name = str(name_val) if "name" in tool_d else str(tool_d)
        else:
            name = str(tool)

        masked.append({"name": name, "enabled": name in allowed_set})

    result = dict(context)
    result["tools"] = masked
    return result


def append_only(
    history: tuple[_HistoryItemT, ...], *events: _HistoryItemT
) -> tuple[_HistoryItemT, ...]:
    """Append *events* to *history* without mutating or reordering it.

    Contract 1 (REQ-ORC-090): agent history is append-only. This is a pure
    function — *history* is never mutated in place, and prior entries keep
    their original order; a new tuple is always returned.

    Args:
        history: The existing, immutable history tuple.
        *events: One or more new events to append, in order.

    Returns:
        A new tuple equal to ``history + events``.
    """
    return history + events
