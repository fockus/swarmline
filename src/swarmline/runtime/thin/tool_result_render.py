"""How a tool result is rendered for the model (Sprint 1ce CE-24).

One rendering for every place a ReAct run hands a tool result back to the model:
the native path, the text-ReAct path, and a ``role="tool"`` message in a rebuilt
projection. Opt-in via ``native_config["data_provenance_enabled"]``: the result
goes inside a ``<data source="tool:<name>">`` envelope, so an instruction planted
in a tool's output reads as quoted data. Two things are harness text, not data,
and stay OUTSIDE the envelope:

- the tool-result offload marker (``scratch_read(key=...) to restore``) — moved
  into the envelope's ``note``; the omitted middle is shown as ``[...]``;
- results of tools named in ``native_config["data_provenance_harness_tools"]`` —
  receipts the host itself writes (e.g. a yield-model ``spawn_agent`` telling the
  model to finish its turn) render as before, unlabelled.

Without the flag every byte is what the loop rendered before.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from swarmline.context.data_envelope import wrap_data
from swarmline.runtime.thin.tool_result_offload import (
    OffloadOutcome,
    scratch_key_for_call,
    split_offload_projection,
)
from swarmline.runtime.types import Message

if TYPE_CHECKING:
    from swarmline.runtime.types import RuntimeConfig

DATA_PROVENANCE_KEY = "data_provenance_enabled"
HARNESS_TOOLS_KEY = "data_provenance_harness_tools"
OFFLOAD_KEY_METADATA = "offload_key"


def render_tool_result(
    name: str,
    content: str,
    *,
    labelled: bool,
    prefix: str = "Tool result from",
    restore_key: str | None = None,
) -> str:
    """``"<prefix> <name>: <content>"``, or a ``tool:<name>`` data envelope.

    ``restore_key`` is set only for a result that WAS offloaded; its marker then
    moves from the body into the envelope note. An empty result keeps the label.
    """
    if not (labelled and content):
        return f"{prefix} {name}: {content}"
    parts = split_offload_projection(content, restore_key) if restore_key else None
    if parts is None:
        return wrap_data(content, source=f"tool:{name}")
    head, marker, tail = parts
    body = f"{head}\n[...]\n{tail}" if tail else head
    note = marker.strip(" .\n")
    if tail:
        note = f"{note}; the omitted middle is marked [...]"
    return wrap_data(body, source=f"tool:{name}", note=note)


@dataclass(frozen=True)
class ToolResultRendering:
    """Per-run rendering settings, read once from ``native_config``."""

    labelled: bool = False
    harness_tools: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def from_config(cls, config: RuntimeConfig) -> ToolResultRendering:
        native = config.native_config
        if native.get(DATA_PROVENANCE_KEY) is not True:
            return cls()
        raw = native.get(HARNESS_TOOLS_KEY)
        names = raw if isinstance(raw, (list, tuple, set, frozenset)) else ()
        return cls(True, frozenset(n for n in names if isinstance(n, str)))

    def render(
        self,
        name: str,
        content: str,
        *,
        prefix: str = "Tool result from",
        restore_key: str | None = None,
    ) -> str:
        labelled = self.labelled and name not in self.harness_tools
        return render_tool_result(
            name, content, labelled=labelled, prefix=prefix, restore_key=restore_key
        )

    def restore_key(self, call_id: str, outcome: OffloadOutcome) -> str | None:
        """The scratch key of an offloaded result when labelling, else ``None``."""
        return (
            scratch_key_for_call(call_id)
            if self.labelled and outcome.offloaded
            else None
        )

    def tool_message(self, name: str, content: str, restore_key: str | None) -> Message:
        """Transcript message; carries the restore key so a rebuild renders it alike."""
        if restore_key:
            metadata = {OFFLOAD_KEY_METADATA: restore_key}
            return Message(role="tool", content=content, name=name, metadata=metadata)
        return Message(role="tool", content=content, name=name)


__all__ = [
    "DATA_PROVENANCE_KEY",
    "HARNESS_TOOLS_KEY",
    "OFFLOAD_KEY_METADATA",
    "ToolResultRendering",
    "render_tool_result",
]
