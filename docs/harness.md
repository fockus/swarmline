# Composable Agent Harness

The harness is a single declarative model for assembling an agent: kernel,
optional multi-agent composition, optional infrastructure (checkpointing,
event recording, replay), middleware, tools, and memory. Two front-ends
compile into the exact same spec — an SDK builder and a YAML pipeline file
— and named presets expand into it too. A minimal spec (kernel only) builds
a simple agent with zero composition/infra overhead; a fuller spec builds a
supervised, durable multi-agent system. Either way, the output is the
**existing** `swarmline.agent.Agent` — nothing new to learn on the consuming
side, and nothing about `Agent`, `AgentConfig`, or `SwarmlineStack` changes
because the harness exists.

```
   SDK builder  ─┐
   YAML pipeline ─┼──► HarnessSpec (frozen, single source of truth) ──► HarnessBuilder.build()
   preset name  ─┘                                                          │
                                                                             ▼
                                                                           Agent
                                                          (existing interface — embed as-is)
```

## The spec

```python
from swarmline.harness import CompositionSpec, HarnessSpec, InfraSpec, WorkerSpec

HarnessSpec(
    kernel="react",                       # key in the kernel registry
    composition=None,                     # CompositionSpec | None — supervisor/graph
    infra=None,                           # InfraSpec | None — checkpoint/events/replay
    middleware=(),
    tools=(),
    memory=None,
    preset=None,                          # informational preset name, see below
)
```

`HarnessSpec()` — every field defaulted — is a solo ReAct agent. `composition`
and `infra` left `None` are never even consulted by the builder: a minimal
spec pays zero composition/infra overhead.

## SDK builder

```python
from swarmline.harness.builder import HarnessBuilder

agent = HarnessBuilder().kernel("react").build()
```

Fluent methods (`kernel`, `supervisor`, `with_checkpointing`, `with_events`)
accumulate a `HarnessSpec`; `build()` resolves it into an `Agent`.

## YAML pipeline

```python
from swarmline.harness.builder import HarnessBuilder
from swarmline.harness.yaml_loader import load_harness_yaml

spec = load_harness_yaml("pipeline.yaml")
agent = HarnessBuilder.from_spec(spec).build()
```

```yaml
# pipeline.yaml
kernel: react
composition:
  mode: supervisor
  blackboard: true
  workers:
    - role: researcher
      kernel: react
    - role: coder
      kernel: react
infra:
  checkpoint: true
```

An SDK call and a YAML file describing the same composition produce
`==`-equal `HarnessSpec` instances (single source of truth — no parallel
resolution logic) and therefore build equivalent agents.

## Presets

```python
from swarmline.harness.presets import get_preset_registry

spec = get_preset_registry().expand("simple-react")
```

Three built-ins, each a documented, named bundle:

| Preset | Expands to |
|---|---|
| `simple-react` | `HarnessSpec(kernel="react")` — solo agent, no composition/infra |
| `supervisor-team` | supervisor + `researcher`/`coder`/`reviewer` workers, blackboard on |
| `research-fanout` | supervisor + 3 parallel `researcher-1/2/3` workers, blackboard on |

