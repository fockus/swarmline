"""Shared normalization helpers for memory providers."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Any

from cognitia.memory.types import GoalState, PhaseState


def json_dumps_or_none(value: Any) -> str | None:
    """Serialize a JSON payload or return None."""
    if value is None:
        return None
    return json.dumps(value)


def json_load_or_none(raw: Any) -> Any | None:
    """Deserialize a JSON payload when needed."""
    if raw in (None, ""):
        return None
    if isinstance(raw, dict | list):
        return raw
    try:
        return json.loads(str(raw))
    except (TypeError, json.JSONDecodeError):
        return None


def json_load_or_empty_list(raw: Any) -> list[str]:
    """Deserialize a JSON list or return an empty list."""
    parsed = json_load_or_none(raw)
    if isinstance(parsed, list):
        return [str(item) for item in parsed]
    return []


def json_load_value(raw: Any) -> Any:
    """Deserialize a JSON payload or preserve the raw value."""
    if raw is None:
        return None
    if isinstance(raw, dict | list | int | float | bool):
        return raw
    try:
        return json.loads(str(raw))
    except (TypeError, json.JSONDecodeError):
        return raw


def merge_scoped_facts(
    rows: Sequence[Any],
    *,
    value_loader: Callable[[Any], Any] = json_load_value,
) -> dict[str, Any]:
    """Merge global and scoped fact rows so scoped values override globals."""
    merged: dict[str, Any] = {}
    global_rows = [row for row in rows if getattr(row, "topic_id", None) is None]
    topic_rows = [row for row in rows if getattr(row, "topic_id", None) is not None]
    for row in global_rows + topic_rows:
        merged[str(row.key)] = value_loader(row.value)
    return merged


def build_goal_state(
    *,
    goal_id: Any,
    title: Any,
    target_amount: Any,
    current_amount: Any,
    phase: Any,
    plan: Any,
    is_main: Any,
    plan_loader: Callable[[Any], Any] = json_load_or_none,
) -> GoalState:
    """Normalize a database row into GoalState."""
    return GoalState(
        goal_id=str(goal_id),
        title=str(title),
        target_amount=int(target_amount) if target_amount is not None else None,
        current_amount=int(current_amount or 0),
        phase=str(phase or ""),
        plan=plan_loader(plan),
        is_main=bool(is_main),
    )


def build_session_state(
    *,
    role_id: Any,
    active_skill_ids: Any,
    title: Any,
    prompt_hash: Any,
    delegated_from: Any,
    delegation_turn_count: Any,
    pending_delegation: Any,
    delegation_summary: Any,
    skill_ids_loader: Callable[[Any], list[str]] = json_load_or_empty_list,
) -> dict[str, Any]:
    """Normalize a database row into the legacy session-state payload."""
    return {
        "role_id": str(role_id),
        "active_skill_ids": skill_ids_loader(active_skill_ids),
        "title": title,
        "prompt_hash": str(prompt_hash or ""),
        "delegated_from": delegated_from,
        "delegation_turn_count": int(delegation_turn_count or 0),
        "pending_delegation": pending_delegation,
        "delegation_summary": delegation_summary,
    }


def build_phase_state(*, user_id: str, phase: Any, notes: Any) -> PhaseState:
    """Normalize a phase-state row."""
    return PhaseState(
        user_id=user_id,
        phase=str(phase or ""),
        notes=str(notes or ""),
    )
