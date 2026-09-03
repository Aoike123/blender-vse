"""Launch the plugin's declared stdio command and verify MCP discovery."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path

from mcp import Client, StdioServerParameters

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_TOOLS = {
    "blender_read",
    "blender_patch",
    "blender_acknowledge",
    "blender_verify",
}


def _load_builder():
    path = ROOT / "scripts" / "build_plugin.py"
    spec = importlib.util.spec_from_file_location("plugin_runtime_builder", path)
    if not spec or not spec.loader:
        raise RuntimeError(f"cannot load plugin builder: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tree_fingerprint(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


async def inspect(
    plugin_root: Path,
    label: str,
    *,
    runtime_command: str | None = None,
    offline: bool = False,
) -> None:
    config = json.loads((plugin_root / ".mcp.json").read_text(encoding="utf-8"))
    declared = config["mcpServers"]["blender-vse-control"]
    executable = runtime_command or shutil.which(declared["command"])
    if not executable:
        raise RuntimeError(f"missing plugin command: {declared['command']}")
    environment = {
        name: os.environ[name] for name in declared["env_vars"] if name in os.environ
    }
    environment.update(
        {
            "BLENDER_VSE_ALLOWED_ROOTS": str(ROOT / ".tmp" / "plugin-projects"),
            "UV_CACHE_DIR": str(ROOT / ".tmp" / "plugin-uv-cache"),
            "PATH": str(Path(executable).resolve().parent),
        }
    )
    if shutil.which("python", path=environment["PATH"]):
        raise RuntimeError("isolated plugin launch PATH unexpectedly contains Python")
    if offline:
        environment["UV_OFFLINE"] = "1"
    parameters = StdioServerParameters(
        command=executable,
        args=declared["args"],
        cwd=plugin_root,
        env=environment,
    )
    async with Client(parameters) as client:
        listing = await client.list_tools()
        names = {tool.name for tool in listing.tools}
        if names != EXPECTED_TOOLS:
            raise RuntimeError(f"unexpected plugin tools: {sorted(names)}")
        print(
            json.dumps(
                {
                    "server": client.server_info.name,
                    "protocol": client.protocol_version,
                    "source": label,
                    "uv_offline": offline,
                    "system_python_on_path": False,
                    "tools": sorted(names),
                },
                ensure_ascii=False,
            )
        )


async def main() -> None:
    temp_parent = ROOT / ".tmp"
    temp_parent.mkdir(exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix="plugin-bundle-", dir=temp_parent))
    try:
        declared = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))[
            "mcpServers"
        ]["blender-vse-control"]
        uv = shutil.which(declared["command"])
        if not uv:
            raise RuntimeError(f"missing plugin command: {declared['command']}")
        runtime_bin = temp / "runtime-bin"
        runtime_bin.mkdir()
        isolated_uv = runtime_bin / Path(uv).name
        shutil.copy2(uv, isolated_uv)
        isolated_uv.chmod(isolated_uv.stat().st_mode | 0o111)

        await inspect(ROOT, "checkout", runtime_command=str(isolated_uv))
        builder = _load_builder()
        archive_path = builder.build(temp / "plugin.zip")
        builder.verify(archive_path)
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(temp)
        installed = temp / builder.BUNDLE_ROOT / "plugins" / builder.PLUGIN_NAME
        before = _tree_fingerprint(installed)
        await inspect(
            installed,
            "extracted-bundle",
            runtime_command=str(isolated_uv),
            offline=True,
        )
        after = _tree_fingerprint(installed)
        if before != after:
            raise RuntimeError("plugin launch modified the installed source tree")
        if (installed / ".venv").exists() or (installed / "uv.lock").exists():
            raise RuntimeError("plugin launch wrote environment state into the bundle")
    finally:
        shutil.rmtree(temp, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(asyncio.wait_for(main(), timeout=140))
