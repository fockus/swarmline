"""Langfuse exporter -- bridges EventBus events to Langfuse traces.

Subscribes to EventBus events (llm_call_start/end, tool_call_start/end)
and records LLM calls as Langfuse *generations* (model, token usage, latency)
and tool calls as Langfuse *spans*.

Usage::

    from swarmline.observability.langfuse_exporter import LangfuseExporter

    exporter = LangfuseExporter()  # credentials from LANGFUSE_* env vars
    exporter.attach(event_bus)
    # ... agent runs, events flow ...
    exporter.detach(event_bus)

Requires: ``pip install swarmline[langfuse]`` (langfuse SDK v3+).

A pre-built client (or any object with the same ``start_generation`` /
``start_span`` / ``flush`` surface) can be injected via ``client=`` --
useful for tests and for sharing one client across exporters.
"""

from __future__ import annotations

import importlib
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _try_import_langfuse() -> Any:
    """Lazy import the Langfuse client class.

    Returns
    -------
    type
        ``langfuse.Langfuse`` or raises ImportError with install hint.
    """
    try:
        module = importlib.import_module("langfuse")
        return module.Langfuse
    except ImportError:
        raise ImportError(
            "The langfuse package is required for LangfuseExporter. "
            "Install it with: pip install swarmline[langfuse]"
        ) from None


class LangfuseExporter:
    """Bridges Swarmline EventBus events to Langfuse observations.

    LLM calls become generations (with model and token usage when the
    events carry them); tool calls become spans. Export errors are logged
    and swallowed -- observability must never break an agent run.

    Parameters
    ----------
    bus:
        Optional EventBus; can also be passed to :meth:`attach`.
    client:
        Pre-built Langfuse client (duck-typed). If ``None``, a real
        ``langfuse.Langfuse`` is constructed from the explicit keys below
        or the ``LANGFUSE_PUBLIC_KEY`` / ``LANGFUSE_SECRET_KEY`` /
        ``LANGFUSE_HOST`` environment variables.
    public_key / secret_key / host:
        Explicit Langfuse credentials; ignored when ``client`` is given.
    runtime_name:
        Optional runtime identifier (e.g. ``"thin"``), added to metadata.
    session_id:
        Optional session identifier; added to metadata and, when the SDK
        supports it, promoted to the Langfuse trace session.
    """

    def __init__(
        self,
        bus: Any = None,
        *,
        client: Any = None,
        public_key: str | None = None,
        secret_key: str | None = None,
        host: str | None = None,
        runtime_name: str | None = None,
        session_id: str | None = None,
    ) -> None:
        if client is not None:
            self._client = client
        else:
            langfuse_cls = _try_import_langfuse()
            kwargs: dict[str, Any] = {}
            if public_key is not None:
                kwargs["public_key"] = public_key
            if secret_key is not None:
                kwargs["secret_key"] = secret_key
            if host is not None:
                kwargs["host"] = host
            self._client = langfuse_cls(**kwargs)

        self._bus = bus
        self._runtime_name = runtime_name
        self._session_id = session_id
        self._active: dict[str, Any] = {}  # key -> Langfuse observation
        self._sub_ids: list[str] = []

    def attach(self, event_bus: Any = None) -> None:
        """Subscribe to EventBus events."""
        bus = event_bus or self._bus
        if bus is None:
            raise ValueError("No EventBus provided to attach()")
        self._bus = bus
        self._sub_ids.append(bus.subscribe("llm_call_start", self._on_llm_start))
        self._sub_ids.append(bus.subscribe("llm_call_end", self._on_llm_end))
        self._sub_ids.append(bus.subscribe("tool_call_start", self._on_tool_start))
        self._sub_ids.append(bus.subscribe("tool_call_end", self._on_tool_end))

    def detach(self, event_bus: Any = None) -> None:
        """Unsubscribe, end lingering observations, and flush the client."""
        bus = event_bus or self._bus
        if bus is not None:
            for sid in self._sub_ids:
                bus.unsubscribe(sid)
        self._sub_ids.clear()
        for obs in self._active.values():
            try:
                obs.end()
            except Exception:  # noqa: BLE001
                pass
        self._active.clear()
        try:
            self._client.flush()
        except Exception:  # noqa: BLE001
            pass

    def _metadata(self) -> dict[str, Any]:
        meta: dict[str, Any] = {}
        if self._runtime_name:
            meta["swarmline.runtime"] = self._runtime_name
        if self._session_id:
            meta["swarmline.session_id"] = self._session_id
        return meta

    def _bind_session(self, obs: Any) -> None:
        """Promote session_id to the Langfuse trace when the SDK supports it."""
        if not self._session_id:
            return
        update_trace = getattr(obs, "update_trace", None)
        if update_trace is None:
            return
        try:
            update_trace(session_id=self._session_id)
        except Exception:  # noqa: BLE001
            pass

    def _on_llm_start(self, data: dict[str, Any]) -> None:
        model = data.get("model", "unknown")
        try:
            obs = self._client.start_generation(
                name=f"swarmline.llm.{model}",
                model=model,
                input=data.get("messages"),
                metadata=self._metadata(),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Langfuse export failed (llm_call_start): %s", exc)
            return
        self._bind_session(obs)
        key = f"llm_call:{data.get('correlation_id', id(obs))}"
        self._active[key] = obs

    def _on_llm_end(self, data: dict[str, Any]) -> None:
        key = f"llm_call:{data.get('correlation_id', '')}"
        obs = self._active.pop(key, None)
        if obs is None:
            # Fallback: pair with any open llm observation (legacy events
            # without correlation_id).
            for k in list(self._active):
                if k.startswith("llm_call:"):
                    obs = self._active.pop(k)
                    break
        if obs is None:
            return

        update_kwargs: dict[str, Any] = {}
        if "response" in data:
            update_kwargs["output"] = data["response"]
        usage: dict[str, int] = {}
        if "input_tokens" in data:
            usage["input"] = data["input_tokens"]
        if "output_tokens" in data:
            usage["output"] = data["output_tokens"]
        if usage:
            update_kwargs["usage_details"] = usage
        if data.get("error"):
            update_kwargs["level"] = "ERROR"
            update_kwargs["status_message"] = data.get(
                "error_message", "LLM call failed"
            )
        try:
            if update_kwargs:
                obs.update(**update_kwargs)
            obs.end()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Langfuse export failed (llm_call_end): %s", exc)

    def _on_tool_start(self, data: dict[str, Any]) -> None:
        tool_name = data.get("name", "unknown_tool")
        try:
            obs = self._client.start_span(
                name=f"swarmline.tool.{tool_name}",
                input=data.get("args"),
                metadata=self._metadata(),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Langfuse export failed (tool_call_start): %s", exc)
            return
        self._bind_session(obs)
        correlation_id = data.get("correlation_id", tool_name)
        self._active[f"tool_call:{correlation_id}"] = obs

    def _on_tool_end(self, data: dict[str, Any]) -> None:
        correlation_id = data.get("correlation_id", data.get("name", "unknown"))
        obs = self._active.pop(f"tool_call:{correlation_id}", None)
        if obs is None:
            return
        update_kwargs: dict[str, Any] = {}
        if data.get("error"):
            update_kwargs["level"] = "ERROR"
            update_kwargs["status_message"] = data.get(
                "error_message", "Tool call failed"
            )
        try:
            if update_kwargs:
                obs.update(**update_kwargs)
            obs.end()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Langfuse export failed (tool_call_end): %s", exc)
