"""Machine-readable installation advice shared by Agent hosts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

RECOMMENDED_PROJECTS_DIRECTORY = "blender-vse-projects"


def _absolute(path: str | Path, label: str) -> Path:
    expanded = Path(path).expanduser()
    if not expanded.is_absolute():
        raise ValueError(f"{label} must be an absolute path")
    return expanded.resolve(strict=False)


def workspace_storage_advice(
    *,
    projects_dir: str | Path,
    workspace_root: str | Path | None,
) -> dict[str, Any]:
    """Explain whether project storage follows the workspace-first policy.

    Storage outside a workspace remains supported, but an installing Agent must
    disclose the portability and sandbox trade-offs and obtain confirmation.
    The helper is advisory and never moves or creates user files.
    """

    projects = _absolute(projects_dir, "project directory")
    if workspace_root is None:
        return {
            "workspace_available": False,
            "workspace_root": None,
            "projects_dir": str(projects),
            "projects_inside_workspace": None,
            "recommended_projects_dir": None,
            "advisory_code": "workspace_unavailable",
            "confirmation_required": True,
            "message_zh_CN": (
                "当前 Harness 没有可确认的工作区。建议先打开或选择工作区，"
                "并把 Blender VSE 项目与素材目录放在该工作区内；若继续使用"
                "工作区外目录，请明确确认。"
            ),
        }

    workspace = _absolute(workspace_root, "workspace root")
    recommended = workspace / RECOMMENDED_PROJECTS_DIRECTORY
    inside = projects == workspace or projects.is_relative_to(workspace)
    if inside:
        code = None
        message = "Blender VSE 项目目录位于当前工作区内。"
    else:
        code = "projects_dir_outside_workspace"
        message = (
            f"所选项目与素材目录 {projects} 位于当前工作区 {workspace} 外。"
            f"建议改用 {recommended}；若继续使用外部目录，请明确确认。"
        )
    return {
        "workspace_available": True,
        "workspace_root": str(workspace),
        "projects_dir": str(projects),
        "projects_inside_workspace": inside,
        "recommended_projects_dir": str(recommended),
        "advisory_code": code,
        "confirmation_required": not inside,
        "message_zh_CN": message,
    }


__all__ = ["RECOMMENDED_PROJECTS_DIRECTORY", "workspace_storage_advice"]
