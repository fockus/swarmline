"""Hooks module - agent event interception."""

from __future__ import annotations

from importlib import import_module
from typing import Any

from swarmline.hooks.registry import HookCallback, HookEntry, HookRegistry

__all__ = ["HookCallback", "HookEntry", "HookRegistry"]


def __getattr__(name: str) -> Any:
    if name != "registry_to_sdk_hooks":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    try:
        module = import_module("swarmline.hooks.sdk_bridge")
        value = getattr(module, name)
    except (ImportError, AttributeError) as exc:
        raise ImportError(
            "registry_to_sdk_hooks is unavailable. Install claude-agent-sdk to use SDK hooks."
        ) from exc

    globals()[name] = value
    return value
