# Production Safety

Swarmline provides four complementary safety mechanisms for production deployments: **cost budgets**, **guardrails**, **input filters**, and **retry/fallback policies**. All are opt-in via `RuntimeConfig` — disabled by default for zero overhead.

## Cost Budget Tracking

Track accumulated LLM costs and enforce spending limits.

```python
from swarmline.runtime.cost import CostBudget
from swarmline.runtime.types import RuntimeConfig

config = RuntimeConfig(
    runtime_name="thin",
    cost_budget=CostBudget(
        max_cost_usd=5.0,           # USD spending cap
        max_total_tokens=1_000_000,  # token cap (optional)
        action_on_exceed="error",    # "error" (stop) or "warn" (continue)
    ),
)
```

### How It Works

- ThinRuntime creates a `CostTracker` at startup and records usage after each LLM call
- Costs are computed using bundled `pricing.json` (updated with major model releases)
- Unknown models fall back to `_default` pricing — no crashes on new models
- When exceeded: emits `RuntimeEvent` with `kind="budget_exceeded"` (error mode) or continues with warning
- Final event includes `total_cost_usd` when budget tracking is active

### Bundled Pricing

| Model | Input $/1M tokens | Output $/1M tokens |
|-------|-------------------|-------------------|
| claude-sonnet-4-20250514 | 3.00 | 15.00 |
| gpt-4o | 2.50 | 10.00 |
| gpt-4o-mini | 0.15 | 0.60 |
| gemini-2.0-flash | 0.10 | 0.40 |
| `_default` | 3.00 | 15.00 |

### CostBudget Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `max_cost_usd` | `float \| None` | `None` | Maximum total cost in USD. `None` disables cost limit. |
| `max_total_tokens` | `int \| None` | `None` | Maximum total tokens (input + output). `None` disables token limit. |
| `action_on_exceed` | `"error" \| "warn"` | `"error"` | `"error"` emits a `budget_exceeded` event and stops. `"warn"` continues with warning status. |

### Programmatic Access

```python
from swarmline.runtime.cost import CostTracker, CostBudget, load_pricing

tracker = CostTracker(budget=budget, pricing=load_pricing())
tracker.record("gpt-4o", input_tokens=1000, output_tokens=500)

print(tracker.total_cost_usd)    # accumulated cost
print(tracker.total_tokens)      # accumulated tokens
print(tracker.check_budget())    # "ok" | "warning" | "exceeded"
tracker.reset()                  # zero all counters
```

### Custom Pricing

Override bundled pricing by passing a custom `dict[str, ModelPricing]` to `CostTracker`:

```python
from swarmline.runtime.cost import CostTracker, CostBudget, ModelPricing

custom_pricing = {
    "my-fine-tuned-model": ModelPricing(input_per_1m=5.0, output_per_1m=20.0),
    "_default": ModelPricing(input_per_1m=3.0, output_per_1m=15.0),
}

tracker = CostTracker(
    budget=CostBudget(max_cost_usd=10.0),
    pricing=custom_pricing,
)
```

`ModelPricing` is a frozen dataclass with two fields: `input_per_1m` and `output_per_1m` (USD per 1 million tokens). When `CostTracker.record()` encounters an unknown model, it falls back to the `_default` key. If no `_default` is present and the model is unknown, the call is silently ignored (no cost recorded).

The `load_pricing()` function loads the bundled `pricing.json` via `importlib.resources`, making it reliable inside installed packages.

---

## Guardrails

Pre- and post-LLM content checks. Input guardrails run before the LLM call; output guardrails run after. A failed guardrail emits an error event with `kind="guardrail_tripwire"`.

```python
from swarmline.guardrails import (
    ContentLengthGuardrail,
    RegexGuardrail,
    CallerAllowlistGuardrail,
)
from swarmline.runtime.types import RuntimeConfig

config = RuntimeConfig(
    runtime_name="thin",
    input_guardrails=[
        ContentLengthGuardrail(max_length=8000),
        RegexGuardrail(patterns=[r"ignore previous instructions"]),
    ],
    output_guardrails=[
        RegexGuardrail(
            patterns=[r"SECRET_\d+"],
            reason="Sensitive data leaked in response",
        ),
    ],
)
```

### Built-in Guardrails

| Guardrail | Description |
|-----------|-------------|
| `ContentLengthGuardrail` | Rejects text longer than `max_length` characters (default: 100,000) |
| `RegexGuardrail` | Rejects text matching any of the given regex `patterns` |
| `CallerAllowlistGuardrail` | Rejects requests from `session_id` not in the allowlist |

### Custom Guardrails

Implement the `Guardrail` protocol:

