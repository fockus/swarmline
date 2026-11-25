"""Tests for swarmline.channels — generic channel abstraction (OSS-T6).

Generalised from:
- taskloom.shared.channel               (IncomingMessage, OutgoingMessage)
  src/taskloom/shared/channel.py
- taskloom.application.ports.integrations  (ChannelAdapterPort, ChannelRegistryPort, GatewayPort)
  src/taskloom/application/ports/integrations.py:55-88
- taskloom.infrastructure.channels.registry  (ChannelRegistry)
  src/taskloom/infrastructure/channels/registry.py
"""

from __future__ import annotations

import ast
import importlib
import inspect
import pkgutil

import pytest

import swarmline.channels as channels_pkg
from swarmline.channels import (
    ChannelAdapterPort,
    ChannelRegistry,
    ChannelRegistryPort,
    GatewayPort,
    IncomingMessage,
    OutgoingMessage,
)


# ---------------------------------------------------------------------------
# Fake adapter — minimal in-memory implementation of ChannelAdapterPort
# ---------------------------------------------------------------------------


class FakeChannelAdapter:
    """In-memory stub used across multiple test classes."""

    def __init__(self, channel_name: str) -> None:
        self._channel_name = channel_name
        self.sent: list[OutgoingMessage] = []

    async def normalize(self, raw: dict[str, object]) -> IncomingMessage:
        return IncomingMessage(
            channel_id=self._channel_name,
            sender_id=str(raw.get("sender_id", "anon")),
            content=str(raw.get("content", raw.get("text", ""))),
            conversation_id=(
                str(raw["conversation_id"]) if raw.get("conversation_id") else None
            ),
            thread_id=str(raw["thread_id"]) if raw.get("thread_id") else None,
            metadata={"raw": raw},
        )

    async def send(self, msg: OutgoingMessage) -> dict[str, object]:
        self.sent.append(msg)
        return {"status": "sent", "channel": self._channel_name}

    async def healthcheck(self) -> dict[str, object]:
        return {"channel": self._channel_name, "status": "ok"}


class FakeGateway:
    """Minimal stub that satisfies GatewayPort structurally."""

    async def dispatch_event(self, event: IncomingMessage) -> dict[str, object]:
        return {"dispatched": True, "channel_id": event.channel_id}


# ---------------------------------------------------------------------------
# ChannelRegistry tests
# ---------------------------------------------------------------------------


class TestChannelRegistry:
    def test_register_and_get_adapter_returns_same_instance(self) -> None:
        # Arrange
        registry = ChannelRegistry()
        adapter = FakeChannelAdapter("telegram")
        # Act
        registry.register("telegram", adapter)
        result = registry.get("telegram")
        # Assert
        assert result is adapter

    def test_list_channels_returns_all_registered_names(self) -> None:
        # Arrange
        registry = ChannelRegistry()
        registry.register("telegram", FakeChannelAdapter("telegram"))
        registry.register("web", FakeChannelAdapter("web"))
        # Act
        names = registry.list_channels()
        # Assert
        assert set(names) == {"telegram", "web"}

    def test_list_channels_empty_registry_returns_empty_list(self) -> None:
        registry = ChannelRegistry()
        assert registry.list_channels() == []

    def test_get_missing_channel_raises_key_error(self) -> None:
        # Arrange
        registry = ChannelRegistry()
        # Act / Assert
        with pytest.raises(KeyError):
            registry.get("nonexistent")

    def test_unregister_removes_adapter_and_get_raises_after(self) -> None:
        # Arrange
        registry = ChannelRegistry()
        registry.register("slack", FakeChannelAdapter("slack"))
        # Act
        registry.unregister("slack")
        # Assert — adapter is gone
        with pytest.raises(KeyError):
            registry.get("slack")

    def test_unregister_missing_channel_raises_key_error(self) -> None:
        registry = ChannelRegistry()
        with pytest.raises(KeyError):
            registry.unregister("ghost")

    def test_register_overwrites_existing_adapter(self) -> None:
        registry = ChannelRegistry()
        old = FakeChannelAdapter("web")
        new = FakeChannelAdapter("web")
        registry.register("web", old)
        registry.register("web", new)
        assert registry.get("web") is new

    def test_list_channels_after_unregister_excludes_removed_name(self) -> None:
        registry = ChannelRegistry()
        registry.register("a", FakeChannelAdapter("a"))
        registry.register("b", FakeChannelAdapter("b"))
        registry.unregister("a")
        assert registry.list_channels() == ["b"]


# ---------------------------------------------------------------------------
# FakeAdapter functional tests
# ---------------------------------------------------------------------------


