from __future__ import annotations

from pathlib import Path

import pytest

from blender_vse.installation import workspace_storage_advice


def test_workspace_storage_advice_recommends_workspace_when_missing(
    tmp_path: Path,
) -> None:
    projects = (tmp_path / "external-projects").resolve()
    advice = workspace_storage_advice(projects_dir=projects, workspace_root=None)

    assert advice["workspace_available"] is False
    assert advice["projects_inside_workspace"] is None
    assert advice["advisory_code"] == "workspace_unavailable"
    assert advice["confirmation_required"] is True
    assert "工作区" in advice["message_zh_CN"]


def test_workspace_storage_advice_accepts_directory_inside_workspace(
    tmp_path: Path,
) -> None:
    workspace = (tmp_path / "workspace").resolve()
    projects = workspace / "blender-vse-projects"
    advice = workspace_storage_advice(
        projects_dir=projects,
        workspace_root=workspace,
    )

    assert advice["projects_inside_workspace"] is True
    assert advice["recommended_projects_dir"] == str(projects)
    assert advice["advisory_code"] is None
    assert advice["confirmation_required"] is False


def test_workspace_storage_advice_requires_confirmation_outside_workspace(
    tmp_path: Path,
) -> None:
    workspace = (tmp_path / "workspace").resolve()
    projects = (tmp_path / "external").resolve()
    advice = workspace_storage_advice(
        projects_dir=projects,
        workspace_root=workspace,
    )

    assert advice["projects_inside_workspace"] is False
    assert advice["advisory_code"] == "projects_dir_outside_workspace"
    assert advice["confirmation_required"] is True
    assert str(workspace / "blender-vse-projects") in advice["message_zh_CN"]


@pytest.mark.parametrize("field", ["projects_dir", "workspace_root"])
def test_workspace_storage_advice_rejects_relative_paths(
    field: str, tmp_path: Path
) -> None:
    values = {
        "projects_dir": (tmp_path / "projects").resolve(),
        "workspace_root": (tmp_path / "workspace").resolve(),
    }
    values[field] = Path("relative")
    with pytest.raises(ValueError, match="absolute"):
        workspace_storage_advice(**values)
