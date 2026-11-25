"""ContextBudget - management of context packet sizes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from swarmline.domain_types import ImageBlock

if TYPE_CHECKING:
    from swarmline.context.adaptive_budget import AdaptiveContextBudget
    from swarmline.domain_types import Message

#: Fallback context-window size (tokens) for callers with no better source for
#: the model's actual window -- e.g. CodingContextInputFilter's skill-listing
#: budget (Stage 3) and tool-result offload (Stage 4, context-engineering-
#: manus-parity). A SINGLE shared constant, so two call sites reading it via
#: their own differently-named native_config keys never independently drift
#: to two different literal defaults.
DEFAULT_CONTEXT_WINDOW_TOKENS: int = 200_000

#: Explicit mapping of every ``DefaultContextBuilder`` layer to one of the 6
#: ``AdaptiveContextBudget`` categories (``CATEGORIES`` in ``adaptive_budget.py``).
#: Part of the ``adaptive-budget`` spec, Task 3 (REQ-009). Task 4 (builder wiring)
#: uses this table to route two-pass allocation; Task 3 itself only defines it.
LAYER_TO_CATEGORY: dict[str, str] = {
    "guardrails": "system",  # P0: Guardrails (identity + guardrails)
    "role": "system",  # P0.5: Role
    "memory_bank": "memory",  # P_MEMORY: Memory Bank prompt + MEMORY.md
    "goal": "task",  # P1: Goal
    "phase": "task",  # P1.5: Phase
    "tool_hints": "tools",  # P2: Skill instructions (tool hints)
    "last_messages": "events",  # P2.5: Latest conversation messages
    "memory_recall": "memory",  # P3: Memory recall (cross-topic facts)
    "user_profile": "memory",  # P4: User profile
    "available_files": "memory",  # P4.5: Available Files (FileRegistry injection)
    "summary": "content",  # P5: Summary
}


@dataclass(frozen=True)
class ContextBudget:
    """Token budget for context packets.

    Priority (highest to lowest):
    P0: guardrails   - never dropped
    P1: active_goal  - truncate to goal_max if needed
    P2: tool hints   - keep only for active skills
    P3: memory recall - reduce top-k
    P4: user_profile  - truncate to key facts
    P5: summary      - dropped first
    """

    total_tokens: int = 8000
    guardrails_reserved: int = 1500  # P0: always reserved
    goal_max: int = 1000  # P1
    tools_max: int = 2000  # P2
    messages_max: int = 2000  # P2.5: latest conversation messages
    memory_max: int = 1500  # P3
    profile_max: int = 1000  # P4
    artifacts_max: int = 1500  # P4.5: Available Files (FileRegistry injection)
    summary_max: int = 1000  # P5
    #: Opt-in adaptive allocator (REQ-009/REQ-010). None (default) preserves the
    #: static per-layer caps above exactly as before; Task 4 wires the two-pass
    #: allocation when this is set. Storing only - never called from this module.
    adaptive: AdaptiveContextBudget | None = None


def estimate_tokens(text: str) -> int:
    """Rough token estimate (1 token ~ 4 characters for Russian/English)."""
    return len(text) // 4 + 1


#: Flat estimate of one image part. Providers bill an image by its pixel size
#: (Anthropic ~ w*h/750, capped near 1600 for a 1.15 MP image; OpenAI high detail
#: 765-1105 for a typical photo), and its base64 length says nothing about that --
#: so an image counts as this many tokens, never as its characters / 4.
IMAGE_TOKEN_ESTIMATE: int = 1600


def _is_image_block(block: Any) -> bool:
    if isinstance(block, ImageBlock):
        return True
    return isinstance(block, dict) and block.get("type") == "image"


def estimate_image_tokens(content_blocks: Any) -> int:
    """``IMAGE_TOKEN_ESTIMATE`` per image in ``content_blocks`` (``ImageBlock``s or their
    serialized dicts); text blocks are not counted -- they repeat the message ``content``."""
    if not isinstance(content_blocks, list):
        return 0
    return IMAGE_TOKEN_ESTIMATE * sum(1 for b in content_blocks if _is_image_block(b))


def estimate_message_tokens(message: Message) -> int:
    """Text estimate of ``message.content`` plus its image parts."""
    return estimate_tokens(message.content) + estimate_image_tokens(
        message.content_blocks
    )


def truncate_to_budget(text: str, max_tokens: int) -> str:
    """Truncate text to max_tokens (approximately)."""
    max_chars = max_tokens * 4
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n... [обрезано]"
