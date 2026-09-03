from __future__ import annotations

import importlib.util
import json
import zipfile
from pathlib import Path

import blender_vse

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / ".codex-plugin" / "plugin.json"
MCP_CONFIG = ROOT / ".mcp.json"
EXPECTED_TOOLS = {
    "blender_read",
    "blender_patch",
    "blender_acknowledge",
    "blender_verify",
}


def _load_builder():
    path = ROOT / "scripts" / "build_plugin.py"
    spec = importlib.util.spec_from_file_location("plugin_builder", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_plugin_manifest_matches_package_and_component_paths() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["name"] == "blender-vse"
    assert manifest["version"] == blender_vse.__version__
    assert (ROOT / manifest["skills"]).is_dir()
    assert (ROOT / manifest["mcpServers"]).is_file()
    assert manifest["license"] == "AGPL-3.0-only"
    assert manifest["repository"] == "https://github.com/Aoike123/blender-vse-control"
    interface = manifest["interface"]
    assert 1 <= len(interface["defaultPrompt"]) <= 3
    assert all(len(prompt) <= 128 for prompt in interface["defaultPrompt"])


def test_plugin_mcp_config_runs_local_source_with_safe_approvals() -> None:
    config = json.loads(MCP_CONFIG.read_text(encoding="utf-8"))
    assert set(config) == {"mcpServers"}
    assert set(config["mcpServers"]) == {"blender-vse-control"}
    server = config["mcpServers"]["blender-vse-control"]
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
        "scripts/run_plugin_mcp.py",
    ]
    package_metadata = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"mcp>=2.0,<3"' in package_metadata
    assert server["cwd"] == "."
    assert server["enabled"] is True
    assert server["default_tools_approval_mode"] == "approve"
    assert set(server["tools"]) == {"blender_patch", "blender_acknowledge"}
    assert all(
        settings == {"approval_mode": "prompt"} for settings in server["tools"].values()
    )
    inherited = set(server["env_vars"])
    assert len(inherited) == len(server["env_vars"])
    assert {"PATH", "UV_OFFLINE", "BLENDER_VSE_ALLOWED_ROOTS"} <= inherited
    assert not any(
        marker in name.upper()
        for name in inherited
        for marker in ("API_KEY", "PASSWORD", "SECRET", "TOKEN")
    )
    assert "BLENDER_VSE_ALLOW_DIRECT_MUTATION" not in inherited


def test_plugin_bundle_is_deterministic_and_allowlisted(tmp_path: Path) -> None:
    builder = _load_builder()
    first = builder.build(tmp_path / "first.zip")
    second = builder.build(tmp_path / "second.zip")
    assert first.read_bytes() == second.read_bytes()
    report = builder.verify(first)
    assert report["files"] >= 30
    assert report["marketplace"] == "blender-vse-local"
    with zipfile.ZipFile(first) as archive:
        names = set(archive.namelist())
        assert all(info.create_system == 3 for info in archive.infolist())
        assert all(
            info.date_time == (1980, 1, 1, 0, 0, 0) for info in archive.infolist()
        )
        assert b"\r\n" not in archive.read(
            "blender-vse-marketplace/plugins/blender-vse/skills/blender-vse/SKILL.md"
        )
    prefix = "blender-vse-marketplace/plugins/blender-vse"
    assert "blender-vse-marketplace/.agents/plugins/marketplace.json" in names
    assert f"{prefix}/.codex-plugin/plugin.json" in names
    assert f"{prefix}/.claude-plugin/plugin.json" in names
    assert f"{prefix}/.claude-plugin/marketplace.json" in names
    assert f"{prefix}/.mcp.json" in names
    assert f"{prefix}/assets/icon.png" in names
    assert f"{prefix}/assets/logo.png" in names
    assert f"{prefix}/assets/logo-dark.png" in names
    assert f"{prefix}/install-contract.json" in names
    assert f"{prefix}/clients/claude/mcp.json" in names
    assert f"{prefix}/skills/blender-vse/SKILL.md" in names
    assert f"{prefix}/skills/blender-vse/SKILL_zh-CN.md" in names
    assert f"{prefix}/skills/blender-vse/assets/icon.png" in names
    assert f"{prefix}/skills/blender-vse/assets/logo.png" in names
    assert f"{prefix}/src/blender_vse/mcp/server.py" in names
    assert f"{prefix}/scripts/run_plugin_mcp.py" in names
    assert f"{prefix}/scripts/print_dsh_config.py" in names
    for document in (
        "README",
        "THIRD_PARTY_NOTICES",
        "docs/configuration",
        "docs/clients",
        "docs/context-model",
        "docs/installation",
        "docs/mcp",
        "docs/operations",
        "docs/plugin",
    ):
        assert f"{prefix}/{document}.md" in names
        assert f"{prefix}/{document}_zh-CN.md" in names
    assert not any("/tests/" in name for name in names)


def test_plugin_files_have_no_placeholders_or_unpublished_tools() -> None:
    payload = MANIFEST.read_text(encoding="utf-8") + MCP_CONFIG.read_text(
        encoding="utf-8"
    )
    assert "[TODO:" not in payload
    skill = (ROOT / "skills" / "blender-vse" / "SKILL.md").read_text(encoding="utf-8")
    published = {name for name in EXPECTED_TOOLS if name in skill}
    assert published == EXPECTED_TOOLS
