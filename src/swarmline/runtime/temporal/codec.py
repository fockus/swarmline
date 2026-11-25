"""Redaction PayloadCodec — keeps secrets out of server-side history.

Every workflow input, activity input/output, and result is persisted in
Temporal's event history **on the server**. This codec runs
``observability.redaction.redact_secrets`` over each JSON payload at encode
time (client → server and worker → server), so Bearer tokens, ``sk-*`` API
keys, URL userinfo, and env-style ``KEY=value`` secrets never land in
history in plaintext.

Redaction is one-way: decode is a passthrough, so a client or worker
connected *without* the codec still reads codec-encoded payloads (they are
plain JSON, just redacted). Asymmetric configuration degrades safely.

The swarmline wire contract never carries credentials by design (LLM keys
live on workers, never in payloads) — the codec is defense-in-depth for
secrets that leak *through content*: tool results, error messages, model
output.
"""

from __future__ import annotations

from typing import Any

from temporalio.api.common.v1 import Payload
from temporalio.converter import DataConverter, PayloadCodec

from swarmline.observability.redaction import redact_secrets

_JSON_ENCODINGS = (b"json/plain", b"json/protobuf")


class RedactionCodec(PayloadCodec):
    """Applies secret-pattern redaction to JSON payloads at encode time."""

    async def encode(self, payloads: Any) -> list[Payload]:
        return [self._redact(p) for p in payloads]

    async def decode(self, payloads: Any) -> list[Payload]:
        return list(payloads)

    @staticmethod
    def _redact(payload: Payload) -> Payload:
        if payload.metadata.get("encoding") not in _JSON_ENCODINGS:
            return payload  # binary/unknown encodings pass through untouched
        try:
            text = payload.data.decode("utf-8")
        except UnicodeDecodeError:
            return payload
        redacted = redact_secrets(text)
        if redacted == text:
            return payload
        return Payload(metadata=dict(payload.metadata), data=redacted.encode("utf-8"))


def build_data_converter() -> DataConverter:
    """Temporal's default JSON converter + the redaction codec."""
    import dataclasses

    return dataclasses.replace(DataConverter.default, payload_codec=RedactionCodec())
