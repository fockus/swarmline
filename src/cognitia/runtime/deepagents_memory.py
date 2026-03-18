"""Native thread/checkpointer/store helpers for DeepAgents."""

from __future__ import annotations

from typing import Any

from cognitia.runtime.types import RuntimeErrorData


def _build_resume_command(resume_value: Any) -> Any:
    """Build a langgraph Command lazily so the base install stays import-safe."""
    try:
        from langgraph.types import Command  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "DeepAgents native resume requires the optional dependency `langgraph` "
            "(install `cognitia[deepagents]`)."
        ) from exc
    return Command(resume=resume_value)


def validate_native_state_config(
    native_config: dict[str, Any],
) -> RuntimeErrorData | None:
    """Check native thread state config compatibility."""
    if native_config.get("resume") is not None and native_config.get("checkpointer") is None:
        return RuntimeErrorData(
            kind="capability_unsupported",
            message=("DeepAgents native resume requires a checkpointer in native_config."),
            recoverable=False,
        )
    return None


def build_native_invocation(
    *,
    messages: list[Any],
    native_config: dict[str, Any],
) -> tuple[Any, dict[str, Any], dict[str, Any]]:
    """Build graph input/config/native metadata for the native DeepAgents path."""
    thread_id = native_config.get("thread_id")
    checkpointer = native_config.get("checkpointer")
    store = native_config.get("store")
    resume_value = native_config.get("resume")
    uses_native_thread = checkpointer is not None

    if resume_value is not None:
        payload: Any = _build_resume_command(resume_value)
    elif uses_native_thread:
        payload = {"messages": list(messages[-1:])}
    else:
        payload = {"messages": list(messages)}

    run_config: dict[str, Any] = {}
    if thread_id is not None:
        run_config["configurable"] = {"thread_id": thread_id}

    native_metadata = {
        "runtime": "deepagents",
        "thread_id": thread_id,
        "history_source": "native_thread" if uses_native_thread else "cognitia_history",
        "uses_checkpointer": checkpointer is not None,
        "uses_store": store is not None,
        "resume_requested": resume_value is not None,
    }

    return payload, run_config, native_metadata


def build_native_state_notice(native_metadata: dict[str, Any]) -> str | None:
    """Explicit notice when native thread semantics differ from portable history replay."""
    if native_metadata.get("history_source") != "native_thread" and not native_metadata.get(
        "resume_requested"
    ):
        return None

    parts = ["DeepAgents native thread semantics active"]
    thread_id = native_metadata.get("thread_id")
    if thread_id:
        parts.append(f"thread_id={thread_id}")
    if native_metadata.get("resume_requested"):
        parts.append("resume command provided")
    else:
        parts.append("history source=native thread (latest message only)")
    return "; ".join(parts)