`preset: <name>` is also a valid YAML top-level key and a `HarnessSpec.preset`
field — an unknown name is rejected with a named error the same way an
unknown kernel or composition block is (see [Validation](#validation) below).
It does not auto-expand into `composition`/`infra` on that spec; call
`PresetRegistry.expand(name)` to get the full, buildable spec.

## Graph composition

*Not to be confused with [Orchestration](orchestration.md)'s `swarmline.multi_agent`
org-chart graphs — this section is the harness's own `composition.mode: "graph"`
block, a declarative topology of harness workers, unrelated to that module.*

A `graph` composition declares a small multi-agent pipeline as data — workers
plus an optional topology (`edges`, `parallel` fan-out groups, `routes`
state-key branching) — instead of hand-wiring
`swarmline.orchestration.workflow_graph.WorkflowGraph`. Every topology field
defaults to empty; with none declared, the workers chain linearly, in
declaration order, ending at the `"END"` sentinel.

```python
from swarmline.harness.builder import HarnessBuilder
from swarmline.harness.spec import WorkerSpec

agent = (
    HarnessBuilder()
    .graph(
        (
            WorkerSpec(role="researcher", kernel="react"),
            WorkerSpec(role="writer", kernel="adapt"),
        )
    )
    .build()
)
```

The same topology as YAML — an SDK call and a YAML file describing it
produce `==`-equal `HarnessSpec` instances, exactly like every other
composition mode:

```yaml
# graph_pipeline.yaml
kernel: react
composition:
  mode: graph
  workers:
    - role: researcher
      kernel: react
    - role: writer
      kernel: adapt
```

**Bootstrapping "graph" — an explicit, one-time call.** Unlike every example
above, this one needs one extra line before `.build()` succeeds: the "graph"
composition block is real and wired, but it is registered explicitly, not as
an import side effect (same registry seam the [Validation](#validation)
section below documents for every composition mode):

```python
from swarmline.orchestration.graph_harness_composition import (
    register_graph_composition,
)

register_graph_composition()  # idempotent — call once, e.g. at app bootstrap
```

Skip that call and `.build()` raises `CompositionBlockNotFound` naming
`"graph"` — the same honest, fail-loud shape the deferred `supervisor` block
below raises for `"supervisor"`. The difference: once `"graph"` is
registered, `.build()` returns a genuinely **live** graph-composed `Agent`
right now — there is no I-052-style backlog item left pending for graph mode,
because the resolved factory is the existing `WorkflowGraph` class, reused
as-is (no new orchestration engine).

**Fan-out and join** — a `parallel` group runs its members concurrently off
a shared upstream output and joins on `then`, which sees every member's
output:

```python
from swarmline.harness.spec import ParallelSpec

agent = (
    HarnessBuilder()
    .graph(
        (
            WorkerSpec(role="r1", kernel="react"),
            WorkerSpec(role="r2", kernel="adapt"),
            WorkerSpec(role="r3", kernel="reflection"),
            WorkerSpec(role="synth", kernel="planner"),
        ),
        parallel=(ParallelSpec(members=("r1", "r2", "r3"), then="synth"),),
    )
    .build()
)
```

**Declarative routing** — `routes` express state-key branching as data, no
callables, so a route works loaded straight from YAML:

```python
from swarmline.harness.spec import RouteSpec

agent = (
    HarnessBuilder()
    .graph(
        (
            WorkerSpec(role="reviewer", kernel="react"),
            WorkerSpec(role="publisher", kernel="adapt"),
        ),
        routes=(
            RouteSpec(
                source="reviewer",
                key="last_output",
                mapping=(("approve", "publisher"),),
                default="END",
            ),
        ),
    )
    .build()
)
```

After `reviewer` runs, the route reads `state["last_output"]`: `"approve"`
sends the run to `publisher`; any other value falls to the declared
`default` — here `"END"`, ending the run right after `reviewer`. Omitting
`default` and landing on an unmapped value (or a state missing the key
entirely) ends the run with a terminal error event naming the routing node
and the key, instead of silently guessing a target.

**State convention.** Every graph run seeds `state["input"]` from the
prompt and threads it through each node (prompt-chaining: a node's task is
its predecessor's output, or the seed if it has none). The final answer is
the terminal node's own output; the *full* state — every node's output — is
attached as structured metadata:

```python
result = await agent.query("...")
result.text                              # the terminal node's output
result.native_metadata["graph_state"]
# {"input": str, "outputs": {role: str, ...}, "last_output": str, "last_role": str}
```

**Live per-node progress.** `agent.stream()` yields a `status` event as
execution enters and leaves each node — not batched after the fact — so a
multi-minute run is observable, not a dead screen, before the terminal
event:

```python
async for event in agent.stream("..."):
    if event.type == "status":
        print(event.text)  # "researcher: started", "researcher: finished", ...
```

**v1 limitations**, enforced fail-loud at `build()` time, before anything
runs: topologies are DAG-only (a declared cycle is rejected, naming it);
per-worker `tools` are not yet threaded (a graph worker declaring `tools`
is rejected, naming the worker); one model per worker, pinned via its own
`kernel` (no separate per-node model override); every unknown reference,
duplicate role, multi-successor node, or unreachable worker is rejected by
name rather than surfacing as silent misbehavior at run time.

## Validation

Any spec, from any front-end, that references an unknown kernel, preset,
composition mode, worker kernel, or infra block is rejected by `build()`
with a clear, named error:

```python
from swarmline.harness.builder import HarnessBuilder
from swarmline.harness.spec import HarnessSpec
from swarmline.runtime.thin.kernels import KernelNotFound

try:
    HarnessBuilder().kernel("not-a-real-kernel").build()
except KernelNotFound as exc:
    print(exc)  # "No kernel registered for mode 'not-a-real-kernel'. Available modes: ..."
```

To validate a spec WITHOUT constructing a real `Agent` (e.g. a CI step that
checks a YAML pipeline before deploy), use the standalone validator:

```python
from swarmline.harness.validation import validate_harness_spec

validate_harness_spec(spec)  # raises the same named errors build() does
```

## Embedding in a downstream app (taskloom)

taskloom (or any downstream app) treats the harness purely as an agent
factory: build a spec, get back a plain `Agent`, embed it as an inner agent
— there is no taskloom-specific API surface here, `Agent` is the contract
(REQ-011/012).

**What builds today.** A composition-free spec — `simple-react`, or any
hand-written `HarnessSpec(kernel=...)` with `composition=None` — builds a
real `Agent` right now, through any of the three front-ends:

```python
from swarmline.harness.builder import HarnessBuilder
from swarmline.harness.presets import get_preset_registry

spec = get_preset_registry().expand("simple-react")
agent = HarnessBuilder.from_spec(spec).build()   # -> real, embeddable Agent
```

**The intended durable pattern.** taskloom's actual target shape is a
supervised team with checkpointing — a `supervisor-team` preset plus
`with_checkpointing()`:

```python
from swarmline.harness.builder import HarnessBuilder
from swarmline.harness.presets import get_preset_registry

spec = (
    HarnessBuilder
    .from_spec(get_preset_registry().expand("supervisor-team"))
    .with_checkpointing()
    .spec
)
# spec.composition.mode == "supervisor", spec.infra.checkpoint == True — a
# fully valid, well-formed HarnessSpec expressing the intended durable shape.

agent = HarnessBuilder.from_spec(spec).build()
```

**Honest current state:** that last `build()` call raises
`CompositionBlockNotFound`, naming `"supervisor"`. The supervisor composition
block (`swarmline.orchestration.supervisor`, H6) and the checkpoint infra
block are genuinely valid, existing pieces of swarmline — but neither is
wired into the harness's composition/infra registry seam yet (tracked as
backlog items I-052 and I-053). The harness does not fake a working durable
build in the meantime: it fails loud, naming exactly what is missing, which
is what [Validation](#validation) above is for.

**The one-line fix, once I-052/I-053 land**, is registration — no change to
this doc's example code, no change to `HarnessBuilder`:

```python
from swarmline.harness.registries import get_composition_registry, get_infra_registry

get_composition_registry().register("supervisor", supervisor_factory)
get_infra_registry().register("checkpoint", checkpoint_factory)
```

After that, the exact same `supervisor-team` + `with_checkpointing()` example
above builds a real, durable, supervised `Agent` with zero changes on the
taskloom side.

## See also

- [Runtimes](runtimes.md) — the underlying `ExecutionKernel` registry the
  harness's `kernel` field resolves through.
- [Orchestration](orchestration.md) — the H6 supervisor that will back the
  `supervisor` composition block once wired (I-052).
