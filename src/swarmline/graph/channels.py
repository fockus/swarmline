"""State channels and reducers for the native Graph DSL (Epic D, Stage D1.1).

LangGraph-style channel primitives: a `Reducer` folds an `update` into the
`current` channel value. `replace` (last-writer-wins) is the default for any
channel not explicitly declared in a `StateSchema`. `add` accumulates via the
channel's natural `+` operator (lists concat, numbers sum, strings concat).
`add_messages` is the message-list specialization: append, or replace in
place when an incoming message's `"id"` matches an existing one.

Stdlib-only — no framework or `swarmline.pipeline` dependency.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

Reducer = Callable[[Any, Any], Any]


def replace(current: Any, update: Any) -> Any:
    """Last-writer-wins: the update always overwrites the current value."""
    return update


def add(current: Any, update: Any) -> Any:
    """Accumulate `update` onto `current` via `+` (lists/numbers/strings).

    When `current` is `None` (channel not yet written), `update` is returned
    as-is — the caller (`init_state`) is responsible for seeding `current`
    from the channel's `default_factory()` before the first `apply_update`.
    Incompatible operand types raise `TypeError` naturally; it is never
    swallowed or silently downgraded to `replace`.
    """
    if current is None:
        return update
    return current + update


def add_messages(current: list[Any], update: Any) -> list[Any]:
    """Append `update` (one message or a list of messages) to `current`.

    A message that is a `Mapping` carrying an `"id"` matching an existing
    message's `"id"` replaces that message in place (list length unchanged)
    instead of being appended.
    """
    incoming: Sequence[Any] = update if isinstance(update, list) else [update]
    result = list(current)
    for message in incoming:
        message_id = message.get("id") if isinstance(message, Mapping) else None
        replaced = False
        if message_id is not None:
            for index, existing in enumerate(result):
                if isinstance(existing, Mapping) and existing.get("id") == message_id:
                    result[index] = message
                    replaced = True
                    break
        if not replaced:
            result.append(message)
    return result


@dataclass(frozen=True)
class Channel:
    """Declares how a single state key merges concurrent/sequential updates."""

    reducer: Reducer = replace
    default_factory: Callable[[], Any] | None = None


StateSchema = Mapping[str, "Channel"]


def init_state(schema: StateSchema) -> dict[str, Any]:
    """Seed a fresh state dict from each declared channel's `default_factory`.

    Channels without a `default_factory` are absent from the seeded dict
    (they are populated lazily on first `apply_update`).
    """
    state: dict[str, Any] = {}
    for key, channel in schema.items():
        if channel.default_factory is not None:
            state[key] = channel.default_factory()
    return state


def apply_update(
    state: dict[str, Any], update: Mapping[str, Any], schema: StateSchema
) -> dict[str, Any]:
    """Fold `update` into `state` through each key's declared reducer.

    Returns a NEW dict; `state` is never mutated. Keys undeclared in
    `schema` fall back to the `replace` reducer.
    """
    new_state = dict(state)
    for key, value in update.items():
        channel = schema.get(key)
        reducer = channel.reducer if channel is not None else replace
        new_state[key] = reducer(new_state.get(key), value)
    return new_state


__all__ = [
    "Channel",
    "Reducer",
    "StateSchema",
    "add",
    "add_messages",
    "apply_update",
    "init_state",
    "replace",
]
