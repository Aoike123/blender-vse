from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from blender_vse.blender import live_session
from blender_vse.blender import runner as runner_module
from blender_vse.blender.runner import BlenderResult, BlenderRunner, RunnerConfig


def _runner(policy: str = "live_session", executable: str = "blender") -> BlenderRunner:
    return BlenderRunner(
        RunnerConfig(blender_executable=executable, execution=policy)
    )


def test_dry_run_always_uses_non_saving_headless_path(monkeypatch) -> None:
    runner = _runner()
    calls = []

    def headless(script, **kwargs):
        calls.append((script, kwargs))
        return BlenderResult(True, mode="dry_run")

    monkeypatch.setattr(runner, "_run_headless", headless)
    result = runner.run_script(
        "pass",
        project="demo.blend",
        save=True,
        dry_run=True,
        script_name="add_text",
    )
    assert result.mode == "dry_run"
    assert calls[0][1]["save"] is False
    assert calls[0][1]["dry_run"] is True


def test_headless_policy_refuses_interactive_mutation() -> None:
    result = _runner("headless").run_script(
        "pass", project="demo.blend", script_name="add_text"
    )
    assert not result.success
    assert "INTERACTIVE VSE edit" in result.error


def test_headless_operation_uses_subprocess_path(monkeypatch) -> None:
    runner = _runner("live_session")
    monkeypatch.setattr(
        runner,
        "_run_headless",
        lambda _script, **_kwargs: BlenderResult(True, mode="headless"),
    )
    assert runner.run_script("pass", script_name="inspect_media").mode == "headless"


def test_interactive_operation_uses_live_path(monkeypatch) -> None:
    runner = _runner("live_session")
    monkeypatch.setattr(
        runner,
        "_run_live",
        lambda _script, **_kwargs: BlenderResult(True, mode="live"),
    )
    assert runner.run_script("pass", script_name="list_strips").mode == "live"


def test_live_path_fails_closed_when_session_proof_is_missing(monkeypatch) -> None:
    runner = _runner()
    monkeypatch.setattr(
        live_session,
        "ensure_live_session",
        lambda _project: {"ready": False, "code": "gui_not_visible"},
    )
    result = runner._run_live(
        "pass",
        project="demo.blend",
        save=False,
        timeout=1,
        script_name="list_strips",
    )
    assert not result.success
    assert "gui_not_visible" in result.error


def test_live_path_parses_payload_and_refreshes(monkeypatch) -> None:
    runner = _runner()
    monkeypatch.setattr(
        live_session,
        "ensure_live_session",
        lambda _project: {"ready": True},
    )
    monkeypatch.setattr(live_session, "refresh_ui_script", lambda: "\n# refresh")
    executed = []

    def execute(code, timeout):
        executed.append((code, timeout))
        return {"success": True, "output": 'VP_RESULT:{"count": 2}\n'}

    monkeypatch.setattr(live_session, "execute_code", execute)
    result = runner._run_live(
        "pass",
        project="demo.blend",
        save=False,
        timeout=2,
        script_name="list_strips",
        refresh_after=True,
    )
    assert result.success and result.payload == {"count": 2}
    assert "# refresh" in executed[0][0]
    assert executed[0][1] == 2


@pytest.mark.parametrize(
    "bridge_result",
    [
        {"success": False, "error": "bridge execution failed", "output": ""},
        {"success": True, "output": "VP_ERROR: explicit error"},
    ],
)
def test_live_path_reports_bridge_and_script_errors(monkeypatch, bridge_result) -> None:
    runner = _runner()
    monkeypatch.setattr(
        live_session,
        "ensure_live_session",
        lambda _project: {"ready": True},
    )
    monkeypatch.setattr(live_session, "execute_code", lambda *_args, **_kwargs: bridge_result)
    result = runner._run_live(
        "pass",
        project="demo.blend",
        save=False,
        timeout=1,
        script_name="list_strips",
    )
    assert not result.success


def test_headless_path_reports_missing_blender() -> None:
    runner = _runner("headless", executable="")
    runner.config.blender_executable = None
    result = runner._run_headless(
        "pass",
        project=None,
        save=False,
        dry_run=False,
        timeout=1,
        script_name="inspect_media",
        args=None,
    )
    assert not result.success and result.error == "blender not found"


def test_headless_path_parses_payload_and_cleans_script(monkeypatch, tmp_path) -> None:
    runner = _runner("headless")
    monkeypatch.setattr(runner_module, "TMP_DIR", tmp_path)
    commands = []

    def run(command, **_kwargs):
        commands.append(command)
        return SimpleNamespace(
            returncode=0,
            stdout='VP_RESULT:{"native": true}\n',
            stderr="",
        )

    monkeypatch.setattr(runner_module.subprocess, "run", run)
    result = runner._run_headless(
        "pass",
        project=None,
        save=False,
        dry_run=False,
        timeout=3,
        script_name="inspect_media",
        args=["extra"],
    )
    assert result.success and result.payload == {"native": True}
    assert "--background" in commands[0]
    assert commands[0][-1] == "extra"
    assert list(tmp_path.glob("vp_*.py")) == []

def test_headless_timeout_is_structured_and_cleans_script(monkeypatch, tmp_path) -> None:
    runner = _runner("headless")
    monkeypatch.setattr(runner_module, "TMP_DIR", tmp_path)
    monkeypatch.setattr(
        runner_module.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            subprocess.TimeoutExpired("blender", 2)
        ),
    )
    result = runner._run_headless(
        "pass",
        project=None,
        save=False,
        dry_run=False,
        timeout=2,
        script_name="inspect_media",
        args=None,
    )
    assert not result.success and "timed out" in result.error
    assert list(tmp_path.glob("vp_*.py")) == []
