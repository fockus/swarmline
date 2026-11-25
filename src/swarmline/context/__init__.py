"""Context module - system_prompt assembly with budgeting.

Runtime context contracts (REQ-ORC-090/091/092)
-------------------------------------------------
The following three contracts are guaranteed swarmline runtime contracts for
every agent, at any nesting depth (Manus-style context-engineering rules
1-3, adapted to swarmline):

1. **Append-only context + stable prefix** (REQ-ORC-090) —
   ``append_only`` never mutates or reorders prior history; ``build_stable_prefix``
   is byte-identical for identical inputs, maximising KV-cache reuse.
2. **Tool masking** (REQ-ORC-091) — ``mask_tools`` soft-disables tools
   outside the allowed set (keeps every entry, flips ``enabled=False``)
   instead of adding/removing them, preserving the stable prefix.
3. **Artifact-ref** (REQ-ORC-092) — ``ArtifactStore`` + ``to_artifact_ref``
   replace a large output with a short, restorable reference so the
   orchestrator holds a pointer, never the full transcript.

Manus rules 4-6 (context-engineering-manus-parity, Stages 4/5/6):
4. filesystem-as-context — ``runtime/thin/tool_result_offload.py`` (Stage 4:
   large tool results offloaded to a ``ScratchpadProvider``, restorable
   head+tail projection kept inline).
5. recitation / todo-attention — ``RecitationInputFilter`` below (Stage 5:
   plan/todo re-injected at the tail of ``messages`` by human-turn cadence).
6. keep-errors-in-context — ``swarmline.compaction.ConversationCompactionFilter``
   (Stage 6: cheap-before-expensive cascade — no-LLM dedup/templates, the
   existing weak-model tier, then a structured summary that keeps errors
   VERBATIM as a fixed section; safe-fail abort/local-fallback + anti-
   thrashing cooldown so a flaky summarizer never silently drops context).

Data envelope (Sprint 1ce CE-15/19, CE-24): ``wrap_data`` renders quoted data
(compaction summaries today; tool results, memory, sub-agent replies next) in a
deterministic ``<data source="...">`` block the model reads but never obeys.
"""

from swarmline.context.artifact_ref import ArtifactStore, to_artifact_ref
from swarmline.context.budget import (
    DEFAULT_CONTEXT_WINDOW_TOKENS,
    IMAGE_TOKEN_ESTIMATE,
    ContextBudget,
    estimate_image_tokens,
    estimate_message_tokens,
    estimate_tokens,
    truncate_to_budget,
)
from swarmline.context.data_envelope import wrap_data
from swarmline.context.builder import (
    BuiltContext,
    ContextInput,
    DefaultContextBuilder,
    compute_prompt_hash,
)
from swarmline.context.prompt_caching import (
    build_cached_system,
    mark_last_message_breakpoints,
)
from swarmline.context.recitation_input_filter import (
    RECITATION_CADENCE,
    RecitationInputFilter,
    count_human_turns,
    should_recite,
)
from swarmline.context.stable_prefix import append_only, build_stable_prefix, mask_tools

__all__ = [
    "DEFAULT_CONTEXT_WINDOW_TOKENS",
    "IMAGE_TOKEN_ESTIMATE",
    "RECITATION_CADENCE",
    "ArtifactStore",
    "BuiltContext",
    "ContextBudget",
    "ContextInput",
    "DefaultContextBuilder",
    "RecitationInputFilter",
    "append_only",
    "build_cached_system",
    "build_stable_prefix",
    "compute_prompt_hash",
    "count_human_turns",
    "estimate_image_tokens",
    "estimate_message_tokens",
    "estimate_tokens",
    "mark_last_message_breakpoints",
    "mask_tools",
    "should_recite",
    "to_artifact_ref",
    "truncate_to_budget",
    "wrap_data",
]
