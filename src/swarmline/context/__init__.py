"""Context module - system_prompt assembly with budgeting."""

from swarmline.context.budget import ContextBudget, estimate_tokens, truncate_to_budget
from swarmline.context.builder import (
    BuiltContext,
    ContextInput,
    DefaultContextBuilder,
    compute_prompt_hash,
)

__all__ = [
    "BuiltContext",
    "ContextBudget",
    "ContextInput",
    "DefaultContextBuilder",
    "compute_prompt_hash",
    "estimate_tokens",
    "truncate_to_budget",
]
