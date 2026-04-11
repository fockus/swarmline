"""Persistent budget domain types — scopes, thresholds, incidents, cost events."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum


class BudgetWindow(str, Enum):
    """Time window for budget aggregation."""

    MONTHLY = "monthly"
    LIFETIME = "lifetime"


class BudgetScopeType(str, Enum):
    """Scope dimension for budget tracking."""

    AGENT = "agent"
    GRAPH = "graph"
    TENANT = "tenant"


@dataclass(frozen=True)
class BudgetScope:
    """Identifies a budget scope by type and id."""

    scope_type: BudgetScopeType
    scope_id: str


@dataclass(frozen=True)
class BudgetThreshold:
    """Budget limit configuration for a scope + window."""

    scope: BudgetScope
    window: BudgetWindow
    limit_usd: float
    warn_at_percent: float = 80.0
    hard_stop: bool = True


class ThresholdAction(str, Enum):
    """Action determined by threshold check."""

    OK = "ok"
    WARN = "warn"
    STOP = "stop"


@dataclass(frozen=True)
class ThresholdResult:
    """Result of checking a budget threshold."""

    scope: BudgetScope
    window: BudgetWindow
    usage_usd: float
    limit_usd: float
    percent: float
    action: ThresholdAction


@dataclass(frozen=True)
class BudgetIncident:
    """Recorded budget breach or warning incident."""

    id: str
    scope: BudgetScope
    window: BudgetWindow
    usage_usd: float
    limit_usd: float
    action: ThresholdAction
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class CostEvent:
    """A single recorded cost event within a budget scope."""

    id: str
    scope: BudgetScope
    amount_usd: float
    description: str = ""
    timestamp: float = field(default_factory=time.time)


def _generate_id() -> str:
    """Generate a short unique ID for budget records."""
    return uuid.uuid4().hex[:12]
