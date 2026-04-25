"""Pytest bootstrap — guarantee project-local src/ takes priority over any
external `swarmline` editable installations.

Why:
    The developer's pyenv site-packages contains editable .pth entries from
    sibling projects (e.g. /Apps/taskloom/packages/swarmline, /Apps/cognitia)
    which also expose a top-level `swarmline` package. Without this shim,
    `import swarmline` may resolve to one of those instead of the project
    being tested, breaking Sprint 1A meta-tests like
    `test_tool_function_protocol.py` whose contract depends on the `tool_protocol`
    module identity matching the `swarmline.agent` re-export.

What:
    Insert `<repo>/src` at sys.path[0] (idempotently) before pytest collects
    or imports anything else. CI environments do not have these collisions,
    so this is a no-op there.
"""

from __future__ import annotations

import sys
from pathlib import Path

_LOCAL_SRC = (Path(__file__).resolve().parent / "src").as_posix()
if _LOCAL_SRC in sys.path:
    sys.path.remove(_LOCAL_SRC)
sys.path.insert(0, _LOCAL_SRC)
