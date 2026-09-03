from __future__ import annotations

import ast

import pytest

from blender_vse.blender.runner import BlenderResult, BlenderRunnerError
from blender_vse.blender.vse_ops import _j, _py, _q, dispatch


class RecordingRunner:
    def __init__(self):
        self.calls = []

    def run_script(self, script, **kwargs):
        self.calls.append((script, kwargs))
        return BlenderResult(True, payload={"recorded": True}, mode="dry_run")


def test_string_encoders_produce_parseable_literals() -> None:
    hostile = "x'); __import__('os').system('bad') #\n"
    for literal in (_j(hostile), _q(hostile), _py({"value": hostile, "ok": True})):
        tree = ast.parse("value = " + literal)
        assert isinstance(tree.body[0], ast.Assign)
    assert ast.literal_eval(_q(hostile)) == hostile


@pytest.mark.parametrize("operation", ["open_project", "resolve_strip"])
def test_read_only_operations_never_save_or_refresh(operation: str) -> None:
    runner = RecordingRunner()
    params = {"project": "demo.blend"}
    if operation == "resolve_strip":
        params["target"] = "Title"
    dispatch(operation, runner, "demo.blend", params)
    _, options = runner.calls[0]
    assert options["save"] is False
    assert options["refresh_after"] is False


def test_direct_mutation_is_blocked_before_runner(monkeypatch) -> None:
    runner = RecordingRunner()
    monkeypatch.delenv("BLENDER_VSE_ALLOW_DIRECT_MUTATION", raising=False)
    monkeypatch.delenv("VP_ALLOW_DIRECT_MUTATION", raising=False)
    with pytest.raises(BlenderRunnerError) as caught:
        dispatch(
            "set_text",
            runner,
            "demo.blend",
            {"project": "demo.blend", "target": "Title", "text": "new"},
        )
    assert caught.value.code == "internal_primitive"
    assert runner.calls == []


def test_internal_harness_can_opt_into_direct_mutation(monkeypatch) -> None:
    runner = RecordingRunner()
    monkeypatch.setenv("BLENDER_VSE_ALLOW_DIRECT_MUTATION", "1")
    dispatch(
        "set_text",
        runner,
        "demo.blend",
        {"project": "demo.blend", "target": "Title", "text": "new"},
    )
    _, options = runner.calls[0]
    assert options["save"] is True
    assert options["refresh_after"] is True


def test_removed_operation_uses_catalog_error() -> None:
    with pytest.raises(BlenderRunnerError) as caught:
        dispatch(
            "generate_proxy",
            RecordingRunner(),
            "demo.blend",
            {"project": "demo.blend"},
        )
    assert caught.value.code == "proxy_generation_externalized"
