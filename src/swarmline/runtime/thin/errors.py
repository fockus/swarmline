"""Typed errors for ThinRuntime LLM integration."""

from __future__ import annotations

from typing import Any

from swarmline.runtime.types import RuntimeErrorData


class ThinLlmError(RuntimeError):
    """Typed exception carrying RuntimeErrorData for ThinRuntime."""

    def __init__(self, error: RuntimeErrorData) -> None:
        super().__init__(error.message)
        self.error = error


def dependency_missing_error(
    message: str,
    *,
    provider: str | None = None,
    package: str | None = None,
) -> ThinLlmError:
    """Build dependency_missing error for missing provider SDKs."""
    details: dict[str, Any] = {}
    if provider is not None:
        details["provider"] = provider
    if package is not None:
        details["package"] = package
    return ThinLlmError(
        RuntimeErrorData(
            kind="dependency_missing",
            message=message,
            recoverable=False,
            details=details or None,
        )
    )


def provider_runtime_crash(provider: str, exc: Exception) -> ThinLlmError:
    """Normalize provider/API exceptions to a runtime_crash error."""
    return ThinLlmError(
        RuntimeErrorData(
            kind="runtime_crash",
            message=f"LLM API error ({provider}): {type(exc).__name__}: {exc}",
            recoverable=False,
            details={
                "provider": provider,
                "exception_type": type(exc).__name__,
            },
        )
    )
