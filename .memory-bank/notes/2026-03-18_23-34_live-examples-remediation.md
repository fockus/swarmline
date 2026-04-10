# Live Examples Remediation

- Offline smoke is not enough for examples that advertise optional live modes; they also need degraded-mode checks (`--live` without credentials) and honest docs.
- `examples/19_cli_runtime.py` must show the same Claude NDJSON command contract as `docs/cli-runtime.md`, otherwise users copy a broken command shape.
- `examples/24_deep_research.py` is now explicit: default path is mock, `--live` is executable and guarded by `ANTHROPIC_API_KEY`.
- `examples/27_nano_claw.py` demo is now event-driven enough to demonstrate actual mock tool side-effects, not just canned assistant text.
- For streaming examples, middleware accuracy depends on preserving final-event metadata (`usage`, `total_cost_usd`) before constructing post-stream `Result`.
