"""Validate the Claude package with its real local CLI."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLAUDE_PACKAGE = "@anthropic-ai/claude-code@2.1.259"


def _run(command: list[str], *, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"command failed ({result.returncode}): {subprocess.list2cmdline(command)}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result.stdout


def _copy_claude_plugin(target: Path) -> None:
    (target / ".claude-plugin").mkdir(parents=True)
    (target / "clients" / "claude").mkdir(parents=True)
    (target / "scripts").mkdir(parents=True)
    shutil.copy2(
        ROOT / ".claude-plugin" / "plugin.json",
        target / ".claude-plugin" / "plugin.json",
    )
    shutil.copy2(
        ROOT / "clients" / "claude" / "mcp.json",
        target / "clients" / "claude" / "mcp.json",
    )
    shutil.copy2(
        ROOT / "scripts" / "run_plugin_mcp.py",
        target / "scripts" / "run_plugin_mcp.py",
    )
    ignored = shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info")
    shutil.copytree(ROOT / "skills", target / "skills", ignore=ignored)
    shutil.copytree(ROOT / "src", target / "src", ignore=ignored)


def _claude(npx: str, temp: Path) -> dict[str, object]:
    marketplace_output = _run(
        [
            npx,
            "--yes",
            CLAUDE_PACKAGE,
            "plugin",
            "validate",
            str(ROOT),
            "--strict",
            "--json",
        ]
    )
    marketplace = json.loads(marketplace_output)
    if not marketplace.get("success"):
        raise RuntimeError("Claude marketplace validation did not report success")

    plugin_root = temp / "claude-plugin"
    _copy_claude_plugin(plugin_root)
    plugin_output = _run(
        [
            npx,
            "--yes",
            CLAUDE_PACKAGE,
            "plugin",
            "validate",
            str(plugin_root),
            "--strict",
            "--json",
        ]
    )
    plugin = json.loads(plugin_output)
    if not plugin.get("success"):
        raise RuntimeError("Claude plugin validation did not report success")

    marketplace_root = temp / "claude-marketplace"
    (marketplace_root / ".claude-plugin").mkdir(parents=True)
    local_marketplace = json.loads(
        (ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
    )
    local_marketplace["plugins"][0]["source"] = "./plugins/blender-vse"
    (marketplace_root / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps(local_marketplace, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    shutil.copytree(
        plugin_root,
        marketplace_root / "plugins" / "blender-vse",
    )
    claude_config = temp / "claude-config"
    environment = dict(os.environ)
    environment["CLAUDE_CONFIG_DIR"] = str(claude_config)
    environment["NO_COLOR"] = "1"
    base = [npx, "--yes", CLAUDE_PACKAGE, "plugin"]
    _run(
        [*base, "marketplace", "add", str(marketplace_root), "--scope", "user"],
        env=environment,
    )
    _run(
        [
            *base,
            "install",
            "blender-vse@blender-vse",
            "--scope",
            "user",
        ],
        env=environment,
    )
    listing = _run([*base, "list", "--json"], env=environment)
    if "blender-vse@blender-vse" not in listing:
        raise RuntimeError("Claude isolated install is absent from plugin list")
    cached_skills = list(claude_config.rglob("skills/blender-vse/SKILL.md"))
    if len(cached_skills) != 1:
        raise RuntimeError(
            f"Claude isolated install expected one cached Skill, found {cached_skills}"
        )
    health = _run(
        [npx, "--yes", CLAUDE_PACKAGE, "mcp", "list"],
        env=environment,
    )
    if (
        "plugin:blender-vse:blender-vse-control" not in health
        or "Connected" not in health
    ):
        raise RuntimeError(f"Claude plugin MCP did not connect:\n{health}")
    return {
        "package": CLAUDE_PACKAGE,
        "marketplace": True,
        "plugin": True,
        "isolated_install": True,
        "mcp_connected": True,
    }


def main() -> int:
    npx = shutil.which("npx")
    if not npx:
        raise RuntimeError("harness smoke requires npx on PATH")

    temp_parent = (ROOT / ".tmp").resolve()
    temp_parent.mkdir(exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix="harness-smoke-", dir=temp_parent)).resolve()
    try:
        result = {
            "claude": _claude(npx, temp),
            "components": {
                "skills": 1,
                "mcp_servers": 1,
                "mcp_tools": 4,
            },
        }
        print(json.dumps(result, indent=2, ensure_ascii=False))
    finally:
        if temp.parent != temp_parent:
            raise RuntimeError(f"refusing to remove unexpected temp path: {temp}")
        shutil.rmtree(temp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
