"""LangSmith exporter -- bridges EventBus events to LangSmith runs.

Subscribes to EventBus events (llm_call_start/end, tool_call_start/end)
and records LLM calls as LangSmith runs of type ``llm`` and tool calls
as runs of type ``tool``.

Usage::

    from swarmline.observability.langsmith_exporter import LangSmithExporter

    exporter = LangSmithExporter()  # credentials from LANGSMITH_* env vars
    exporter.attach(event_bus)
    # ... agent runs, events flow ...
    exporter.detach(event_bus)

Requires: ``pip install swarmline[langsmith]``.

A pre-built client (or any object with the same ``create_run`` /
``update_run`` surface) can be injected via ``client=`` -- useful for
tests and for sharing one client across exporters.
"""

from __future__ import annotations

import importlib
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def _try_import_langsmith() -> Any:
    """Lazy import the LangSmith client class.

    Returns
    -------
    type
        ``langsmith.Client`` or raises ImportError with install hint.
    """
    try:
        module = importlib.import_module("langsmith")
        return module.Client
    except ImportError:
        raise ImportError(
            "The langsmith package is required for LangSmithExporter. "
            "Install it with: pip install swarmline[langsmith]"
        ) from None


def _dotted_order(start_time: datetime, run_id: uuid.UUID) -> str:
    """LangSmith root-run dotted order: strftime timestamp + run id."""
    return start_time.strftime("%Y%m%dT%H%M%S%fZ") + str(run_id)


class LangSmithExporter:
    """Bridges Swarmline EventBus events to LangSmith runs.

    Each LLM/tool call becomes a root run (its own trace); the session id,
    when configured, lands in run metadata so runs of one session can be
    filtered together. Export errors are logged and swallowed --
    observability must never break an agent run.

    Parameters
    ----------
    bus:
        Optional EventBus; can also be passed to :meth:`attach`.
    client:
        Pre-built LangSmith client (duck-typed). If ``None``, a real
        ``langsmith.Client`` is constructed from the explicit values below
        or the ``LANGSMITH_API_KEY`` / ``LANGSMITH_ENDPOINT`` environment
        variables.
    api_key / api_url:
        Explicit LangSmith credentials; ignored when ``client`` is given.
    project_name:
        Target LangSmith project. ``None`` uses the SDK default
        (``LANGSMITH_PROJECT`` env var or ``"default"``).
    runtime_name:
        Optional runtime identifier (e.g. ``"thin"``), added to metadata.
    session_id:
        Optional session identifier, added to metadata.
    """

    def __init__(
        self,
        bus: Any = None,
        *,
        client: Any = None,
        api_key: str | None = None,
        api_url: str | None = None,
        project_name: str | None = None,
        runtime_name: str | None = None,
        session_id: str | None = None,
    ) -> None:
        if client is not None:
            self._client = client
        else:
            client_cls = _try_import_langsmith()
            kwargs: dict[str, Any] = {}
            if api_key is not None:
                kwargs["api_key"] = api_key
            if api_url is not None:
                kwargs["api_url"] = api_url
            self._client = client_cls(**kwargs)

        self._bus = bus
        self._project_name = project_name
        self._runtime_name = runtime_name
        self._session_id = session_id
        self._active: dict[str, uuid.UUID] = {}  # key -> LangSmith run id
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
        """Unsubscribe and close any lingering runs."""
        bus = event_bus or self._bus
        if bus is not None:
            for sid in self._sub_ids:
                bus.unsubscribe(sid)
        self._sub_ids.clear()
        now = datetime.now(timezone.utc)
        for run_id in self._active.values():
            try:
                self._client.update_run(run_id, end_time=now)
            except Exception:  # noqa: BLE001
                pass
        self._active.clear()

    def _metadata(self) -> dict[str, Any]:
        meta: dict[str, Any] = {}
        if self._runtime_name:
            meta["swarmline.runtime"] = self._runtime_name
        if self._session_id:
            meta["swarmline.session_id"] = self._session_id
        return meta

    def _create_run(
        self,
        *,
        name: str,
        run_type: str,
        inputs: dict[str, Any],
        event_name: str,
    ) -> uuid.UUID | None:
        run_id = uuid.uuid4()
        start = datetime.now(timezone.utc)
        try:
            self._client.create_run(
                name=name,
                run_type=run_type,
                inputs=inputs,
                id=run_id,
                trace_id=run_id,
                dotted_order=_dotted_order(start, run_id),
                start_time=start,
                extra={"metadata": self._metadata()},
                project_name=self._project_name,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("LangSmith export failed (%s): %s", event_name, exc)
            return None
        return run_id

    def _end_run(
        self,
        run_id: uuid.UUID,
        *,
        outputs: dict[str, Any],
        data: dict[str, Any],
        event_name: str,
        default_error: str,
    ) -> None:
        kwargs: dict[str, Any] = {
            "outputs": outputs,
            "end_time": datetime.now(timezone.utc),
        }
        if data.get("error"):
            kwargs["error"] = data.get("error_message", default_error)
        try:
            self._client.update_run(run_id, **kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.warning("LangSmith export failed (%s): %s", event_name, exc)

    def _on_llm_start(self, data: dict[str, Any]) -> None:
        model = data.get("model", "unknown")
        inputs: dict[str, Any] = {"model": model}
        if "messages" in data:
            inputs["messages"] = data["messages"]
        run_id = self._create_run(
            name=f"swarmline.llm.{model}",
            run_type="llm",
            inputs=inputs,
            event_name="llm_call_start",
        )
        if run_id is not None:
            self._active[f"llm_call:{data.get('correlation_id', run_id)}"] = run_id

    def _on_llm_end(self, data: dict[str, Any]) -> None:
        key = f"llm_call:{data.get('correlation_id', '')}"
        run_id = self._active.pop(key, None)
        if run_id is None:
            # Fallback: pair with any open llm run (legacy events without
            # correlation_id).
            for k in list(self._active):
                if k.startswith("llm_call:"):
                    run_id = self._active.pop(k)
                    break
        if run_id is None:
            return
        outputs: dict[str, Any] = {}
        for field in ("response", "input_tokens", "output_tokens", "finish_reason"):
            if field in data:
                outputs[field] = data[field]
        self._end_run(
            run_id,
            outputs=outputs,
            data=data,
            event_name="llm_call_end",
            default_error="LLM call failed",
        )

    def _on_tool_start(self, data: dict[str, Any]) -> None:
        tool_name = data.get("name", "unknown_tool")
        inputs: dict[str, Any] = {"tool": tool_name}
        if "args" in data:
            inputs["args"] = data["args"]
        run_id = self._create_run(
            name=f"swarmline.tool.{tool_name}",
            run_type="tool",
            inputs=inputs,
            event_name="tool_call_start",
        )
        if run_id is not None:
            correlation_id = data.get("correlation_id", tool_name)
            self._active[f"tool_call:{correlation_id}"] = run_id

    def _on_tool_end(self, data: dict[str, Any]) -> None:
        correlation_id = data.get("correlation_id", data.get("name", "unknown"))
        run_id = self._active.pop(f"tool_call:{correlation_id}", None)
        if run_id is None:
            return
        outputs: dict[str, Any] = {}
        if "ok" in data:
            outputs["ok"] = data["ok"]
        self._end_run(
            run_id,
            outputs=outputs,
            data=data,
            event_name="tool_call_end",
            default_error="Tool call failed",
        )
