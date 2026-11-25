"""Architecture contract: the Domain layer must not import Infrastructure.

Clean Architecture invariant — dependency direction is
Infrastructure -> Application -> Domain, never reversed. The Domain contracts
(``swarmline.protocols`` package + the pure value module ``domain_types``) must
not contain *runtime-level* imports that reach into Infrastructure
(``swarmline.runtime``, ``swarmline.tools``) or the multi-agent feature package
(``swarmline.multi_agent``). Type-only imports guarded by ``TYPE_CHECKING`` and
lazy imports inside functions are allowed.

This is a static (AST) guard so it is immune to the eager public-API loading in
``swarmline/__init__.py`` (a separate concern): it inspects source, not
``sys.modules``.

Regression guard for the 2026-06-29 dual-model review CRITICALs:
- ``protocols/host_adapter.py`` imported ``LifecycleMode`` from
  ``multi_agent.graph_types`` at module level;
- ``protocols/multi_agent.py`` imported ``TaskFilter/TaskItem`` from
  ``multi_agent.task_types`` at module level;
- ``multi_agent/agent_tool.py`` imported ``ToolSpec/Message`` from the
  ``swarmline.runtime.types`` re-export instead of their ``domain_types`` home.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import swarmline

_SRC = Path(swarmline.__file__).parent
_PROTOCOLS = sorted(
    p for p in (_SRC / "protocols").glob("*.py") if p.name != "__init__.py"
)

_FORBIDDEN = ("swarmline.runtime", "swarmline.tools", "swarmline.multi_agent")


def _is_type_checking(test: ast.expr) -> bool:
    """True for ``if TYPE_CHECKING:`` / ``if typing.TYPE_CHECKING:``."""
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    if isinstance(test, ast.Attribute):
        return test.attr == "TYPE_CHECKING"
    return False


def _runtime_level_imports(path: Path) -> list[tuple[str, int]]:
    """Module-level import targets, skipping TYPE_CHECKING blocks and function bodies.

    Lazy imports inside functions/classes are intentionally ignored (allowed
    pattern); only top-level (executed at import time) imports are collected.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[tuple[str, int]] = []

    def visit(body: list[ast.stmt]) -> None:
        for node in body:
            if isinstance(node, ast.If):
                if _is_type_checking(node.test):
                    continue  # type-only imports — allowed
                visit(node.body)
                visit(node.orelse)
            elif isinstance(node, ast.ImportFrom) and node.module:
                found.append((node.module, node.lineno))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    found.append((alias.name, node.lineno))
            # FunctionDef / AsyncFunctionDef / ClassDef bodies are not descended:
            # lazy imports inside them run only when called, not at import time.

    visit(tree.body)
    return found


def _violations(path: Path, forbidden: tuple[str, ...]) -> list[str]:
    return [
        f"{path.name}:{lineno} imports {module}"
        for module, lineno in _runtime_level_imports(path)
        if module.startswith(forbidden)
    ]


@pytest.mark.parametrize("path", _PROTOCOLS, ids=lambda p: p.name)
def test_protocol_module_has_no_infrastructure_import(path: Path) -> None:
    """No protocols/ module may import Infrastructure or the multi_agent feature at runtime."""
    violations = _violations(path, _FORBIDDEN)
    assert violations == [], (
        "Domain contract imports Infrastructure/feature at module level "
        f"(Clean Architecture violation): {violations}"
    )


def test_domain_types_is_infrastructure_free() -> None:
    """domain_types.py (pure value types) must not import Infrastructure at runtime."""
    path = _SRC / "domain_types.py"
    violations = _violations(path, _FORBIDDEN)
    assert violations == [], f"domain_types.py imports Infrastructure: {violations}"


def test_agent_tool_depends_on_domain_not_runtime_reexport() -> None:
    """agent_tool.py must take ToolSpec/Message from domain_types, not the runtime re-export (DIP)."""
    path = _SRC / "multi_agent" / "agent_tool.py"
    violations = _violations(path, ("swarmline.runtime",))
    assert violations == [], (
        "multi_agent/agent_tool.py imports from Infrastructure at module level "
        f"(should use swarmline.domain_types): {violations}"
    )
