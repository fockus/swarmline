"""swarmline.runtime.fallback — provider fallback chain, error taxonomy, and cascade resolver.

Public API re-exported from sub-modules:
  _types    — RemediationAction, ClassifiedError, FallbackEntry, FallbackChain
  _cooldown — CooldownStatePort, InMemoryCooldownState
  _resolver — FallbackResolver
"""

from __future__ import annotations

from swarmline.runtime.fallback._cooldown import (
    CooldownStatePort,
    InMemoryCooldownState,
)
from swarmline.runtime.fallback._resolver import FallbackResolver
from swarmline.runtime.fallback._types import (
    ClassifiedError,
    FallbackChain,
    FallbackEntry,
    RemediationAction,
)

__all__ = [
    "RemediationAction",
    "ClassifiedError",
    "FallbackEntry",
    "FallbackChain",
    "CooldownStatePort",
    "InMemoryCooldownState",
    "FallbackResolver",
]