```python
from swarmline.guardrails import GuardrailContext, GuardrailResult

class ToxicityGuardrail:
    async def check(self, ctx: GuardrailContext, text: str) -> GuardrailResult:
        if is_toxic(text):
            return GuardrailResult(passed=False, reason="Toxic content detected")
        return GuardrailResult(passed=True)
```

### Execution Model

- All guardrails run in parallel via `asyncio.gather` — N guardrails don't add linear latency
- First failure stops execution and emits an error event
- `tripwire=True` in `GuardrailResult` marks a hard, non-recoverable failure

---

## Input Filters

Transform messages and system prompt before each LLM call. Filters are applied sequentially in list order.

```python
from swarmline.input_filters import MaxTokensFilter, SystemPromptInjector
from swarmline.runtime.types import RuntimeConfig

config = RuntimeConfig(
    runtime_name="thin",
    input_filters=[
        SystemPromptInjector(
            extra_text="Always reply in English.",
            position="prepend",  # or "append"
        ),
        MaxTokensFilter(max_tokens=64_000),
    ],
)
```

### Built-in Filters

| Filter | Description |
|--------|-------------|
| `MaxTokensFilter` | Trims older messages to fit within `max_tokens` budget. Always preserves system prompt and the last message. Token estimation: `len(text) / chars_per_token` (default 4.0). |
| `SystemPromptInjector` | Prepends or appends text to the system prompt. |

### InputFilter Protocol

All filters implement the `InputFilter` protocol from `swarmline.input_filters`:

```python
from swarmline.input_filters import InputFilter
from swarmline.runtime.types import Message

class RedactFilter:
    async def filter(
        self, messages: list[Message], system_prompt: str
    ) -> tuple[list[Message], str]:
        cleaned = [redact_pii(m) for m in messages]
        return cleaned, system_prompt
```

Filters are applied sequentially in list order. Each filter receives the output of the previous one, forming a pipeline. The final `(messages, system_prompt)` tuple is passed to the LLM call.

---

## Retry / Fallback Policy

Automatic retry with exponential backoff when LLM calls fail.

```python
from swarmline.retry import ExponentialBackoff
from swarmline.runtime.types import RuntimeConfig

config = RuntimeConfig(
    runtime_name="thin",
    retry_policy=ExponentialBackoff(
        max_retries=3,       # up to 3 retries (4 total attempts)
        base_delay=1.0,      # seconds
        max_delay=60.0,      # cap
        jitter=True,         # random factor 0.5-1.5x
    ),
)
```

### Delay Formula

```
delay = min(base_delay * 2^attempt, max_delay) * uniform(0.5, 1.5)
```

### Model Fallback Chain

Switch to a backup model when the primary fails:

```python
from swarmline.retry import ModelFallbackChain

chain = ModelFallbackChain(models=["gpt-4o", "claude-sonnet-4-20250514", "gemini-2.0-flash"])
next_model = chain.next_model("gpt-4o")  # "claude-sonnet-4-20250514"
```

### Provider Fallback

Switch to an entirely different provider when the primary is down:

```python
from swarmline.retry import ProviderFallback

fb = ProviderFallback(fallback_model="openai:gpt-4o")
# Use fb.fallback_model as the target when the primary provider returns errors
```

`ProviderFallback` is a frozen dataclass with a single field (`fallback_model: str`). It is intended to be used alongside `ModelFallbackChain` for two-level resilience: first try alternative models within the same provider, then fail over to a different provider entirely.

### RetryPolicy Protocol

All retry strategies implement the `RetryPolicy` protocol:

```python
from swarmline.retry import RetryPolicy

class MyRetryPolicy:
    def should_retry(self, error: Exception, attempt: int) -> tuple[bool, float]:
        """Return (should_retry, delay_seconds). attempt is zero-based."""
        if attempt < 2 and "rate_limit" in str(error):
            return True, 5.0
        return False, 0.0
```

The `attempt` parameter is zero-based (0 = first retry candidate). When `should_retry` returns `False`, the delay value is ignored.

---

## Data Flow

The complete request pipeline with all safety mechanisms:

```
User Input
    │
    ▼
Input Filters (sequential: SystemPromptInjector → MaxTokensFilter → RagInputFilter)
    │
    ▼
Input Guardrails (parallel, asyncio.gather)
    │  fail → error event, kind="guardrail_tripwire"
    ▼  pass
LLM Call
    │  error → RetryPolicy.should_retry → retry loop or error event
    ▼  success
Output Guardrails (parallel)
    │  fail → error event, kind="guardrail_tripwire"
    ▼  pass
CostTracker.record → check_budget
    │  exceeded → budget_exceeded event (if action="error")
    ▼  ok
Final RuntimeEvent
```

## PII Redaction

