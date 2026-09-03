"""Print a portable stdio MCP configuration with absolute local paths."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MCP_VERSION = "2.1.1"
PYTHON_VERSION = "3.12"

if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from blender_vse.installation import workspace_storage_advice


def build_config(
    *,
    plugin_root: Path = ROOT,
    projects_dir: Path | None = None,
    workspace_root: Path | None = None,
    allow_external_projects: bool = False,
    allowed_roots: list[Path] | None = None,
) -> dict:
    plugin_root = plugin_root.expanduser().resolve()
    launcher = plugin_root / "scripts" / "run_plugin_mcp.py"
    if not launcher.is_file():
        raise ValueError(f"plugin launcher not found: {launcher}")
    environment: dict[str, str] = {}
    projects: Path | None = None
    if projects_dir is not None:
        expanded = projects_dir.expanduser()
        if not expanded.is_absolute():
            raise ValueError("project directory must be an absolute path")
        projects = expanded.resolve(strict=False)
        environment["BLENDER_VSE_PROJECTS_DIR"] = str(projects)
    roots = []
    for path in allowed_roots or []:
        expanded = path.expanduser()
        if not expanded.is_absolute():
            raise ValueError("allowed roots must be absolute paths")
        resolved = expanded.resolve(strict=False)
        if resolved not in roots:
            roots.append(resolved)
    if projects is not None and projects not in roots:
        roots.insert(0, projects)
    if projects is not None:
        advice = workspace_storage_advice(
            projects_dir=projects,
            workspace_root=workspace_root,
        )
        external_roots = []
        if workspace_root is not None:
            workspace = Path(workspace_root).expanduser().resolve(strict=False)
            external_roots = [
                path
                for path in roots
                if path != workspace and not path.is_relative_to(workspace)
            ]
        if (
            advice["confirmation_required"] or external_roots
        ) and not allow_external_projects:
            message = str(advice["message_zh_CN"])
            if external_roots:
                message = (
                    "One or more project/resource roots are outside the active workspace: "
                    + ", ".join(str(path) for path in external_roots)
                    + ". Obtain explicit user confirmation."
                )
            raise ValueError(
                message
                + " Pass --allow-external-projects only after the user confirms."
            )
    if roots:
        environment["BLENDER_VSE_ALLOWED_ROOTS"] = os.pathsep.join(
            str(path) for path in roots
        )
    return {
        "mcpServers": {
            "blender-vse-control": {
                "type": "stdio",
                "command": "uv",
                "args": [
                    "run",
                    "--no-project",
                    "--managed-python",
                    "--python",
                    PYTHON_VERSION,
                    "--with",
                    f"mcp=={MCP_VERSION}",
                    "python",
                    str(launcher),
                ],
                "env": environment,
            }
        }
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugin-root", type=Path, default=ROOT)
    parser.add_argument("--projects-dir", type=Path)
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--allow-external-projects", action="store_true")
    parser.add_argument("--allowed-root", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    payload = build_config(
        plugin_root=args.plugin_root,
        projects_dir=args.projects_dir,
        workspace_root=args.workspace_root,
        allow_external_projects=args.allow_external_projects,
        allowed_roots=args.allowed_root,
    )
    rendered = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8", newline="\n")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
