"""Concrete in-memory channel adapter registry.

Generalised from:
    taskloom.infrastructure.channels.registry
    (src/taskloom/infrastructure/channels/registry.py)

The only change from the taskloom original is the removal of the
product-layer ``NotFoundError`` import — standard :exc:`KeyError` is used
instead so this module has zero external dependencies.
"""

from __future__ import annotations

from swarmline.channels.ports import ChannelAdapterPort


class ChannelRegistry:
    """Dict-backed registry mapping channel names to :class:`ChannelAdapterPort` instances.

    Satisfies :class:`~swarmline.channels.ports.ChannelRegistryPort` structurally.

    This is the default concrete implementation.  Swap it out via the
    :class:`~swarmline.channels.ports.ChannelRegistryPort` abstraction if you need
    persistence, discovery, or hot-reload behaviour.
    """

    def __init__(self) -> None:
        self._adapters: dict[str, ChannelAdapterPort] = {}

    def register(self, name: str, adapter: ChannelAdapterPort) -> None:
        """Register *adapter* under *name*, overwriting any previous entry."""
        self._adapters[name] = adapter

    def unregister(self, name: str) -> None:
        """Remove the adapter registered under *name*.

        Raises:
            KeyError: if *name* is not registered.
        """
        if name not in self._adapters:
            raise KeyError(name)
        del self._adapters[name]

    def get(self, name: str) -> ChannelAdapterPort:
        """Return the adapter registered under *name*.

        Raises:
            KeyError: if *name* is not registered.
        """
        if name not in self._adapters:
            raise KeyError(name)
        return self._adapters[name]

    def list_channels(self) -> list[str]:
        """Return a list of all currently registered channel names."""
        return list(self._adapters.keys())


__all__ = ["ChannelRegistry"]
