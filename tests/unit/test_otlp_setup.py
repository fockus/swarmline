"""Unit tests for configure_otlp_from_env() in swarmline.observability.otlp_setup.

Tests are ordered from no-SDK-required (early exit paths) to SDK-required
(TracerProvider construction). SDK-needing tests are guarded with
pytest.importorskip so the test file is safe to collect without the
opentelemetry-sdk package installed.

Naming convention: test_<what>_<condition>_<result>.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from swarmline.observability.otlp_setup import configure_otlp_from_env

# ---------------------------------------------------------------------------
# No-SDK tests (early-exit path checks endpoint before any import)
# ---------------------------------------------------------------------------


def test_configure_otlp_from_env_returns_none_when_endpoint_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When OTEL_EXPORTER_OTLP_ENDPOINT is absent, return None without touching SDK."""
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)

    result = configure_otlp_from_env()

    assert result is None


def test_configure_otlp_from_env_returns_none_when_endpoint_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty string endpoint is treated the same as absent — return None."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")

    result = configure_otlp_from_env()

    assert result is None


def test_default_otlp_exporter_rejects_unknown_protocol() -> None:
    """An unrecognized protocol raises ValueError before any import attempt (no SDK)."""
    from swarmline.observability.otlp_setup import _default_otlp_exporter

    with pytest.raises(ValueError, match="Unsupported OTLP protocol"):
        _default_otlp_exporter(endpoint="http://x", headers={}, protocol="bogus")


# ---------------------------------------------------------------------------
# SDK-needing tests — guarded with importorskip
# ---------------------------------------------------------------------------

_otel_sdk = pytest.importorskip("opentelemetry.sdk")


def _make_fake_factory() -> tuple[MagicMock, MagicMock]:
    """Return (factory_callable, instance) where factory returns instance."""
    instance = MagicMock(name="FakeExporter")
    factory = MagicMock(name="fake_factory", return_value=instance)
    return factory, instance


def test_configure_otlp_from_env_passes_endpoint_to_factory_when_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Factory is called exactly once with the configured endpoint; provider is returned."""
    from opentelemetry.sdk.trace import TracerProvider

    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_HEADERS", raising=False)
    monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)

    factory, _ = _make_fake_factory()

    result = configure_otlp_from_env(exporter_factory=factory)

    factory.assert_called_once()
    call_kwargs = factory.call_args.kwargs
    assert call_kwargs["endpoint"] == "http://localhost:4317"
    assert isinstance(result, TracerProvider)


def test_configure_otlp_from_env_uses_service_name_from_env_when_arg_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OTEL_SERVICE_NAME env var sets the service.name resource attribute."""
    from opentelemetry.sdk.trace import TracerProvider

    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
    monkeypatch.setenv("OTEL_SERVICE_NAME", "svc")
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_HEADERS", raising=False)

    factory, _ = _make_fake_factory()

    result = configure_otlp_from_env(exporter_factory=factory)

    assert isinstance(result, TracerProvider)
    resource_attrs = result.resource.attributes
    assert resource_attrs.get("service.name") == "svc"


def test_configure_otlp_from_env_arg_overrides_env_service_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit service_name= kwarg wins over OTEL_SERVICE_NAME env var."""
    from opentelemetry.sdk.trace import TracerProvider

    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
    monkeypatch.setenv("OTEL_SERVICE_NAME", "env-svc")
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_HEADERS", raising=False)

    factory, _ = _make_fake_factory()

    result = configure_otlp_from_env(service_name="arg-svc", exporter_factory=factory)

    assert isinstance(result, TracerProvider)
    resource_attrs = result.resource.attributes
    assert resource_attrs.get("service.name") == "arg-svc"


def test_configure_otlp_from_env_parses_headers_into_dict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OTEL_EXPORTER_OTLP_HEADERS 'a=1,b=2' is passed to factory as headers dict."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_HEADERS", "a=1,b=2")
    monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)

    factory, _ = _make_fake_factory()

    configure_otlp_from_env(exporter_factory=factory)

    call_kwargs = factory.call_args.kwargs
    assert call_kwargs["headers"] == {"a": "1", "b": "2"}


def test_configure_otlp_from_env_ignores_malformed_header_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Header entries without '=' are silently ignored, no exception raised."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_HEADERS", "good=val,badentry,also=ok")
    monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)

    factory, _ = _make_fake_factory()

    configure_otlp_from_env(exporter_factory=factory)  # must not raise

    call_kwargs = factory.call_args.kwargs
    assert call_kwargs["headers"] == {"good": "val", "also": "ok"}


def test_configure_otlp_from_env_falls_back_to_swarmline_service_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No service_name kwarg and no OTEL_SERVICE_NAME → service.name == 'swarmline'."""
    from opentelemetry.sdk.trace import TracerProvider

    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
    monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_HEADERS", raising=False)

    factory, _ = _make_fake_factory()

    result = configure_otlp_from_env(exporter_factory=factory)

    assert isinstance(result, TracerProvider)
    assert result.resource.attributes.get("service.name") == "swarmline"


def test_configure_otlp_from_env_set_global_registers_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """set_global=True registers the provider via trace.set_tracer_provider()."""
    import opentelemetry.trace as trace_api

    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_HEADERS", raising=False)
    monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)
    # Patch the global setter so we assert the call without polluting OTel's
    # process-wide "set once" provider (which would leak across tests).
    set_global_mock = MagicMock(name="set_tracer_provider")
    monkeypatch.setattr(trace_api, "set_tracer_provider", set_global_mock)

    factory, _ = _make_fake_factory()

    result = configure_otlp_from_env(exporter_factory=factory, set_global=True)

    set_global_mock.assert_called_once_with(result)


def test_configure_otlp_from_env_default_does_not_mutate_global_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default set_global=False never calls trace.set_tracer_provider()."""
    import opentelemetry.trace as trace_api

    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_HEADERS", raising=False)
    monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)
    set_global_mock = MagicMock(name="set_tracer_provider")
    monkeypatch.setattr(trace_api, "set_tracer_provider", set_global_mock)

    factory, _ = _make_fake_factory()

    configure_otlp_from_env(exporter_factory=factory)

    set_global_mock.assert_not_called()
