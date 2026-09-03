"""Print a DSH Cordis patch for the local Blender VSE MCP server.

The rendered document uses JSON syntax, which is valid YAML and can be passed
directly to ``dsh --patch`` or merged as one item into a profile/home
``cordis.patch.yml``.  It never edits DSH configuration itself.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
MCP_VERSION = "2.1.1"
PYTHON_VERSION = "3.12"

if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from blender_vse.installation import workspace_storage_advice


def _absolute(path: Path, label: str) -> Path:
    expanded = path.expanduser()
    if not expanded.is_absolute():
        raise ValueError(f"{label} must be an absolute path")
    return expanded.resolve(strict=False)


def build_patch(
    *,
    plugin_root: Path = ROOT,
    projects_dir: Path,
    workspace_root: Path | None = None,
    allow_external_projects: bool = False,
    allowed_roots: list[Path] | None = None,
) -> list[dict[str, Any]]:
    plugin_root = _absolute(plugin_root, "plugin root")
    launcher = plugin_root / "scripts" / "run_plugin_mcp.py"
    if not launcher.is_file():
        raise ValueError(f"plugin launcher not found: {launcher}")

    projects = _absolute(projects_dir, "project directory")
    roots = [_absolute(path, "allowed root") for path in (allowed_roots or [])]
    if projects not in roots:
        roots.insert(0, projects)
    advice = workspace_storage_advice(
        projects_dir=projects,
        workspace_root=workspace_root,
    )
    external_roots = []
    if workspace_root is not None:
        workspace = _absolute(workspace_root, "workspace root")
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
            message + " Pass --allow-external-projects only after the user confirms."
        )

    return [
        {
            "insert": [
                {
                    "id": "mcp-blender-vse-control",
                    "name": "@deepseek-ai/dsh-mcp-client",
                    "config": {
                        "serverName": "blender-vse-control",
                        "transport": "stdio",
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
                        "cwd": str(plugin_root),
                        "env": {
                            "BLENDER_VSE_PROJECTS_DIR": str(projects),
                            "BLENDER_VSE_ALLOWED_ROOTS": os.pathsep.join(
                                str(path) for path in roots
                            ),
                        },
                        "toolCallTimeoutMs": 3_600_000,
                        "failOnStartupError": True,
                    },
                }
            ]
        }
    ]


def render_patch(patch: list[dict[str, Any]]) -> str:
    return json.dumps(patch, indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugin-root", type=Path, default=ROOT)
    parser.add_argument("--projects-dir", type=Path, required=True)
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--allow-external-projects", action="store_true")
    parser.add_argument("--allowed-root", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    patch = build_patch(
        plugin_root=args.plugin_root,
        projects_dir=args.projects_dir,
        workspace_root=args.workspace_root,
        allow_external_projects=args.allow_external_projects,
        allowed_roots=args.allowed_root,
    )
    rendered = render_patch(patch)
    if args.output:
        output = args.output.expanduser().resolve(strict=False)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8", newline="\n")
        print(output)
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
