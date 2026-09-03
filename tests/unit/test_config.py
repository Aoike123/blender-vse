from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from blender_vse.blender import config, live_session


def test_preferred_environment_name_wins(monkeypatch) -> None:
    monkeypatch.setenv("BLENDER_VSE_EXECUTION", "headless")
    monkeypatch.setenv("VP_BLENDER_EXECUTION", "live_session")
    assert config.execution_policy() == "headless"


def test_legacy_environment_name_remains_compatible(monkeypatch) -> None:
    monkeypatch.delenv("BLENDER_VSE_EXECUTION", raising=False)
    monkeypatch.setenv("VP_BLENDER_EXECUTION", "headless")
    assert config.execution_policy() == "headless"


def test_bridge_host_policy_is_loopback_only() -> None:
    assert live_session._loopback_host("127.0.0.1")
    assert live_session._loopback_host("localhost")
    assert live_session._loopback_host("::1")
    assert not live_session._loopback_host("0.0.0.0")
    assert not live_session._loopback_host("192.168.1.2")


def test_environment_value_precedence(monkeypatch) -> None:
    monkeypatch.setenv("PREFERRED_TEST_SETTING", "preferred")
    monkeypatch.setenv("LEGACY_TEST_SETTING", "legacy")
    assert (
        config.env_value("PREFERRED_TEST_SETTING", "LEGACY_TEST_SETTING", "default")
        == "preferred"
    )
    monkeypatch.delenv("PREFERRED_TEST_SETTING")
    assert (
        config.env_value("PREFERRED_TEST_SETTING", "LEGACY_TEST_SETTING", "default")
        == "legacy"
    )


def test_configured_blender_path_is_discovered(monkeypatch, tmp_path) -> None:
    executable = tmp_path / "blender"
    executable.touch()
    monkeypatch.setenv("BLENDER_VSE_BLENDER_EXECUTABLE", str(executable))
    assert config.find_blender() == str(executable)


def test_blender_version_parses_first_output_line(monkeypatch) -> None:
    monkeypatch.setattr(
        config.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout="Blender 5.1.0\nBuild info",
            stderr="",
        ),
    )
    assert config.blender_version("blender") == "5.1.0"


def test_runtime_tmp_dir_accepts_legacy_alias(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("BLENDER_VSE_TMP_DIR", raising=False)
    monkeypatch.setenv("VP_TMP_DIR", str(tmp_path))
    assert config.runtime_tmp_dir() == tmp_path


def test_default_state_dir_respects_explicit_setting(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("BLENDER_VSE_STATE_DIR", str(tmp_path))
    assert config._default_state_dir() == tmp_path


def test_find_blender_falls_back_to_path(monkeypatch) -> None:
    monkeypatch.setattr(config, "_blender_candidates", lambda: [])
    monkeypatch.setattr(
        config.shutil,
        "which",
        lambda name: "/bin/blender" if name == "blender" else None,
    )
    assert config.find_blender() == "/bin/blender"


@pytest.mark.parametrize(
    "result",
    [
        SimpleNamespace(returncode=1, stdout="", stderr="bad"),
        SimpleNamespace(returncode=0, stdout="", stderr=""),
    ],
)
def test_blender_version_rejects_failed_or_empty_output(monkeypatch, result) -> None:
    monkeypatch.setattr(config.subprocess, "run", lambda *_args, **_kwargs: result)
    assert config.blender_version("blender") is None


def test_blender_version_handles_process_error(monkeypatch) -> None:
    monkeypatch.setattr(
        config.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("missing")),
    )
    assert config.blender_version("blender") is None


def test_blender_python_finds_versioned_runtime(monkeypatch, tmp_path) -> None:
    executable = tmp_path / "blender"
    executable.touch()
    python = tmp_path / "5.1.0" / "python" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.touch()
    monkeypatch.setattr(config, "blender_version", lambda _executable: "5.1.0")
    assert config.blender_python(str(executable)) == str(python)


@pytest.mark.parametrize(
    ("finder", "setting"),
    [("find_ffmpeg", "BLENDER_VSE_FFMPEG"), ("find_ffprobe", "BLENDER_VSE_FFPROBE")],
)
def test_media_tool_override(monkeypatch, tmp_path, finder: str, setting: str) -> None:
    executable = tmp_path / finder
    executable.touch()
    monkeypatch.setenv(setting, str(executable))
    assert getattr(config, finder)() == str(executable)


def test_version_helper_uses_stdout_or_stderr(monkeypatch) -> None:
    monkeypatch.setattr(
        config.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout="",
            stderr="tool 1.2\nmore",
        ),
    )
    assert config._version(["tool", "--version"]) == "tool 1.2"


