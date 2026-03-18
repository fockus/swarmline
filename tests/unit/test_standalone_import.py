"""Smoke test: cognitia importable standalone (without freedom_agent in sys.path). Iteration 4: E2E-uroven - verify chto library not imeet obratnyh zavisimostey.
"""

from __future__ import annotations

import subprocess
import sys


class TestStandaloneImport:
    """cognitia mozhno importirovat without freedom_agent."""

    def test_import_cognitia_without_freedom_agent(self) -> None:
        """import cognitia works without freedom_agent in sys.path."""
        # Run subprocess gde freedom_agent NE dobavlen in PYTHONPATH
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys; "
                    "# Удаляем пути к freedom_agent из sys.path\n"
                    "sys.path = [p for p in sys.path if 'freedom_agent' not in p]; "
                    "import cognitia; "
                    "print('version:', cognitia.__version__); "
                    "print('protocols:', dir(cognitia)); "
                    "from cognitia.protocols import RuntimePort, RoleSkillsProvider, LocalToolResolver; "
                    "from cognitia.config import YamlRoleSkillsLoader, load_role_router_config; "
                    "from cognitia.runtime.ports.base import BaseRuntimePort, StreamEvent; "
                    "from cognitia.bootstrap import CognitiaStack; "
                    "print('OK')"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert (
            result.returncode == 0
        ), f"Import failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        assert "OK" in result.stdout

    def test_no_reverse_dependency_in_source(self) -> None:
        """Ishodnyy kod cognitia not contains imports from freedom_agent."""
        import pathlib

        cognitia_src = pathlib.Path(__file__).parent.parent.parent / "src" / "cognitia"
        violations: list[str] = []

        for py_file in cognitia_src.rglob("*.py"):
            content = py_file.read_text(encoding="utf-8")
            for i, line in enumerate(content.splitlines(), 1):
                stripped = line.strip()
                # Propuskaem kommentarii
                if stripped.startswith("#"):
                    continue
                if "freedom_agent" in stripped:
                    violations.append(f"{py_file.relative_to(cognitia_src)}:{i}: {stripped}")

        assert (
            violations == []
        ), "Найдены обратные зависимости cognitia → freedom_agent:\n" + "\n".join(violations)

    def test_no_domain_leaks(self) -> None:
        """cognitia not contains domain-specific strok (PF5, finance, Freedom)."""
        import pathlib

        cognitia_src = pathlib.Path(__file__).parent.parent.parent / "src" / "cognitia"
        domain_terms = {"PF5", "finance", "Freedom"}
        violations: list[str] = []

        for py_file in cognitia_src.rglob("*.py"):
            content = py_file.read_text(encoding="utf-8")
            for i, line in enumerate(content.splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                for term in domain_terms:
                    if term in stripped and not stripped.startswith("# "):
                        violations.append(
                            f"{py_file.relative_to(cognitia_src)}:{i}: [{term}] {stripped}"
                        )

        assert violations == [], "Найдены domain-specific утечки в cognitia:\n" + "\n".join(
            violations
        )
