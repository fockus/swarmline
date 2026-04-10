# Examples Smoke Coverage

- `examples/` are part of the release surface and need automated smoke coverage, not just manual runs.
- One-script smoke coverage was insufficient: `01_agent_basics.py` had already drifted into a broken offline path while CI stayed green.
- Parametric subprocess smoke over all runnable examples is cheap enough (`28 passed in 5.59s`) to keep as a default regression seam.
- For examples, the practical contract is simple: default invocation must exit `0`, keep `stderr` empty, and produce user-visible output.