class TestFakeAdapterNormalize:
    async def test_normalize_full_payload_returns_incoming_message(self) -> None:
        # Arrange
        adapter = FakeChannelAdapter("web")
        raw: dict[str, object] = {
            "sender_id": "user-42",
            "content": "hello swarmline",
            "conversation_id": "conv-1",
            "thread_id": "thread-abc",
        }
        # Act
        msg = await adapter.normalize(raw)
        # Assert
        assert isinstance(msg, IncomingMessage)
        assert msg.channel_id == "web"
        assert msg.sender_id == "user-42"
        assert msg.content == "hello swarmline"
        assert msg.conversation_id == "conv-1"
        assert msg.thread_id == "thread-abc"
        assert msg.metadata == {"raw": raw}

    async def test_normalize_minimal_payload_uses_defaults(self) -> None:
        adapter = FakeChannelAdapter("api")
        msg = await adapter.normalize({})
        assert msg.channel_id == "api"
        assert msg.sender_id == "anon"
        assert msg.content == ""
        assert msg.conversation_id is None
        assert msg.thread_id is None
        assert msg.metadata == {"raw": {}}

    async def test_send_outgoing_message_records_message_and_returns_status(
        self,
    ) -> None:
        # Arrange
        adapter = FakeChannelAdapter("telegram")
        msg = OutgoingMessage(channel_id="telegram", content="hi there")
        # Act
        result = await adapter.send(msg)
        # Assert
        assert result == {"status": "sent", "channel": "telegram"}
        assert adapter.sent == [msg]

    async def test_send_multiple_messages_appends_all(self) -> None:
        adapter = FakeChannelAdapter("slack")
        m1 = OutgoingMessage(channel_id="slack", content="first")
        m2 = OutgoingMessage(channel_id="slack", content="second")
        await adapter.send(m1)
        await adapter.send(m2)
        assert adapter.sent == [m1, m2]

    async def test_healthcheck_returns_ok_status(self) -> None:
        adapter = FakeChannelAdapter("web")
        result = await adapter.healthcheck()
        assert result == {"channel": "web", "status": "ok"}

    async def test_fake_gateway_dispatch_event_returns_dispatched(self) -> None:
        gateway = FakeGateway()
        event = IncomingMessage(channel_id="api", sender_id="bot", content="ping")
        result = await gateway.dispatch_event(event)
        assert result["dispatched"] is True
        assert result["channel_id"] == "api"


# ---------------------------------------------------------------------------
# Envelope field-type tests — no product ids
# ---------------------------------------------------------------------------


class TestEnvelopeFields:
    def test_incoming_message_fields_are_plain_str(self) -> None:
        """channel_id, sender_id, content must be plain str — not typed product ids."""
        msg = IncomingMessage(
            channel_id="telegram",
            sender_id="u-1",
            content="hello",
        )
        assert type(msg.channel_id) is str
        assert type(msg.sender_id) is str
        assert type(msg.content) is str

    def test_incoming_message_optional_fields_default_to_none(self) -> None:
        msg = IncomingMessage(channel_id="x", sender_id="s", content="c")
        assert msg.conversation_id is None
        assert msg.thread_id is None
        assert msg.metadata == {}

    def test_outgoing_message_fields_are_plain_str(self) -> None:
        msg = OutgoingMessage(channel_id="web", content="response")
        assert type(msg.channel_id) is str
        assert type(msg.content) is str

    def test_outgoing_message_optional_fields_default_to_none(self) -> None:
        msg = OutgoingMessage(channel_id="web", content="hi")
        assert msg.conversation_id is None
        assert msg.thread_id is None
        assert msg.metadata == {}

    def test_incoming_message_is_immutable(self) -> None:
        msg = IncomingMessage(channel_id="x", sender_id="s", content="c")
        with pytest.raises(AttributeError):
            msg.content = "mutated"  # type: ignore[misc]

    def test_outgoing_message_is_immutable(self) -> None:
        msg = OutgoingMessage(channel_id="x", content="c")
        with pytest.raises(AttributeError):
            msg.content = "mutated"  # type: ignore[misc]

    def test_incoming_message_with_all_optional_fields(self) -> None:
        msg = IncomingMessage(
            channel_id="slack",
            sender_id="bot",
            content="ping",
            conversation_id="conv-99",
            thread_id="thread-77",
            metadata={"extra": "value"},
        )
        assert msg.conversation_id == "conv-99"
        assert msg.thread_id == "thread-77"
        assert msg.metadata == {"extra": "value"}

    def test_outgoing_message_with_all_optional_fields(self) -> None:
        msg = OutgoingMessage(
            channel_id="email",
            content="body",
            conversation_id="conv-1",
            thread_id="t-1",
            metadata={"subject": "re"},
        )
        assert msg.conversation_id == "conv-1"
        assert msg.thread_id == "t-1"
        assert msg.metadata == {"subject": "re"}


# ---------------------------------------------------------------------------
# Metadata immutability tests (OSS-T6 blocker fix)
# ---------------------------------------------------------------------------


