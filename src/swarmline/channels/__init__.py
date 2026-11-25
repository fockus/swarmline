"""swarmline.channels — generic channel abstraction (OSS-T6).

Provides framework-agnostic ports and envelopes for building channel adapters.
Product-specific transports (Telegram, Lobu/web, etc.) live in the product
layer; only the contracts and the in-memory registry are shipped here.

Usage::

    from swarmline.channels import (
        ChannelAdapterPort,
        ChannelRegistry,
        ChannelRegistryPort,
        GatewayPort,
        IncomingMessage,
        OutgoingMessage,
    )

    class MyAdapter:
        async def normalize(self, raw):  ...
        async def send(self, msg): ...
        async def healthcheck(self): ...

    registry = ChannelRegistry()
    registry.register("my_channel", MyAdapter())

Zero product coupling:  no taskloom / tenant / workspace / FastAPI /
SQLAlchemy / Lobu types are referenced anywhere in this subpackage.
"""

from swarmline.channels.envelopes import IncomingMessage, OutgoingMessage
from swarmline.channels.ports import (
    ChannelAdapterPort,
    ChannelRegistryPort,
    GatewayPort,
)
from swarmline.channels.registry import ChannelRegistry

__all__ = [
    "ChannelAdapterPort",
    "ChannelRegistry",
    "ChannelRegistryPort",
    "GatewayPort",
    "IncomingMessage",
    "OutgoingMessage",
]
