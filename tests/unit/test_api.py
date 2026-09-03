from __future__ import annotations

import json
from pathlib import Path

import pytest

from blender_vse import api
from blender_vse.api import BlenderVSE

READY = {
    "ready": True,
    "session_proof": {
        "pid": 42,
        "filepath": "demo.blend",
        "gui_visible": True,
        "workspace": "Video Editing",
        "vse_area_count": 2,
        "scene_binding_match": True,
        "visible_strip_match": True,
        "content_display_ready": True,
    },
}


def test_patch_rejects_empty_commands_before_session(
    monkeypatch, tmp_path: Path
) -> None:
    called = False

    def ensure(_project):
        nonlocal called
        called = True
        return READY

    monkeypatch.setattr(BlenderVSE, "_ensure_live", staticmethod(ensure))
    project = tmp_path / "demo.blend"
    project.touch()
    result = BlenderVSE().patch(
        project,
        base_revision=0,
        base_timeline_hash="hash",
        read_token="token",
        patch_id="patch-1",
        commands=[],
    )
    assert not result["ok"]
    assert result["error"]["code"] == "invalid_args"
    assert not called


def test_read_merges_revision_and_timeline(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "demo.blend"
    project.touch()
    controller = BlenderVSE()
    monkeypatch.setattr(controller, "_ensure_live", lambda _project: READY)

    def execute(op, _params):
        if op == "get_revision":
            return {
                "ok": True,
                "data": {
                    "revision": 4,
                    "timeline_hash": "abc",
                    "observation_id": "obs-4",
                },
            }
        if op == "list_strips":
            return {"ok": True, "data": {"strips": [{"name": "Title"}]}}
        raise AssertionError(op)

    monkeypatch.setattr(controller, "execute", execute)
    result = controller.read(project, view="full")
    assert result["ok"]
    assert result["data"]["revision"] == 4
    assert result["data"]["strips"] == [{"name": "Title"}]
    assert result["data"]["context"]["bounded"] is False
    assert result["data"]["session"]["gui_visible"] is True


def test_read_defaults_to_bounded_summary(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "demo.blend"
    project.touch()
    controller = BlenderVSE()
    monkeypatch.setattr(controller, "_ensure_live", lambda _project: READY)
    calls = []

    def execute(op, params):
        calls.append((op, params))
        if op == "get_revision":
            return {
                "ok": True,
                "data": {
                    "revision": 1,
                    "timeline_hash": "hash",
                    "observation_id": "obs",
                },
            }
        return {
            "ok": True,
            "data": {
                "fps": 30,
                "resolution": [1920, 1080],
                "strips": [
                    {
                        "video_ai_id": "one",
                        "id": "One",
                        "name": "One",
                        "type": "MOVIE",
                        "channel": 1,
                        "frame_start": 1,
                        "frame_end": 30,
                    }
                ],
            },
        }

    monkeypatch.setattr(controller, "execute", execute)
    result = controller.read(project)
    assert result["ok"]
    assert result["data"]["strips"] == []
    assert result["data"]["summary"]["total_strips"] == 1
    assert result["data"]["context"]["view"] == "summary"
    assert calls[-1][1]["with_text"] is False
    assert (
        len(json.dumps(result, default=str).encode("utf-8"))
        <= result["data"]["context"]["max_bytes"]
    )


def test_invalid_read_query_does_not_start_blender(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "demo.blend"
    project.touch()
    monkeypatch.setattr(
        BlenderVSE,
        "_ensure_live",
        staticmethod(lambda _project: pytest.fail("session should not start")),
    )
    result = BlenderVSE().read(project, view="detail")
    assert result["error"]["code"] == "invalid_read_query"


def test_detail_text_query_requests_text_from_blender(
    monkeypatch, tmp_path: Path
) -> None:
    project = tmp_path / "demo.blend"
    project.touch()
    controller = BlenderVSE()
    monkeypatch.setattr(controller, "_ensure_live", lambda _project: READY)
    calls = []

    def execute(op, params):
        calls.append((op, params))
        if op == "get_revision":
            return {
                "ok": True,
                "data": {
                    "revision": 1,
                    "timeline_hash": "hash",
                    "observation_id": "obs",
                },
            }
        return {
            "ok": True,
            "data": {
                "strips": [
                    {
                        "video_ai_id": "title",
                        "id": "Title",
                        "name": "Title",
                        "type": "TEXT",
                        "channel": 3,
                        "frame_start": 1,
                        "frame_end": 30,
                        "text": "Hello",
                    }
                ]
            },
        }

    monkeypatch.setattr(controller, "execute", execute)
    result = controller.read(
        project,
        view="detail",
        strip_ids=["title"],
        include=["text"],
    )
    assert result["ok"]
    assert result["data"]["strips"][0]["text"] == "Hello"
    assert calls[-1][1]["with_text"] is True


def test_stale_patch_returns_readable_failure(monkeypatch, tmp_path: Path) -> None:
    controller = BlenderVSE()
    project = tmp_path / "demo.blend"
    project.touch()
    monkeypatch.setattr(controller, "_ensure_live", lambda _project: READY)
    monkeypatch.setattr(
        controller,
        "execute",
        lambda _op, _params: {
            "ok": False,
            "error": {"code": "stale_base", "message": "stale_base: changed"},
        },
    )
    result = controller.patch(
        project,
        base_revision=1,
        base_timeline_hash="old",
        read_token="obs",
        patch_id="patch-2",
        commands=[{"op": "set_text", "target": "Title", "text": "New"}],
    )
    assert not result["ok"]
    assert result["error"]["code"] == "stale_base"
    assert "Read again" in result["error"]["message"]


def test_missing_project_fails_without_starting_a_session(
    monkeypatch, tmp_path: Path
) -> None:
    called = False

    def ensure(_project):
        nonlocal called
        called = True
        return READY

    monkeypatch.setattr(BlenderVSE, "_ensure_live", staticmethod(ensure))
    controller = BlenderVSE()
    missing = tmp_path / "missing.blend"
    assert controller.read(missing)["error"]["code"] == "project_not_found"
    assert controller.verify(missing)["error"]["code"] == "project_not_found"
    assert not called


def test_read_can_create_then_observe_a_project(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "new.blend"
    controller = BlenderVSE()
    monkeypatch.setattr(controller, "_ensure_live", lambda _project: READY)
    calls = []

    def execute(op, params):
        calls.append((op, params))
        if op == "create_project":
            project.touch()
            return {"ok": True, "data": {"created": True}}
        if op == "get_revision":
            return {
                "ok": True,
                "data": {
                    "revision": 0,
                    "timeline_hash": "empty",
                    "observation_id": "obs-0",
                },
            }
        if op == "list_strips":
            return {"ok": True, "data": {"strips": []}}
        raise AssertionError(op)

    monkeypatch.setattr(controller, "execute", execute)
    result = controller.read(
        project,
        create_if_missing=True,
        resolution=(640, 360),
        fps=24,
    )
    assert result["ok"]
    assert [op for op, _ in calls] == ["create_project", "get_revision", "list_strips"]
    assert calls[0][1]["resolution"] == [640, 360]
    assert calls[0][1]["fps"] == 24


@pytest.mark.parametrize(
    ("failed_op", "expected_text"),
    [("get_revision", "get_revision failed"), ("list_strips", "list_strips failed")],
)
def test_read_propagates_primitive_failures(
    monkeypatch,
    tmp_path: Path,
    failed_op: str,
    expected_text: str,
) -> None:
    project = tmp_path / "demo.blend"
    project.touch()
    controller = BlenderVSE()
    monkeypatch.setattr(controller, "_ensure_live", lambda _project: READY)

    def execute(op, _params):
        if op == failed_op:
            return {"ok": False, "error": {"code": "broken", "message": "boom"}}
        return {"ok": True, "data": {}}

    monkeypatch.setattr(controller, "execute", execute)
    result = controller.read(project)
    assert not result["ok"]
    assert result["error"]["code"] == "broken"
    assert expected_text in result["error"]["message"]


@pytest.mark.parametrize(
    "commands",
    [["not-an-object"], [{"text": "missing op"}]],
)
def test_patch_rejects_malformed_commands_before_session(
    monkeypatch,
    tmp_path: Path,
    commands,
) -> None:
    project = tmp_path / "demo.blend"
    project.touch()
    ensure = lambda _project: pytest.fail("session should not start")
    monkeypatch.setattr(BlenderVSE, "_ensure_live", staticmethod(ensure))
    result = BlenderVSE().patch(
        project,
        base_revision=1,
        base_timeline_hash="hash",
        read_token="obs",
        patch_id="patch",
        commands=commands,
    )
    assert result["error"]["code"] == "invalid_args"


def test_patch_rejects_missing_observation_values(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "demo.blend"
    project.touch()
    monkeypatch.setattr(
        BlenderVSE,
        "_ensure_live",
        staticmethod(lambda _project: pytest.fail("session should not start")),
    )
    result = BlenderVSE().patch(
        project,
        base_revision=1,
        base_timeline_hash="",
        read_token="",
        patch_id="",
        commands=[{"op": "set_text"}],
    )
    assert result["error"]["code"] == "read_required"


def test_patch_rejects_oversized_command_list_before_session(
    monkeypatch,
    tmp_path: Path,
) -> None:
    project = tmp_path / "demo.blend"
    project.touch()
    monkeypatch.setattr(
        BlenderVSE,
        "_ensure_live",
        staticmethod(lambda _project: pytest.fail("session should not start")),
    )
    result = BlenderVSE().patch(
        project,
        base_revision=1,
        base_timeline_hash="hash",
        read_token="obs",
        patch_id="patch",
        commands=[{"op": "set_text"} for _ in range(101)],
    )
    assert result["error"]["code"] == "invalid_args"
    assert "at most 100" in result["error"]["message"]


@pytest.mark.parametrize(
    "payload",
    [
        {"applied": True, "applied_revision": 2},
        {"status": "already_applied", "applied_revision": 2},
    ],
)
def test_patch_accepts_applied_and_idempotent_results(
    monkeypatch,
    tmp_path: Path,
    payload: dict,
) -> None:
    project = tmp_path / "demo.blend"
    project.touch()
    controller = BlenderVSE()
    monkeypatch.setattr(controller, "_ensure_live", lambda _project: READY)
    monkeypatch.setattr(
        controller,
        "execute",
        lambda _op, _params: {"ok": True, "data": payload},
    )
    result = controller.patch(
        project,
        base_revision=1,
        base_timeline_hash="hash",
        read_token="obs",
        patch_id="patch",
        commands=[{"op": "set_text", "target": "Title", "text": "New"}],
    )
    assert result["ok"]
    assert result["data"]["applied_revision"] == 2
    assert result["data"]["context"]["view"] == "patch"
    assert (
        len(json.dumps(result, default=str).encode("utf-8"))
        <= result["data"]["context"]["max_bytes"]
    )


def test_patch_reports_atomic_rollback(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "demo.blend"
    project.touch()
    controller = BlenderVSE()
    monkeypatch.setattr(controller, "_ensure_live", lambda _project: READY)
    monkeypatch.setattr(
        controller,
        "execute",
        lambda _op, _params: {"ok": True, "data": {"applied": False, "error": "x"}},
    )
    result = controller.patch(
        project,
        base_revision=1,
        base_timeline_hash="hash",
        read_token="obs",
        patch_id="patch",
        commands=[{"op": "set_text"}],
    )
    assert result["error"]["code"] == "patch_rolled_back"


def test_restore_cannot_be_mixed_with_edits(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "demo.blend"
    project.touch()
    monkeypatch.setattr(
        BlenderVSE,
        "_ensure_live",
        staticmethod(lambda _project: pytest.fail("session should not start")),
    )
    result = BlenderVSE().patch(
        project,
        base_revision=1,
        base_timeline_hash="hash",
        read_token="obs",
        patch_id="patch",
        commands=[
            {"op": "restore_checkpoint", "name": "one"},
            {"op": "set_text"},
        ],
    )
    assert "only command" in result["error"]["message"]


def test_acknowledge_and_verify_success(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "demo.blend"
    project.touch()
    controller = BlenderVSE()
    monkeypatch.setattr(controller, "_ensure_live", lambda _project: READY)

    def execute(op, params):
        if op == "acknowledge_revision":
            return {"ok": True, "data": {"revision": 3}}
        assert op == "verify_persistence"
        assert params["expected"] == {"movie": 2}
        return {"ok": True, "data": {"verified": True}}

    monkeypatch.setattr(controller, "execute", execute)
    acknowledged = controller.acknowledge(
        project,
        observed_revision=2,
        observed_hash="hash",
        read_token="obs",
    )
    verified = controller.verify(project, expected={"movie": 2})
    assert acknowledged["ok"] and acknowledged["data"]["revision"] == 3
    assert verified["ok"] and verified["data"]["verified"] is True
    assert acknowledged["data"]["context"]["view"] == "acknowledge"
    assert verified["data"]["context"]["view"] == "verify"


def test_session_projection_fails_closed_when_budget_is_exceeded(monkeypatch) -> None:
    monkeypatch.setattr(api, "SESSION_CONTEXT_MAX_BYTES", 10)
    with pytest.raises(RuntimeError, match="session_context_budget_exceeded"):
        api._session_projection(READY)


def test_session_failure_does_not_return_raw_discovery_tree(monkeypatch) -> None:
    monkeypatch.setattr(
        api.live_session,
        "ensure_live_session",
        lambda _project: {
            "ready": False,
            "code": "gui_not_visible",
            "message": "hidden " + "x" * 20_000,
            "window_candidates": [{"huge": "y" * 20_000}],
            "discovery": {"attempts": 10, "observed_states": ["gui_not_visible"]},
        },
    )
    result = BlenderVSE._ensure_live("demo.blend")
    assert result["error"]["code"] == "gui_not_visible"
    assert "window_candidates" not in result["session"]
    assert result["session"]["context"]["bounded"] is True
    size = len(json.dumps(result, ensure_ascii=False, default=str).encode("utf-8"))
    assert size <= result["context"]["max_bytes"]
    assert result["context"]["response_bytes"] <= result["context"]["max_bytes"]


def test_error_envelope_omits_oversized_optional_data() -> None:
    result = api._failure(
        "patch",
        "patch_rolled_back",
        "failed",
        data={"raw": "x" * 20_000},
    )
    assert "data" not in result
    assert result["data_omitted"] is True
    assert (
        len(json.dumps(result, default=str).encode("utf-8"))
        <= result["context"]["max_bytes"]
    )


def test_checkpoint_restore_replaces_disk_and_keeps_backup(
    monkeypatch,
    tmp_path: Path,
) -> None:
    project = tmp_path / "demo.blend"
    project.write_bytes(b"current")
    checkpoint_dir = tmp_path / "checkpoints"
    checkpoint_dir.mkdir()
    (checkpoint_dir / "good.blend").write_bytes(b"checkpoint")
    controller = BlenderVSE()

    def execute(op, _params):
        if op == "validate_checkpoint_restore":
            return {"ok": True, "data": {"status": "ready"}}
        if op == "finalize_checkpoint_restore":
            return {"ok": True, "data": {"applied": True, "applied_revision": 8}}
        raise AssertionError(op)

    monkeypatch.setattr(controller, "execute", execute)
    monkeypatch.setattr(controller, "_ensure_live", lambda _project: READY)
    monkeypatch.setattr(
        api.live_session,
        "shutdown_live_session_for_restore",
        lambda _project: {"closed": True},
    )
    monkeypatch.setattr(api.live_session, "ensure_live_session", lambda _project: READY)
    result = controller._restore_checkpoint(
        project,
        {"op": "restore_checkpoint", "name": "good"},
        base_revision=7,
        base_timeline_hash="hash",
        read_token="obs",
        patch_id="restore-good",
    )
    assert result["ok"]
    assert project.read_bytes() == b"checkpoint"
    assert Path(result["data"]["pre_restore_backup"]).read_bytes() == b"current"
