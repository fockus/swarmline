"""Unit: swarmline init CLI command — project scaffolding."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from swarmline.cli._app import cli


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _invoke(runner: CliRunner, args: list[str]) -> object:
    return runner.invoke(cli, args, catch_exceptions=False)


def _project_files(base: Path) -> set[str]:
    """Return relative paths of all files in project dir."""
    return {str(p.relative_to(base)) for p in base.rglob("*") if p.is_file()}


# ---------------------------------------------------------------------------
# Basic creation
# ---------------------------------------------------------------------------


class TestInitBasic:

    def test_creates_directory(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = _invoke(runner, ["init", "my-agent"])
            assert result.exit_code == 0
            assert (Path("my-agent")).is_dir()

    def test_creates_agent_py(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            _invoke(runner, ["init", "my-agent"])
            assert Path("my-agent/agent.py").exists()

    def test_creates_config_yaml(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            _invoke(runner, ["init", "my-agent"])
            assert Path("my-agent/config.yaml").exists()

    def test_creates_test_file(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            _invoke(runner, ["init", "my-agent"])
            assert Path("my-agent/tests/test_agent.py").exists()

    def test_creates_env_example(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            _invoke(runner, ["init", "my-agent"])
            assert Path("my-agent/.env.example").exists()

    def test_creates_pyproject_toml(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            _invoke(runner, ["init", "my-agent"])
            assert Path("my-agent/pyproject.toml").exists()

    def test_creates_readme(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            _invoke(runner, ["init", "my-agent"])
            assert Path("my-agent/README.md").exists()

    def test_output_contains_project_name(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = _invoke(runner, ["init", "my-agent"])
            assert "my-agent" in result.output

    def test_output_contains_next_steps(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = _invoke(runner, ["init", "my-agent"])
            assert "cd my-agent" in result.output


# ---------------------------------------------------------------------------
# Name injection
# ---------------------------------------------------------------------------


class TestInitNameInjection:

    def test_agent_name_in_agent_py(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            _invoke(runner, ["init", "cool-bot"])
            content = Path("cool-bot/agent.py").read_text()
            assert "cool-bot" in content or "cool_bot" in content

    def test_agent_name_in_config_yaml(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            _invoke(runner, ["init", "my-project"])
            content = Path("my-project/config.yaml").read_text()
            assert "my-project" in content or "my_project" in content

    def test_agent_name_in_readme(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            _invoke(runner, ["init", "super-agent"])
            content = Path("super-agent/README.md").read_text()
            assert "super-agent" in content

    def test_agent_name_in_pyproject(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            _invoke(runner, ["init", "mybot"])
            content = Path("mybot/pyproject.toml").read_text()
            assert "mybot" in content


# ---------------------------------------------------------------------------
# --runtime flag
# ---------------------------------------------------------------------------


class TestInitRuntime:

    def test_default_runtime_is_thin(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            _invoke(runner, ["init", "bot"])
            content = Path("bot/config.yaml").read_text()
            assert "thin" in content

    def test_runtime_claude(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            _invoke(runner, ["init", "bot", "--runtime", "claude"])
            content = Path("bot/config.yaml").read_text()
            assert "claude" in content

    def test_runtime_invalid_rejected(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["init", "bot", "--runtime", "gpt99"])
            assert result.exit_code != 0


# ---------------------------------------------------------------------------
# --memory flag
# ---------------------------------------------------------------------------


class TestInitMemory:

    def test_default_memory_is_inmemory(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            _invoke(runner, ["init", "bot"])
            content = Path("bot/config.yaml").read_text()
            assert "inmemory" in content or "in_memory" in content or "memory: false" in content

    def test_memory_sqlite(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            _invoke(runner, ["init", "bot", "--memory", "sqlite"])
            content = Path("bot/config.yaml").read_text()
            assert "sqlite" in content

    def test_memory_invalid_rejected(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["init", "bot", "--memory", "redis"])
            assert result.exit_code != 0


# ---------------------------------------------------------------------------
# --full flag
# ---------------------------------------------------------------------------


class TestInitFull:

    def test_full_creates_dockerfile(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            _invoke(runner, ["init", "bot", "--full"])
            assert Path("bot/Dockerfile").exists()

    def test_full_creates_docker_compose(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            _invoke(runner, ["init", "bot", "--full"])
            assert Path("bot/docker-compose.yml").exists()

    def test_full_creates_skills_dir(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            _invoke(runner, ["init", "bot", "--full"])
            assert Path("bot/skills").is_dir()

    def test_full_enables_sqlite_memory(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            _invoke(runner, ["init", "bot", "--full"])
            content = Path("bot/config.yaml").read_text()
            assert "sqlite" in content

    def test_full_has_more_files_than_minimal(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            _invoke(runner, ["init", "minimal"])
            _invoke(runner, ["init", "full", "--full"])
            minimal_files = _project_files(Path("minimal"))
            full_files = _project_files(Path("full"))
            assert len(full_files) > len(minimal_files)


# ---------------------------------------------------------------------------
# --output flag
# ---------------------------------------------------------------------------


class TestInitOutput:

    def test_output_creates_in_target_dir(self, tmp_path: Path) -> None:
        runner = CliRunner()
        target = str(tmp_path / "projects")
        result = runner.invoke(cli, ["init", "bot", "--output", target])
        assert result.exit_code == 0
        assert (tmp_path / "projects" / "bot").is_dir()


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestInitErrors:

    def test_error_if_directory_exists(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            Path("bot").mkdir()
            result = runner.invoke(cli, ["init", "bot"])
            assert result.exit_code != 0
            assert "exists" in result.output.lower() or "already" in result.output.lower()

    def test_force_overwrites_existing(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            Path("bot").mkdir()
            result = runner.invoke(cli, ["init", "bot", "--force"])
            assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Content validity
# ---------------------------------------------------------------------------


class TestInitContentValidity:

    def test_agent_py_is_importable_syntax(self, tmp_path: Path) -> None:
        """Generated agent.py must be valid Python (parse without error)."""
        import ast

        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            _invoke(runner, ["init", "mybot"])
            source = Path("mybot/agent.py").read_text()
            tree = ast.parse(source)  # raises SyntaxError if invalid
            assert tree is not None

    def test_test_file_is_valid_python(self, tmp_path: Path) -> None:
        import ast

        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            _invoke(runner, ["init", "mybot"])
            source = Path("mybot/tests/test_agent.py").read_text()
            ast.parse(source)

    def test_config_yaml_is_valid_yaml(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            _invoke(runner, ["init", "mybot"])
            content = Path("mybot/config.yaml").read_text()
            # Simple check: no Python syntax, YAML-like key: value
            assert ":" in content
            assert not content.startswith("def ")

    def test_pyproject_toml_contains_swarmline(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            _invoke(runner, ["init", "mybot"])
            content = Path("mybot/pyproject.toml").read_text()
            assert "swarmline" in content
