# cognitia (DEPRECATED)

**This package has been renamed to [swarmline](https://pypi.org/project/swarmline/).**

## Migration

```bash
pip uninstall cognitia
pip install swarmline
```

Then update your imports:

```python
# Before
from cognitia import Agent, AgentConfig

# After
from swarmline import Agent, AgentConfig
```

## About

This package is a thin wrapper that re-exports `swarmline` for backward compatibility.
It will not receive any new features. Please migrate to `swarmline`.
