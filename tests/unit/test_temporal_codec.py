"""Unit tests for the redaction PayloadCodec. Requires temporalio."""

from __future__ import annotations

import json

import pytest

pytest.importorskip("temporalio")

from temporalio.api.common.v1 import Payload  # noqa: E402

from swarmline.runtime.temporal.codec import (  # noqa: E402
    RedactionCodec,
    build_data_converter,
)

_SECRET = "sk-proj-abc123456789012345678901234"


class TestRedactionCodec:
    async def test_encode_redacts_secrets_in_json_payloads(self) -> None:
        codec = RedactionCodec()
        payload = Payload(
            metadata={"encoding": b"json/plain"},
            data=json.dumps({"note": f"my key is {_SECRET}"}).encode(),
        )

        [encoded] = await codec.encode([payload])

        assert _SECRET.encode() not in encoded.data
        assert b"REDACTED" in encoded.data
        assert encoded.metadata["encoding"] == b"json/plain"

    async def test_clean_payloads_pass_through_unchanged(self) -> None:
        codec = RedactionCodec()
        payload = Payload(
            metadata={"encoding": b"json/plain"},
            data=json.dumps({"note": "nothing secret here"}).encode(),
        )

        [encoded] = await codec.encode([payload])

        assert encoded is payload

    async def test_non_json_payloads_pass_through(self) -> None:
        codec = RedactionCodec()
        payload = Payload(
            metadata={"encoding": b"binary/plain"},
            data=f"raw {_SECRET}".encode(),
        )

        [encoded] = await codec.encode([payload])

        assert encoded is payload  # unknown encodings are never touched

    async def test_decode_is_passthrough(self) -> None:
        codec = RedactionCodec()
        payload = Payload(metadata={"encoding": b"json/plain"}, data=b'"x"')

        assert await codec.decode([payload]) == [payload]


class TestConverterIntegration:
    async def test_secret_never_survives_the_wire_roundtrip(self) -> None:
        conv = build_data_converter()

        payloads = await conv.encode([{"tool_result": f"Bearer {_SECRET} leaked"}])
        [decoded] = await conv.decode(payloads)

        text = json.dumps(decoded)
        assert _SECRET not in text
        assert "REDACTED" in text

    async def test_payload_dataclasses_still_roundtrip(self) -> None:
        from swarmline.runtime.temporal.payloads import AgentRunInput

        conv = build_data_converter()
        inp = AgentRunInput(
            messages=[{"role": "user", "content": "hi"}],
            system_prompt="sys",
            tools=[],
            run_id="r1",
            model="m1",
            use_reference_history=True,
        )

        [decoded] = await conv.decode(await conv.encode([inp]), [AgentRunInput])

        assert decoded == inp
