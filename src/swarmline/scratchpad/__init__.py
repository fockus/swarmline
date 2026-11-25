"""Scratchpad — ephemeral within-run working memory for Swarmline agents.

Providers:
    - :class:`~swarmline.scratchpad.inmemory_provider.InMemoryScratchpadProvider`
    - :class:`~swarmline.scratchpad.file_provider.FileScratchpadProvider`
    - :class:`~swarmline.scratchpad.openviking_provider.OpenVikingScratchpadProvider`

Isolation decorator:
    - :class:`~swarmline.scratchpad.namespaced_provider.NamespacedScratchpadProvider`
      — scopes a shared provider to a namespace (prefixes keys, filters
      list/search/delete), for hosts that share one backend across tenants/sessions.

Tool factory: :func:`~swarmline.scratchpad.tools.create_scratchpad_tools`.
"""

from __future__ import annotations

from swarmline.scratchpad.file_provider import FileScratchpadProvider
from swarmline.scratchpad.inmemory_provider import InMemoryScratchpadProvider
from swarmline.scratchpad.namespaced_provider import NamespacedScratchpadProvider
from swarmline.scratchpad.openviking_provider import ScratchpadWriteError
from swarmline.scratchpad.protocols import ScratchpadProvider
from swarmline.scratchpad.tools import create_scratchpad_tools
from swarmline.scratchpad.types import ScratchpadEntry

__all__ = [
    "FileScratchpadProvider",
    "InMemoryScratchpadProvider",
    "NamespacedScratchpadProvider",
    "ScratchpadEntry",
    "ScratchpadProvider",
    "ScratchpadWriteError",
    "create_scratchpad_tools",
]
