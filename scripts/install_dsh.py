"""Install the Blender VSE Skill and generate an isolated DSH MCP patch."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SOURCE_SKILL = ROOT / "skills" / "blender-vse"
PROMPT = (
    "Blender VSE 已安装，但尚未完成项目目录配置。请告诉我你希望把 "
    ".blend 项目保存在哪个绝对目录。"
)

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from print_dsh_config import build_patch, render_patch

from blender_vse.installation import workspace_storage_advice


def _fingerprint(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts
    }


def _target_skill(
    *,
    scope: str,
    dsh_home: Path,
    project_root: Path | None,
) -> Path:
    if scope == "user":
        return dsh_home / "skills" / "blender-vse"
    if project_root is None:
        raise ValueError("--project-root is required for project scope")
    expanded = project_root.expanduser()
    if not expanded.is_absolute():
        raise ValueError("project root must be an absolute path")
    return expanded.resolve(strict=False) / ".dsh" / "skills" / "blender-vse"


def _copy_skill(source: Path, target: Path) -> str:
    if target.exists():
        if not target.is_dir():
            raise ValueError(f"DSH Skill target is not a directory: {target}")
        if _fingerprint(source) == _fingerprint(target):
            return "unchanged"
        raise ValueError(
            f"DSH Skill target already contains different files: {target}; "
            "review and remove or migrate it explicitly"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".blender-vse-", dir=target.parent))
    try:
        shutil.copytree(
            source,
            staging / "blender-vse",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        (staging / "blender-vse").replace(target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return "copied"


def install(
    *,
    scope: str = "user",
    dsh_home: Path,
    project_root: Path | None = None,
    plugin_root: Path = ROOT,
    projects_dir: Path | None = None,
    workspace_root: Path | None = None,
    allow_external_projects: bool = False,
    output_patch: Path | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    dsh_home = dsh_home.expanduser().resolve(strict=False)
    target = _target_skill(
        scope=scope,
        dsh_home=dsh_home,
        project_root=project_root,
    )

    patch: list[dict[str, Any]] | None = None
    patch_path: Path | None = None
    workspace_advice: dict[str, Any] | None = None
    if projects_dir is not None:
        workspace_advice = workspace_storage_advice(
            projects_dir=projects_dir,
            workspace_root=workspace_root,
        )
        if not workspace_advice["confirmation_required"] or allow_external_projects:
            patch = build_patch(
                plugin_root=plugin_root,
                projects_dir=projects_dir,
                workspace_root=workspace_root,
                allow_external_projects=allow_external_projects,
            )
            patch_path = (
                output_patch.expanduser().resolve(strict=False)
                if output_patch is not None
                else dsh_home / "integrations" / "blender-vse" / "cordis.patch.yml"
            )

    skill_action = "planned"
    patch_action = (
        "awaiting-projects-dir"
        if projects_dir is None
        else "awaiting-workspace-confirmation"
    )
    if apply:
        skill_action = _copy_skill(SOURCE_SKILL, target)
        if patch is not None and patch_path is not None:
            rendered = render_patch(patch)
            if patch_path.exists():
                if patch_path.read_text(encoding="utf-8") != rendered:
                    raise ValueError(
                        f"DSH patch already exists with different content: {patch_path}"
                    )
                patch_action = "unchanged"
            else:
                patch_path.parent.mkdir(parents=True, exist_ok=True)
                patch_path.write_text(rendered, encoding="utf-8", newline="\n")
                patch_action = "written"
    elif patch is not None:
        patch_action = "planned"

    configured = bool(
        apply
        and projects_dir is not None
        and skill_action in {"copied", "unchanged"}
        and patch_action in {"written", "unchanged"}
    )
    status = "configured" if configured else ("installed" if apply else "planned")
    result: dict[str, Any] = {
        "status": status,
        "ready": False,
        "applied": apply,
        "skill": {
            "source": str(SOURCE_SKILL),
            "target": str(target),
            "action": skill_action,
        },
        "mcp_patch": {
            "path": str(patch_path) if patch_path else None,
            "action": patch_action,
        },
        "workspace_advice": workspace_advice,
    }
    if configured and patch_path is not None:
        result["next_action"] = (
            f'dsh --profile web --patch "{patch_path}" --dump-config'
        )
    elif projects_dir is not None and patch is None:
        result["next_action"] = "confirm_workspace_or_allow_external_projects"
        result["prompt_zh_CN"] = workspace_advice["message_zh_CN"]
    elif projects_dir is not None:
        result["next_action"] = "review_then_rerun_with_apply"
    else:
        result["next_action"] = (
            "ask_user_for_workspace_and_projects_dir"
            if workspace_root is None
            else "ask_user_for_projects_dir"
        )
        result["prompt_zh_CN"] = (
            "当前 Harness 没有可确认的工作区。建议先打开或选择工作区，"
            "并把 Blender VSE 项目与素材放在工作区内。" + PROMPT
            if workspace_root is None
            else PROMPT
        )
        result["required_variable"] = "BLENDER_VSE_PROJECTS_DIR"
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=("user", "project"), default="user")
    parser.add_argument(
        "--dsh-home",
        type=Path,
        default=Path(os.environ.get("DSH_HOME") or Path.home() / ".dsh"),
    )
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--plugin-root", type=Path, default=ROOT)
    parser.add_argument("--projects-dir", type=Path)
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--allow-external-projects", action="store_true")
    parser.add_argument("--output-patch", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    result = install(
        scope=args.scope,
        dsh_home=args.dsh_home,
        project_root=args.project_root,
        plugin_root=args.plugin_root,
        projects_dir=args.projects_dir,
        workspace_root=args.workspace_root,
        allow_external_projects=args.allow_external_projects,
        output_patch=args.output_patch,
        apply=args.apply,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
