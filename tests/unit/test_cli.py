from __future__ import annotations

import json

from blender_vse import cli


def test_ops_prints_json(capsys) -> None:
    assert cli.main(["ops"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert "apply_patch" in payload["operations"]


def test_patch_requires_json_array(tmp_path, capsys) -> None:
    command_file = tmp_path / "commands.json"
    command_file.write_text('{"op":"add_text"}', encoding="utf-8")
    assert (
        cli.main(
            [
                "patch",
                "demo.blend",
                "--base-revision",
                "0",
                "--base-timeline-hash",
                "hash",
                "--read-token",
                "token",
                "--patch-id",
                "patch-1",
                "--commands",
                "@" + str(command_file),
            ]
        )
        == 1
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "invalid_cli_input"


def test_ops_can_be_filtered_by_family(capsys) -> None:
    assert cli.main(["ops", "--family", "revision"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["family"] == "revision"
    assert set(payload["operations"]) == {
        "get_revision",
        "apply_patch",
        "acknowledge_revision",
    }


def test_context_policy_command_is_machine_readable(capsys) -> None:
    assert cli.main(["context-policy"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["context_policy"]["default_view"] == "summary"
    assert payload["context_policy"]["views"]["detail"]["max_bytes"] == 16_384


def test_json_value_supports_inline_and_file_inputs(tmp_path) -> None:
    path = tmp_path / "value.json"
    path.write_text('{"from":"file"}', encoding="utf-8")
    assert cli._json_value('{"inline":true}') == {"inline": True}
    assert cli._json_value("@" + str(path)) == {"from": "file"}


def test_read_command_forwards_creation_options(monkeypatch, capsys) -> None:
    calls = []

    class Controller:
        def read(self, project, **kwargs):
            calls.append((project, kwargs))
            return {"ok": True, "op": "read", "data": {}}

    monkeypatch.setattr(cli, "BlenderVSE", Controller)
    assert (
        cli.main(
            [
                "read",
                "demo.blend",
                "--create",
                "--resolution",
                "640",
                "360",
                "--fps",
                "24",
            ]
        )
        == 0
    )
    assert calls == [
        (
            "demo.blend",
            {
                "create_if_missing": True,
                "resolution": (640, 360),
                "fps": 24,
                "view": "summary",
                "frame_range": None,
                "strip_ids": None,
                "channels": None,
                "strip_types": None,
                "include": None,
                "cursor": None,
                "limit": None,
            },
        )
    ]
    assert json.loads(capsys.readouterr().out)["ok"] is True


def test_execute_command_merges_project_into_params(monkeypatch, capsys) -> None:
    calls = []

    class Controller:
        def execute(self, operation, params):
            calls.append((operation, params))
            return {"ok": True, "op": operation, "data": {}}

    monkeypatch.setattr(cli, "BlenderVSE", Controller)
    assert (
        cli.main(
            [
                "execute",
                "list_strips",
                "--project",
                "demo.blend",
                "--params",
                '{"with_text":true}',
            ]
        )
        == 0
    )
    assert calls == [("list_strips", {"with_text": True, "project": "demo.blend"})]
    assert json.loads(capsys.readouterr().out)["ok"] is True


def test_status_uses_structured_environment_report(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        cli, "environment_report", lambda: {"blender": {"available": False}}
    )
    assert cli.main(["status"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["environment"]["blender"]["available"] is False


def test_execute_rejects_non_object_params(capsys) -> None:
    assert cli.main(["execute", "list_strips", "--params", "[]"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "invalid_cli_input"


def test_read_command_forwards_bounded_query(monkeypatch, capsys) -> None:
    calls = []

    class Controller:
        def read(self, project, **kwargs):
            calls.append((project, kwargs))
            return {"ok": True, "op": "read", "data": {}}

    monkeypatch.setattr(cli, "BlenderVSE", Controller)
    assert (
        cli.main(
            [
                "read",
                "demo.blend",
                "--view",
                "detail",
                "--strip-id",
                "title",
                "--channel",
                "3",
                "--type",
                "text",
                "--include",
                "text",
                "--include",
                "metadata",
                "--limit",
                "10",
            ]
        )
        == 0
    )
    kwargs = calls[0][1]
    assert kwargs["view"] == "detail"
    assert kwargs["strip_ids"] == ["title"]
    assert kwargs["channels"] == [3]
    assert kwargs["strip_types"] == ["text"]
    assert kwargs["include"] == ["text", "metadata"]
    assert kwargs["limit"] == 10
    assert json.loads(capsys.readouterr().out)["ok"] is True
