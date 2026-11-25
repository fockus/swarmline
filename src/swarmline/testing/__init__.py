"""Testing utilities for swarmline.

Public surface:

* :class:`MockRuntime` — deterministic offline runtime for tests and examples.
* :class:`FunctionModel` — LLM test double backed by a user-supplied function.
* :class:`TestModel` — LLM test double with auto-generated tool args from JSON Schema.
"""

from __future__ import annotations

from swarmline.testing.mock_runtime import MockRuntime
from swarmline.testing.models import FunctionModel, TestModel

__all__ = ["FunctionModel", "MockRuntime", "TestModel"]
