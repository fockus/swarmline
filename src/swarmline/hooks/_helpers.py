"""Internal helpers for hook dispatch — kept private (single underscore).

`_hook_name` — defensive name-extraction for any callable shape. Used by the
hook dispatcher when logging warnings about hooks that raised exceptions: hook
callbacks may be `functools.partial`, `lambda`, or class instances with
`__call__`, none of which carry `__name__` in a type-system-visible way.

Without this helper, `hook.__name__` accesses leak `unresolved-attribute`
errors under `ty` strict mode and risk `AttributeError` at runtime when the
caller registered a `partial(...)` hook.
"""

from __future__ import annotations


def _hook_name(hook: object) -> str:
    """Best-effort name for any callable; safe for partial / lambda / class instances.

    Args:
        hook: Any object (callable or otherwise). Hook entries normally hold a
            callable, but the helper accepts arbitrary input to stay defensive
            inside log statements (where raising a second exception would mask
            the original failure being logged).

    Returns:
        `hook.__name__` if available; otherwise `repr(hook)`. Always a string.

    Examples:
        >>> async def my_hook(): ...
        >>> _hook_name(my_hook)
        'my_hook'

        >>> from functools import partial
        >>> def base(x, y): ...
        >>> _hook_name(partial(base, x=1))  # repr-like; not 'base'
        'functools.partial(...)'  # actual repr varies by Python version
    """
    return getattr(hook, "__name__", repr(hook))