Swarmline ships a zero-dependency PII guardrail based on a conservative set of
compiled, ReDoS-safe regular expressions.  All detection and redaction is done
in pure Python (stdlib only) — no network calls, no ML models, no extra package
required.

### Supported kinds

| Kind | Pattern notes |
|---|---|
| `email` | RFC-5321 local-part + domain; supports subdomains and plus-tags |
| `phone` | International (+ country code) and domestic with spaces/dashes/parens |
| `credit_card` | 16-digit (4-4-4-4 Visa/MC/Discover) and 15-digit (4-6-5 Amex); Luhn checksum gate (no false positives) |
| `ssn` | `xxx-xx-xxxx` dash format only — arbitrary 9-digit runs are ignored |
| `ip` | IPv4 dotted-quad; each octet constrained to 0–255. **IPv6 is out of scope.** |

`detect_pii()` returns a **non-overlapping** match list — when patterns overlap a
span, the more-specific kind wins (`credit_card > ssn > ip > email > phone`).

### Redaction strategies

| Strategy | Behaviour | Example result |
|---|---|---|
| `"redact"` (default) | Replace with `[REDACTED_<KIND>]` | `[REDACTED_EMAIL]` |
| `"mask"` | Keep last 4 chars, prefix with `****` | `****1234` |
| `"hash"` | `[<KIND>:<sha256(salt+value)[:10]>]` — deterministic | `[EMAIL:a1b2c3d4e5]` |

All strategies are **idempotent**: replacement tokens do not match any PII
pattern, so applying redaction twice yields the same string.

!!! warning "Set a secret `hash_salt` in production"
    The `"hash"` strategy is irreversible **only** when `hash_salt` is a long
    random secret. The default `hash_salt=""` is unsalted and brute-forceable for
    enumerable PII (e.g. phone numbers), and emits a runtime warning. Always pass
    a secret salt when using `strategy="hash"`.

### Wiring via middleware (prompt + result)

```python
from swarmline.agent.config import AgentConfig
from swarmline.agent.middleware import PiiMiddleware

agent = Agent(AgentConfig(
    system_prompt="You are helpful.",
    middleware=(
        PiiMiddleware(
            strategy="redact",   # "redact" | "mask" | "hash"
            kinds=["email", "ssn"],  # None = all five kinds
            redact_input=True,   # redact the user prompt in before_query
            redact_output=True,  # redact result.text in after_result
            hash_salt="",        # set to a long random secret when strategy="hash"
        ),
    ),
))
```

`PiiMiddleware.before_query` redacts the prompt string before it is sent to the
LLM.  `PiiMiddleware.after_result` redacts `result.text` via
`dataclasses.replace` (the frozen `Result` is never mutated).

**Note:** `result.structured_output` is intentionally not redacted by the
middleware — it is a validated domain object.  Apply redaction at the
application layer if structured fields contain PII.

### Wiring via input filter (full message history + system prompt)

Use `PiiInputFilter` to redact the entire conversation history and system
prompt before each LLM call.  Wire it through `RuntimeConfig.input_filters`:

```python
from swarmline.pii import PiiInputFilter
from swarmline.runtime.types import RuntimeConfig

config = RuntimeConfig(
    runtime_name="thin",
    input_filters=[PiiInputFilter(strategy="mask", kinds=["email", "phone"])],
)
```

`PiiInputFilter` implements the `InputFilter` protocol and applies
`dataclasses.replace` on each frozen `Message` object — no mutation.

### Low-level API

```python
from swarmline.pii import detect_pii, redact_pii

# Detect spans
matches = detect_pii("Call +1 (800) 555-1234", kinds=["phone"])
# [PiiMatch(kind='phone', start=5, end=22, value='+1 (800) 555-1234')]

# Redact (default strategy: "redact")
clean = redact_pii("My SSN is 123-45-6789")
# "My SSN is [REDACTED_SSN]"

# Mask (keep last 4)
masked = redact_pii("Card: 4111 1111 1111 1111", strategy="mask", kinds=["credit_card"])
# "Card: ****1111"

# Hash (deterministic, salted)
hashed = redact_pii("user@example.com", strategy="hash", hash_salt="secret")
# "[EMAIL:7a3f9c1d2b]"
```

### Optional Presidio backend

For higher-recall, ML-assisted detection (names, addresses, custom entities)
install the `pii` extra:

```bash
pip install "swarmline[pii]"
```

This makes `presidio-analyzer` and `presidio-anonymizer` available.  The
`detect_pii_presidio()` function in `swarmline.pii` is a staged stub that
raises `ImportError("install swarmline[pii]")` when the packages are absent.
Full Presidio integration (kind → entity-type mapping) is planned; the stdlib
regex core remains the default and requires no extra installation.