def test_environment_report_is_structured(monkeypatch) -> None:
    monkeypatch.setattr(config, "find_blender", lambda: "/blender")
    monkeypatch.setattr(config, "blender_version", lambda _value: "5.1.0")
    monkeypatch.setattr(config, "blender_python", lambda _value: "/python")
    monkeypatch.setattr(config, "find_ffmpeg", lambda: "/ffmpeg")
    monkeypatch.setattr(config, "find_ffprobe", lambda: "/ffprobe")
    monkeypatch.setattr(config.shutil, "which", lambda name: f"/{name}")
    monkeypatch.setattr(config, "_version", lambda _command: "v1")
    monkeypatch.setattr(
        live_session,
        "check_live_session",
        lambda: {
            "live_session": True,
            "gui_visible": True,
            "bridge_host": "127.0.0.1",
            "bridge_port": 10850,
            "mode": "live_session",
        },
    )
    report = config.environment_report()
    assert report["blender"]["available"] is True
    assert report["ffmpeg"]["available"] is True
    assert report["blender_execution"]["gui_visible"] is True
    assert "project_storage" in report
    python_setup = report["setup"]["python"]
    assert python_setup["strategy"] == "uv-managed"
    assert python_setup["managed_version"] == "3.12"
    assert python_setup["system_python_required"] is False
    assert python_setup["uv_preinstalled_required"] is False
    assert python_setup["bootstrap"] == "request_permission_then_install_uv"
    assert python_setup["uv_available"] is True
    assert python_setup["uv_executable"] == "/uv"
    assert report["setup"]["blender"]["available"] is True
    assert report["setup"]["ffmpeg"]["available"] is True


def test_project_storage_report_requires_the_preferred_explicit_variable(
    tmp_path,
) -> None:
    default = tmp_path / "default-projects"
    report = config.project_storage_report(
        environ={},
        default_projects_dir=default,
    )
    assert report == {
        "projects_dir": str(default.resolve()),
        "configuration_source": "os-default",
        "explicitly_configured": False,
        "ready": False,
        "configuration_required": True,
        "allowed_roots": [str(default.resolve())],
        "allowed_roots_source": "projects_dir",
    }


def test_project_storage_report_uses_configured_directory_and_roots(tmp_path) -> None:
    projects = (tmp_path / "video projects").resolve()
    shared = (tmp_path / "shared").resolve()
    report = config.project_storage_report(
        environ={
            "BLENDER_VSE_PROJECTS_DIR": str(projects),
            "BLENDER_VSE_ALLOWED_ROOTS": config.os.pathsep.join(
                (str(projects), str(shared))
            ),
        },
        default_projects_dir=tmp_path / "unused",
    )
    assert report["projects_dir"] == str(projects)
    assert report["configuration_source"] == "BLENDER_VSE_PROJECTS_DIR"
    assert report["explicitly_configured"] is True
    assert report["ready"] is True
    assert report["configuration_required"] is False
    assert report["allowed_roots"] == [str(projects), str(shared)]
    assert report["allowed_roots_source"] == "BLENDER_VSE_ALLOWED_ROOTS"


def test_project_storage_report_marks_relative_configuration_not_ready() -> None:
    report = config.project_storage_report(
        environ={"BLENDER_VSE_PROJECTS_DIR": "relative-projects"},
        default_projects_dir=Path("unused"),
    )
    assert report["explicitly_configured"] is True
    assert report["ready"] is False
    assert report["configuration_required"] is True


def test_environment_report_guides_missing_runtime_dependencies(monkeypatch) -> None:
    monkeypatch.setattr(config, "find_blender", lambda: None)
    monkeypatch.setattr(config, "find_ffmpeg", lambda: None)
    monkeypatch.setattr(config, "find_ffprobe", lambda: None)
    monkeypatch.setattr(config.shutil, "which", lambda _name: None)
    monkeypatch.setattr(config, "_version", lambda _command: None)
    monkeypatch.setattr(
        live_session,
        "check_live_session",
        lambda: {"live_session": False, "gui_visible": False},
    )

    report = config.environment_report()
    setup = report["setup"]
    assert setup["python"]["system_python_required"] is False
    assert setup["python"]["uv_preinstalled_required"] is False
    assert setup["python"]["uv_available"] is False
    assert setup["blender"]["install_url"] == "https://www.blender.org/download/"
    assert setup["ffmpeg"]["install_url"] == "https://ffmpeg.org/download.html"
    assert setup["installation_ready_for_editing"] is False
    assert setup["installation_ready_for_full_features"] is False
    assert {
        "install_uv_with_user_approval",
        "install_blender",
        "install_ffmpeg",
    } <= set(setup["next_actions"])
