# Runtime Registry

Thread-safe, extensible registry for runtime factories with plugin discovery via Python entry points.

## Built-in Runtimes

Three runtimes are registered automatically:

| Name | Class | Extra |
|------|-------|-------|
| `thin` | `ThinRuntime` | `swarmline[thin]` |
| `claude_sdk` | `ClaudeCodeRuntime` | `swarmline[claude]` |
| `deepagents` | `DeepAgentsRuntime` | `swarmline[deepagents]` |

## Using the Registry

```python
from swarmline.runtime.registry import get_default_registry

registry = get_default_registry()

# List available runtimes
registry.list_available()  # ["thin", "claude_sdk", "deepagents"]

# Check if registered
registry.is_registered("thin")  # True

# Get factory function
factory = registry.get("thin")

# Get capabilities
caps = registry.get_capabilities("thin")
```

## Registering a Custom Runtime

```python
from swarmline.runtime.registry import get_default_registry
from swarmline.runtime.capabilities import RuntimeCapabilities

def my_factory(config, **kwargs):
    return MyCustomRuntime(config=config, **kwargs)

caps = RuntimeCapabilities(streaming=True, tools=True)
get_default_registry().register("my_runtime", my_factory, capabilities=caps)

# Now usable in config:
config = RuntimeConfig(runtime_name="my_runtime", model="my-model")
```

## Plugin Discovery via Entry Points

Register your runtime as a Python package entry point for automatic discovery:

```toml
# pyproject.toml
[project.entry-points."swarmline.runtimes"]
my_runtime = "my_package.runtime:get_runtime"
```

The entry point must return a `tuple[factory_fn, RuntimeCapabilities]`:

```python
# my_package/runtime.py
from swarmline.runtime.capabilities import RuntimeCapabilities

def get_runtime():
    def factory(config, **kwargs):
        return MyRuntime(config=config, **kwargs)
    caps = RuntimeCapabilities(streaming=True, tools=True)
    return factory, caps
```

Invalid entry points are skipped with a warning — they don't break the registry.

## API Reference

| Method | Description |
|--------|-------------|
| `register(name, factory, capabilities)` | Register a runtime factory |
| `get(name)` | Get factory by name (raises `KeyError`) |
| `list_available()` | List all registered runtime names |
| `get_capabilities(name)` | Get `RuntimeCapabilities` for a runtime |
| `is_registered(name)` | Check if a runtime name is registered |
| `unregister(name)` | Remove a runtime (returns `bool`) |

### Helper Functions

```python
from swarmline.runtime.registry import (
    get_default_registry,       # singleton registry with built-ins
    reset_default_registry,     # reset to defaults (for testing)
    get_valid_runtime_names,    # shorthand for list_available()
)
```
