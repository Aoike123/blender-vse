from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from blender_vse.mcp.boundary import (
    MCPAdapter,
    ProjectAccessError,
    ProjectBoundary,
    ProjectLockRegistry,
)


class RecordingController:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Path, dict]] = []

    def _record(self, op: str, project: Path, kwargs: dict) -> dict:
        self.calls.append((op, project, kwargs))
        return {"ok": True, "op": op, "data": {"project": str(project)}}

    def read(self, project: Path, **kwargs) -> dict:
        return self._record("read", project, kwargs)

    def patch(self, project: Path, **kwargs) -> dict:
        return self._record("patch", project, kwargs)

    def acknowledge(self, project: Path, **kwargs) -> dict:
        return self._record("acknowledge", project, kwargs)

    def verify(self, project: Path, **kwargs) -> dict:
        return self._record("verify", project, kwargs)


def test_boundary_resolves_only_blend_files_below_allowed_roots(
    tmp_path: Path,
) -> None:
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    boundary = ProjectBoundary([allowed])

    assert (
        boundary.resolve(allowed / "nested" / "demo.BLEND")
        == (allowed / "nested" / "demo.BLEND").resolve()
    )
    with pytest.raises(ProjectAccessError, match="inside the workspace") as denied:
        boundary.resolve(outside / "demo.blend")
    assert denied.value.code == "project_not_allowed"
    with pytest.raises(ProjectAccessError, match=".blend") as wrong_suffix:
        boundary.resolve(allowed / "demo.py")
    assert wrong_suffix.value.code == "invalid_project_path"


def test_boundary_confines_projects_to_the_workspace_folder(tmp_path: Path) -> None:
    boundary = ProjectBoundary.from_environment(environ={}, cwd=tmp_path)
    projects = (tmp_path / "blender-vse-projects").resolve()
    assert boundary.roots == (projects,)
    assert boundary.resolve("demo.blend") == projects / "demo.blend"
    assert boundary.resolve("cuts/v2.blend") == projects / "cuts" / "v2.blend"
    with pytest.raises(ProjectAccessError) as escaped:
        boundary.resolve("../outside.blend")
    assert escaped.value.code == "project_not_allowed"


def test_boundary_workspace_override_replaces_the_launch_folder(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    boundary = ProjectBoundary.from_environment(
        environ={"BLENDER_VSE_WORKSPACE": str(workspace)},
        cwd=tmp_path / "elsewhere",
    )
    assert boundary.roots == ((workspace / "blender-vse-projects").resolve(),)


def test_boundary_rejects_an_existing_file_as_root(tmp_path: Path) -> None:
    file_root = tmp_path / "not-a-directory"
    file_root.touch()
    with pytest.raises(ValueError, match="not a directory"):
        ProjectBoundary([file_root])


def test_boundary_rejects_a_symlink_escape(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    link = allowed / "linked-outside"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks are unavailable: {exc}")

    with pytest.raises(ProjectAccessError) as denied:
        ProjectBoundary([allowed]).resolve(link / "demo.blend")
    assert denied.value.code == "project_not_allowed"


def test_adapter_denies_paths_before_controller_call(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    controller = RecordingController()
    adapter = MCPAdapter(
        controller=controller,  # type: ignore[arg-type]
        boundary=ProjectBoundary([allowed]),
    )

    result = adapter.read(tmp_path / "outside.blend")
    assert result["error"]["code"] == "project_not_allowed"
    assert controller.calls == []
    encoded = json.dumps(result, ensure_ascii=False).encode("utf-8")
    assert len(encoded) <= result["context"]["max_bytes"]
    assert result["context"]["response_bytes"] <= result["context"]["max_bytes"]


def test_adapter_bounds_unexpected_authorization_failures() -> None:
    class BrokenBoundary:
        def resolve(self, _project):
            raise OSError("secret host detail")

    controller = RecordingController()
    adapter = MCPAdapter(
        controller=controller,  # type: ignore[arg-type]
        boundary=BrokenBoundary(),  # type: ignore[arg-type]
    )
    result = adapter.read("demo.blend")
    assert result["error"] == {
        "code": "invalid_project_path",
        "message": "project authorization failed",
        "truncated": False,
    }
    assert controller.calls == []


def test_adapter_forwards_all_four_operations_with_canonical_path(
    tmp_path: Path,
) -> None:
    project = tmp_path / "demo.blend"
    project.touch()
    controller = RecordingController()
    adapter = MCPAdapter(
        controller=controller,  # type: ignore[arg-type]
        boundary=ProjectBoundary([tmp_path]),
    )

    adapter.read(project, view="summary")
    adapter.patch(project, patch_id="p")
    adapter.acknowledge(project, observed_revision=2)
    adapter.verify(project, expected={"text": 1})

    assert [call[0] for call in controller.calls] == [
        "read",
        "patch",
        "acknowledge",
        "verify",
    ]
    assert all(call[1] == project.resolve() for call in controller.calls)


def test_project_locks_are_stable_per_canonical_path(tmp_path: Path) -> None:
    locks = ProjectLockRegistry(stripes=8)
    first = (tmp_path / "one.blend").resolve()
    assert locks.lock_for(first) is locks.lock_for(first)
    used = {
        id(locks.lock_for((tmp_path / f"project-{index}.blend").resolve()))
        for index in range(64)
    }
    assert 1 < len(used) <= 8


@pytest.mark.parametrize("stripes", [0, 1025])
def test_project_lock_registry_rejects_unbounded_sizes(stripes: int) -> None:
    with pytest.raises(ValueError, match="between 1 and 1024"):
        ProjectLockRegistry(stripes=stripes)


def test_adapter_serializes_concurrent_calls_for_same_project(tmp_path: Path) -> None:
    project = tmp_path / "demo.blend"
    project.touch()

    class ConcurrentController(RecordingController):
        def __init__(self) -> None:
            super().__init__()
            self.guard = threading.Lock()
            self.active = 0
            self.max_active = 0

        def read(self, project: Path, **kwargs) -> dict:
            with self.guard:
                self.active += 1
                self.max_active = max(self.max_active, self.active)
            time.sleep(0.03)
            with self.guard:
                self.active -= 1
            return super().read(project, **kwargs)

    controller = ConcurrentController()
    adapter = MCPAdapter(
        controller=controller,  # type: ignore[arg-type]
        boundary=ProjectBoundary([tmp_path]),
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: adapter.read(project), range(2)))

    assert all(result["ok"] for result in results)
    assert controller.max_active == 1
