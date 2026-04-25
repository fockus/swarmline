"""Stage 5 (Sprint 1A): _hook_name helper for safe hook-name logging.

Background — `hooks/dispatcher.py` accesses `entry.callback.__name__` in 4
places (lines 106/158/194/207) when logging warnings about hooks that raised.
ty strict mode flags these as unresolved-attribute because `callback` may be a
`functools.partial` (or other non-`__name__`-bearing callable union).

Fix — extract a defensive helper:

    def _hook_name(hook: object) -> str:
        return getattr(hook, "__name__", repr(hook))

Replace all 4 inline `hook.__name__` accesses with `_hook_name(hook)`. Eliminates
4 ty errors and makes log output non-crashing for any callable shape.
"""

from __future__ import annotations

from functools import partial
from typing import Any

import pytest

from swarmline.hooks._helpers import _hook_name


def test_named_function_returns_qualname() -> None:
    """`_hook_name` returns `__name__` for normally-defined functions."""

    def foo() -> None:
        pass

    assert _hook_name(foo) == "foo"


async def test_async_named_function_returns_qualname() -> None:
    """Works for async functions (most common hook shape)."""

    async def my_hook() -> None:
        pass

    assert _hook_name(my_hook) == "my_hook"


def test_partial_falls_back_to_repr() -> None:
    """`functools.partial` has no `__name__` — must fall back to repr (not crash)."""

    def base(x: int, y: int) -> int:
        return x + y

    p = partial(base, x=1)
    name = _hook_name(p)
    # Partial repr typically contains "functools.partial" or class name; we just
    # need a non-empty string (no AttributeError)
    assert isinstance(name, str)
    assert len(name) > 0


def test_lambda_returns_lambda_name() -> None:
    """`lambda` has `__name__ == "<lambda>"` — preserved."""
    f = lambda x: x  # noqa: E731
    assert _hook_name(f) == "<lambda>"


def test_callable_class_returns_repr_or_class_name() -> None:
    """Instances of classes with `__call__` may not have `__name__` — repr fallback."""

    class HookCallable:
        def __call__(self) -> None:
            pass

    instance = HookCallable()
    name = _hook_name(instance)
    assert isinstance(name, str)
    assert len(name) > 0


@pytest.mark.parametrize(
    "value",
    [None, 42, "string", [1, 2, 3], {"key": "value"}],
    ids=["None", "int", "str", "list", "dict"],
)
def test_non_callable_inputs_do_not_crash(value: Any) -> None:
    """Defensive: even non-callable inputs (`None`, primitives) — repr fallback."""
    name = _hook_name(value)
    assert isinstance(name, str)
    # No AttributeError, no other exception


def test_dispatcher_uses_helper_not_inline_attribute_access() -> None:
    """Source-level invariant: dispatcher.py uses `_hook_name(...)` helper, not
    inline `<hook>.__name__`. Locks the Stage 5 fix from regressing.
    """
    import inspect

    from swarmline.hooks import dispatcher

    source = inspect.getsource(dispatcher)
    assert "_hook_name" in source, (
        "dispatcher.py must use _hook_name(...) helper. "
        "Direct .__name__ access would re-raise the 4 ty errors fixed in Stage 5."
    )
    # No occurrences of the bare pattern `entry.callback.__name__` should remain
    forbidden = "entry.callback.__name__"
    assert forbidden not in source, (
        f"dispatcher.py contains forbidden inline {forbidden!r}. "
        f"Replace with `_hook_name(entry.callback)`."
    )
