from __future__ import annotations

from pathlib import Path

import pytest

from blender_vse import blender as adapter
from blender_vse.blender.runner import BlenderResult, BlenderRunnerError


@pytest.mark.parametrize(
    ("message", "code"),
    [
        ("stale_base: changed", "stale_base"),
        ("prefix overlap_detected: clips", "overlap_detected"),
        ("batch: unsupported operation", "batch"),
        (
            "preview_resolution_must_be_integer_scale: invalid size",
            "preview_resolution_must_be_integer_scale",
        ),
        ("plain failure", "execution_failed"),
    ],
)
def test_runtime_error_code_preserves_known_prefix(message: str, code: str) -> None:
    assert adapter._runtime_error_code(message) == code


def test_save_snapshot_handles_missing_and_existing_paths(tmp_path: Path) -> None:
    project = tmp_path / "demo.blend"
    assert adapter._save_snapshot(None) == {}
    assert adapter._save_snapshot(str(project)) == {}
    project.write_bytes(b"blend")
    assert adapter._save_snapshot(str(project))["size"] == 5


def test_verify_save_reports_creation_change_and_missing(tmp_path: Path) -> None:
    project = tmp_path / "demo.blend"
    assert adapter._verify_save(None, {}) is None
    missing = adapter._verify_save(str(project), {})
    assert missing["saved"] is False
    project.write_bytes(b"new")
    created = adapter._verify_save(str(project), {})
    assert created["saved"] is True and created["created"] is True
    before = adapter._save_snapshot(str(project))
    unchanged = adapter._verify_save(str(project), before)
    assert unchanged["saved"] is False
    project.write_bytes(b"changed-size")
    changed = adapter._verify_save(str(project), before)
    assert changed["saved"] is True and changed["size_changed"] is True


def test_blender_execute_wraps_typed_runner_errors(monkeypatch) -> None:
    monkeypatch.setattr(
        adapter,
        "dispatch",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            BlenderRunnerError("invalid_args", "bad input", {"field": "x"})
        ),
    )
    result = adapter.blender_execute("list_strips", {"project": "demo.blend"})
    assert result["error"] == {
        "code": "invalid_args",
        "message": "bad input",
        "details": {"field": "x"},
    }


def test_blender_execute_wraps_unexpected_errors(monkeypatch) -> None:
    monkeypatch.setattr(
        adapter,
        "dispatch",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    result = adapter.blender_execute("list_strips", {"project": "demo.blend"})
    assert result["error"]["code"] == "execution_failed"


def test_blender_execute_preserves_script_error_code(monkeypatch) -> None:
    monkeypatch.setattr(
        adapter,
        "dispatch",
        lambda *_args, **_kwargs: BlenderResult(
            False,
            error="revision_mismatch: stale",
            payload={"revision": 2},
            mode="live",
        ),
    )
    result = adapter.blender_execute("get_revision", {"project": "demo.blend"})
    assert result["error"]["code"] == "revision_mismatch"
    assert result["data"] == {"revision": 2}


def test_read_only_success_has_uniform_envelope(monkeypatch) -> None:
    monkeypatch.setattr(
        adapter,
        "dispatch",
        lambda *_args, **_kwargs: BlenderResult(
            True,
            output="complete",
            payload={"strips": []},
            mode="live",
        ),
    )
    result = adapter.blender_execute("list_strips", {"project": "demo.blend"})
    assert result == {
        "ok": True,
        "op": "list_strips",
        "adapter": "blender",
        "dry_run": False,
        "mode": "live",
        "data": {"strips": []},
        "message": "complete",
    }


def test_mutation_verifies_live_save_and_timeline(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "demo.blend"
    project.write_bytes(b"before")
    calls = []

    def dispatch(operation, _runner, _project, _params):
        calls.append(operation)
        if operation == "add_text":
            project.write_bytes(b"after-with-different-size")
            return BlenderResult(True, payload={"added": True}, mode="live")
        assert operation == "list_strips"
        return BlenderResult(
            True,
            payload={"scene": "VideoEditing", "strips": [{"type": "TEXT"}]},
            mode="live",
        )

    monkeypatch.setattr(adapter, "dispatch", dispatch)
    monkeypatch.setattr(adapter, "check_live_session", lambda: {"live_session": True})
    monkeypatch.setattr(
        "blender_vse.blender.live_session.execute_code",
        lambda _code: {"output": f"FP:{project}"},
    )
    result = adapter.blender_execute("add_text", {"project": str(project)})
    assert calls == ["add_text", "list_strips"]
    assert result["live_session"]["live_session"] is True
    assert result["save_verified"]["saved"] is True
    assert result["timeline_verified"] == {
        "strip_count": 1,
        "scene": "VideoEditing",
    }


def test_dry_run_skips_output_verification(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "demo.blend"
    project.touch()
    monkeypatch.setattr(
        adapter,
        "dispatch",
        lambda *_args, **_kwargs: BlenderResult(True, payload={}, mode="dry_run"),
    )
    result = adapter.blender_execute("add_text", {"project": str(project)})
    assert result["dry_run"] is True
    assert "save_verified" not in result
    assert "timeline_verified" not in result
