from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _module(name: str, relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_portable_mcp_config_uses_absolute_launcher_and_standard_fields(
    tmp_path: Path,
) -> None:
    generator = _module("portable_mcp_config", "scripts/print_mcp_config.py")
    roots = [tmp_path / "one", tmp_path / "two"]
    config = generator.build_config(plugin_root=ROOT, allowed_roots=roots)
    server = config["mcpServers"]["blender-vse-control"]

    assert set(server) == {"type", "command", "args", "env"}
    assert server["type"] == "stdio" and server["command"] == "uv"
    assert "--managed-python" in server["args"]
    assert server["args"][server["args"].index("--python") + 1] == "3.12"
    assert Path(server["args"][-1]).is_absolute()
    assert Path(server["args"][-1]).samefile(ROOT / "scripts" / "run_plugin_mcp.py")
    assert server["env"]["BLENDER_VSE_ALLOWED_ROOTS"] == os.pathsep.join(
        str(path.resolve()) for path in roots
    )
    assert "default_tools_approval_mode" not in server
    assert "env_vars" not in server


def test_portable_mcp_config_sets_confirmed_project_directory(tmp_path: Path) -> None:
    generator = _module("portable_mcp_projects", "scripts/print_mcp_config.py")
    workspace = (tmp_path / "workspace").resolve()
    projects = workspace / "blender-vse-projects"
    config = generator.build_config(
        plugin_root=ROOT,
        projects_dir=projects,
        workspace_root=workspace,
    )
    environment = config["mcpServers"]["blender-vse-control"]["env"]

    assert environment == {
        "BLENDER_VSE_PROJECTS_DIR": str(projects),
        "BLENDER_VSE_ALLOWED_ROOTS": str(projects),
    }


def test_portable_mcp_config_requires_confirmation_without_workspace(
    tmp_path: Path,
) -> None:
    generator = _module("portable_mcp_workspace", "scripts/print_mcp_config.py")
    with pytest.raises(ValueError, match="allow-external-projects"):
        generator.build_config(
            plugin_root=ROOT,
            projects_dir=(tmp_path / "projects").resolve(),
        )
