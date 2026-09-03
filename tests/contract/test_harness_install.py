from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_TOOLS = [
    "blender_read",
    "blender_patch",
    "blender_acknowledge",
    "blender_verify",
]


def _module(name: str, relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_install_contract_requires_user_confirmed_project_directory() -> None:
    contract = json.loads((ROOT / "install-contract.json").read_text(encoding="utf-8"))

    assert contract["schema_version"] == 1
    assert contract["components"] == {
        "skills": ["blender-vse"],
        "mcp_servers": ["blender-vse-control"],
        "mcp_tools": EXPECTED_TOOLS,
    }
    assert set(contract["states"]) == {"installed", "ready"}
    assert contract["workflow"][2] == "detect_or_request_workspace"
    assert contract["workflow"][3] == "ask_user_to_confirm_projects_dir"
    assert contract["workflow"][-1].endswith("effective_directory")
    storage = contract["project_storage"]
    assert storage["variable"] == "BLENDER_VSE_PROJECTS_DIR"
    assert storage["required_after_install"] is True
    assert storage["must_be_absolute"] is True
    assert storage["never_use_plugin_cache"] is True
    assert "项目" in storage["prompt_zh_CN"]
    workspace = contract["workspace_policy"]
    assert workspace["workspace_preferred"] is True
    assert workspace["recommended_relative_projects_dir"] == "blender-vse-projects"
    assert workspace["external_projects_allowed_after_confirmation"] is True
    assert workspace["never_move_existing_files_implicitly"] is True
    python_runtime = contract["runtime"]["python"]
    assert python_runtime["strategy"] == "uv-managed"
    assert python_runtime["version"] == "3.12"
    assert python_runtime["system_python_required"] is False
    assert python_runtime["uv_preinstalled_required"] is False
    assert (
        python_runtime["if_uv_missing"]
        == "request_permission_then_install_from_official_source"
    )
    assert contract["runtime"]["blender"]["installation"] == "guided"
    assert contract["runtime"]["ffmpeg"]["installation"] == "guided"
    assert set(contract["clients"]) == {"codex", "claude-code", "dsh"}
    assert all(
        client["ready_requires_project_directory"]
        for client in contract["clients"].values()
    )
    assert all(
        client["ready_requires_workspace_advisory_resolved"]
        for client in contract["clients"].values()
    )


def test_codex_windows_environment_guidance_requires_full_app_restart() -> None:
    english = (ROOT / "docs" / "installation.md").read_text(encoding="utf-8")
    chinese = (ROOT / "docs" / "installation_zh-CN.md").read_text(
        encoding="utf-8"
    )
    assert "opening a new task alone does not refresh" in english
    assert "Fully exit and relaunch Codex" in english
    assert "只新建任务不会刷新父进程环境" in chinese
    assert "完整退出并重新启动 Codex" in chinese


def test_claude_marketplace_and_manifest_share_the_root_plugin() -> None:
    marketplace = json.loads(
        (ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
    )
    manifest = json.loads(
        (ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )

    assert marketplace["name"] == "blender-vse"
    assert marketplace["owner"]["name"] == "Aoike"
    assert len(marketplace["plugins"]) == 1
    entry = marketplace["plugins"][0]
    assert entry["name"] == manifest["name"] == "blender-vse"
    assert entry["source"] == {
        "source": "url",
        "url": "https://github.com/Aoike123/blender-vse-control.git",
        "ref": "main",
    }
    assert manifest["skills"] == "./skills/"
    assert manifest["mcpServers"] == "./clients/claude/mcp.json"
    assert manifest["version"] == "0.1.0"
    codex_manifest = json.loads(
        (ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    assert manifest["version"] == codex_manifest["version"]

    projects = manifest["userConfig"]["projects_dir"]
    assert projects["type"] == "directory"
    assert projects["required"] is True
    assert "project" in projects["description"].lower()


def test_claude_mcp_config_uses_native_root_and_user_config_substitution() -> None:
    config = json.loads(
        (ROOT / "clients" / "claude" / "mcp.json").read_text(encoding="utf-8")
    )
    assert set(config["mcpServers"]) == {"blender-vse-control"}
    server = config["mcpServers"]["blender-vse-control"]

    assert set(server) == {"type", "command", "args", "env"}
    assert server["type"] == "stdio"
    assert server["command"] == "uv"
    assert server["args"] == [
        "run",
        "--no-project",
        "--managed-python",
        "--python",
        "3.12",
        "--with",
        "mcp==2.1.1",
        "python",
        "${CLAUDE_PLUGIN_ROOT}/scripts/run_plugin_mcp.py",
    ]
    assert server["env"] == {
        "BLENDER_VSE_PROJECTS_DIR": "${user_config.projects_dir}",
        "BLENDER_VSE_ALLOWED_ROOTS": "${user_config.projects_dir}",
    }


def test_dsh_patch_generator_binds_one_server_to_the_selected_directory(
    tmp_path: Path,
) -> None:
    generator = _module("dsh_config", "scripts/print_dsh_config.py")
    workspace = (tmp_path / "workspace").resolve()
    projects = workspace / "项目 files"
    shared = (tmp_path / "shared edits").resolve()
    patch = generator.build_patch(
        plugin_root=ROOT,
        projects_dir=projects,
        workspace_root=workspace,
        allow_external_projects=True,
        allowed_roots=[projects, shared],
    )

    assert len(patch) == 1 and set(patch[0]) == {"insert"}
    assert len(patch[0]["insert"]) == 1
    row = patch[0]["insert"][0]
    assert row["id"] == "mcp-blender-vse-control"
    assert row["name"] == "@deepseek-ai/dsh-mcp-client"
    config = row["config"]
    assert config["serverName"] == "blender-vse-control"
    assert config["transport"] == "stdio"
    assert config["command"] == "uv"
    assert "--managed-python" in config["args"]
    assert config["args"][config["args"].index("--python") + 1] == "3.12"
    assert Path(config["cwd"]).samefile(ROOT)
    assert Path(config["args"][-1]).samefile(ROOT / "scripts" / "run_plugin_mcp.py")
    assert config["env"] == {
        "BLENDER_VSE_PROJECTS_DIR": str(projects),
        "BLENDER_VSE_ALLOWED_ROOTS": os.pathsep.join((str(projects), str(shared))),
    }
    assert config["failOnStartupError"] is True

    rendered = generator.render_patch(patch)
    assert json.loads(rendered) == patch


def test_dsh_patch_generator_rejects_relative_project_directory() -> None:
    generator = _module("dsh_config_invalid", "scripts/print_dsh_config.py")
    with pytest.raises(ValueError, match="absolute"):
        generator.build_patch(
            plugin_root=ROOT,
            projects_dir=Path("relative-projects"),
        )


def test_dsh_patch_generator_requires_workspace_or_external_confirmation(
    tmp_path: Path,
) -> None:
    generator = _module("dsh_config_workspace", "scripts/print_dsh_config.py")
    with pytest.raises(ValueError, match="allow-external-projects"):
        generator.build_patch(
            plugin_root=ROOT,
            projects_dir=(tmp_path / "external").resolve(),
            workspace_root=None,
        )


def test_dsh_installer_stops_at_installed_until_user_selects_directory(
    tmp_path: Path,
) -> None:
    installer = _module("dsh_installer", "scripts/install_dsh.py")
    dsh_home = tmp_path / "dsh-home"
    result = installer.install(dsh_home=dsh_home, apply=True)

    assert result["status"] == "installed"
    assert result["ready"] is False
    assert result["next_action"] == "ask_user_for_workspace_and_projects_dir"
    assert result["required_variable"] == "BLENDER_VSE_PROJECTS_DIR"
    target = dsh_home / "skills" / "blender-vse"
    assert (target / "SKILL.md").is_file()
    assert (target / "references" / "command-index.json").is_file()
    assert result["mcp_patch"]["path"] is None


def test_dsh_installer_configures_but_does_not_claim_ready_before_activation(
    tmp_path: Path,
) -> None:
    installer = _module("dsh_installer_ready", "scripts/install_dsh.py")
    dsh_home = tmp_path / "dsh-home"
    workspace = (tmp_path / "workspace").resolve()
    projects = workspace / "blender-vse-projects"
    result = installer.install(
        dsh_home=dsh_home,
        projects_dir=projects,
        workspace_root=workspace,
        apply=True,
    )

    assert result["status"] == "configured"
    assert result["ready"] is False
    patch = Path(result["mcp_patch"]["path"])
    assert patch.is_file()
    payload = json.loads(patch.read_text(encoding="utf-8"))
    environment = payload[0]["insert"][0]["config"]["env"]
    assert environment["BLENDER_VSE_PROJECTS_DIR"] == str(projects)
    assert environment["BLENDER_VSE_ALLOWED_ROOTS"] == str(projects)


def test_dsh_installer_dry_run_never_writes(tmp_path: Path) -> None:
    installer = _module("dsh_installer_dry", "scripts/install_dsh.py")
    dsh_home = tmp_path / "dsh-home"
    workspace = (tmp_path / "workspace").resolve()
    result = installer.install(
        dsh_home=dsh_home,
        projects_dir=workspace / "blender-vse-projects",
        workspace_root=workspace,
        apply=False,
    )
    assert result["status"] == "planned"
    assert result["ready"] is False
    assert result["applied"] is False
    assert result["next_action"] == "review_then_rerun_with_apply"
    assert not dsh_home.exists()


def test_dsh_installer_warns_before_using_directory_outside_workspace(
    tmp_path: Path,
) -> None:
    installer = _module("dsh_installer_workspace_warning", "scripts/install_dsh.py")
    workspace = (tmp_path / "workspace").resolve()
    external = (tmp_path / "external-projects").resolve()
    result = installer.install(
        dsh_home=tmp_path / "dsh-home",
        projects_dir=external,
        workspace_root=workspace,
        apply=True,
    )

    assert result["status"] == "installed"
    assert result["ready"] is False
    assert result["mcp_patch"]["path"] is None
    assert result["next_action"] == "confirm_workspace_or_allow_external_projects"
    assert result["workspace_advice"]["confirmation_required"] is True


def test_dsh_installer_accepts_explicit_external_directory_confirmation(
    tmp_path: Path,
) -> None:
    installer = _module("dsh_installer_workspace_override", "scripts/install_dsh.py")
    workspace = (tmp_path / "workspace").resolve()
    external = (tmp_path / "external-projects").resolve()
    result = installer.install(
        dsh_home=tmp_path / "dsh-home",
        projects_dir=external,
        workspace_root=workspace,
        allow_external_projects=True,
        apply=True,
    )

    assert result["status"] == "configured"
    assert Path(result["mcp_patch"]["path"]).is_file()
    assert result["workspace_advice"]["advisory_code"] == (
        "projects_dir_outside_workspace"
    )


def test_installation_docs_define_installed_and_ready_as_distinct_states() -> None:
    guide = (ROOT / "docs" / "installation.md").read_text(encoding="utf-8")
    assert "installed" in guide
    assert "ready" in guide
    assert "BLENDER_VSE_PROJECTS_DIR" in guide
    assert "Codex" in guide and "Claude Code" in guide and "DSH" in guide
    assert "plugin cache" in guide.lower()
    assert "Do not assume that Python or `uv` is already installed" in guide
    assert "official Blender download" in guide
    assert "official FFmpeg download" in guide
