"""Guardrails -- pre/post-LLM safety checks.

Demonstrates: ContentLengthGuardrail, RegexGuardrail, GuardrailContext.
No API keys required.
"""

import asyncio

from cognitia.guardrails import (
    ContentLengthGuardrail,
    GuardrailContext,
    RegexGuardrail,
)


async def main() -> None:
    ctx = GuardrailContext(session_id="demo-session", model="gpt-4o", turn=1)

    # 1. Content length guardrail
    length_guard = ContentLengthGuardrail(max_length=50)

    short = await length_guard.check(ctx, "Hello, world!")
    print(f"Short text: passed={short.passed}")

    long = await length_guard.check(ctx, "x" * 100)
    print(f"Long text: passed={long.passed}, reason={long.reason}")

    # 2. Regex guardrail -- block forbidden patterns
    regex_guard = RegexGuardrail(
        patterns=[r"(?i)\bpassword\b", r"\b\d{3}-\d{2}-\d{4}\b"],
        reason="Sensitive data detected",
    )

    safe = await regex_guard.check(ctx, "The weather is nice today.")
    print(f"Safe text: passed={safe.passed}")

    unsafe = await regex_guard.check(ctx, "My password is hunter2")
    print(f"Unsafe text: passed={unsafe.passed}, reason={unsafe.reason}")

    ssn = await regex_guard.check(ctx, "SSN: 123-45-6789")
    print(f"SSN text: passed={ssn.passed}, reason={ssn.reason}")


if __name__ == "__main__":
    asyncio.run(main())