class TestMetadataImmutability:
    def test_incoming_metadata_content_is_immutable(self) -> None:
        """Item assignment on IncomingMessage.metadata must raise TypeError.

        frozen=True blocks field rebinding; MappingProxyType blocks item mutation.
        """
        msg = IncomingMessage(
            channel_id="x", sender_id="s", content="c", metadata={"a": 1}
        )
        with pytest.raises(TypeError):
            msg.metadata["b"] = 2  # type: ignore[index]

    def test_incoming_metadata_isolated_from_source_dict(self) -> None:
        """Mutating the original dict after construction must not affect the envelope."""
        source: dict[str, object] = {"a": 1}
        msg = IncomingMessage(
            channel_id="x", sender_id="s", content="c", metadata=source
        )
        source["b"] = 2  # mutate original after construction
        assert "b" not in msg.metadata
        assert msg.metadata == {"a": 1}

    def test_outgoing_metadata_content_is_immutable(self) -> None:
        """Item assignment on OutgoingMessage.metadata must raise TypeError."""
        msg = OutgoingMessage(channel_id="x", content="c", metadata={"a": 1})
        with pytest.raises(TypeError):
            msg.metadata["b"] = 2  # type: ignore[index]

    def test_outgoing_metadata_isolated_from_source_dict(self) -> None:
        """Mutating the original dict after construction must not affect the envelope."""
        source: dict[str, object] = {"k": "v"}
        msg = OutgoingMessage(channel_id="x", content="c", metadata=source)
        source["new"] = "val"  # mutate original after construction
        assert "new" not in msg.metadata
        assert msg.metadata == {"k": "v"}


# ---------------------------------------------------------------------------
# Protocol runtime-checkable tests
# ---------------------------------------------------------------------------


class TestProtocolsRuntimeCheckable:
    def test_fake_adapter_satisfies_channel_adapter_port(self) -> None:
        adapter = FakeChannelAdapter("test")
        assert isinstance(adapter, ChannelAdapterPort)

    def test_channel_registry_satisfies_channel_registry_port(self) -> None:
        registry = ChannelRegistry()
        assert isinstance(registry, ChannelRegistryPort)

    def test_fake_gateway_satisfies_gateway_port(self) -> None:
        gateway = FakeGateway()
        assert isinstance(gateway, GatewayPort)

    def test_gateway_port_has_dispatch_event_method(self) -> None:
        assert hasattr(GatewayPort, "dispatch_event")

    def test_channel_adapter_port_has_expected_methods(self) -> None:
        for method in ("normalize", "send", "healthcheck"):
            assert hasattr(ChannelAdapterPort, method), f"Missing method: {method}"

    def test_channel_registry_port_has_expected_methods(self) -> None:
        for method in ("register", "unregister", "get", "list_channels"):
            assert hasattr(ChannelRegistryPort, method), f"Missing method: {method}"


# ---------------------------------------------------------------------------
# Zero product-coupling tests (AST-style source inspection)
# ---------------------------------------------------------------------------


FORBIDDEN_SYMBOLS = [
    "taskloom",
    "AccessContext",
    "TenantId",
    "WorkspaceId",
    "ConversationId",
    "AgentId",
    "FastAPI",
    "SQLAlchemy",
    "Lobu",
    "lobu",
]


def _collect_channels_sources() -> list[tuple[str, str]]:
    """Return (module_name, source_code) for every module in swarmline.channels."""
    sources: list[tuple[str, str]] = []
    # The package __init__ itself
    sources.append((channels_pkg.__name__, inspect.getsource(channels_pkg)))
    # Sub-modules
    for _finder, name, _ispkg in pkgutil.iter_modules(
        channels_pkg.__path__, channels_pkg.__name__ + "."
    ):
        mod = importlib.import_module(name)
        sources.append((name, inspect.getsource(mod)))
    return sources


def _blank_docstrings(source: str) -> str:
    """Return *source* with all module/class/function docstring lines blanked out.

    Docstrings are allowed to mention product names for provenance reasons
    (DoD: 'must be empty except docstrings').  This function zeroes out those
    lines so the coupling check only fires on actual code.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source

    docstring_lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            if (
                node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            ):
                ds = node.body[0]
                for lineno in range(ds.lineno, (ds.end_lineno or ds.lineno) + 1):
                    docstring_lines.add(lineno)  # 1-based

    if not docstring_lines:
        return source

    lines = source.splitlines(keepends=True)
    return "".join(
        "\n" if (i + 1) in docstring_lines else line for i, line in enumerate(lines)
    )


class TestZeroProductCoupling:
    def test_no_product_symbols_in_any_channels_source(self) -> None:
        """swarmline.channels must not reference any taskloom / product types in code.

        Docstring content is exempted (provenance notes are allowed there).
        """
        for mod_name, source in _collect_channels_sources():
            code_only = _blank_docstrings(source)
            for symbol in FORBIDDEN_SYMBOLS:
                assert symbol not in code_only, (
                    f"Product coupling found in code: symbol={symbol!r} in module={mod_name}"
                )
