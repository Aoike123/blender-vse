from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = ROOT / "tests" / "test-plan.json"


def _plan() -> dict:
    return json.loads(PLAN_PATH.read_text(encoding="utf-8"))


def test_profiles_have_bounded_requirements_and_timeouts() -> None:
    profiles = _plan()["profiles"]
    known_requirements = {
        "python",
        "pytest",
        "pytest-cov",
        "jsonschema",
        "mcp",
        "uv",
        "node",
        "npx",
        "dsh",
        "blender",
        "ffmpeg",
        "visible-gui",
    }
    assert set(profiles) == {
        "fast",
        "coverage",
        "mcp",
        "plugin",
        "harness",
        "stateful",
        "blender-headless",
        "blender-smoke",
        "blender-full",
    }
    for profile in profiles.values():
        assert profile["kind"] in {"pytest", "scripts"}
        assert profile["requires"]
        assert set(profile["requires"]) <= known_requirements
        assert 0 < profile["target_seconds"] <= profile["timeout_seconds"] <= 1200
        if profile["kind"] == "scripts":
            assert all(
                key.startswith("BLENDER_VSE_")
                for key in profile.get("environment", {})
            )
            paths = [suite["path"] for suite in profile["scripts"]]
            assert len(paths) == len(set(paths))
            for suite in profile["scripts"]:
                assert (ROOT / suite["path"]).is_file()
                assert 0 < suite["timeout_seconds"] <= 600


def test_fast_profile_is_blender_free() -> None:
    fast = _plan()["profiles"]["fast"]
    assert fast["kind"] == "pytest"
    assert fast["target_seconds"] <= 3
    assert fast["timeout_seconds"] <= 10
    assert "tests/integration" not in fast["args"]
    assert "blender" not in fast["requires"]
    assert "mcp" not in fast["requires"]
    assert "--ignore=tests/contract/test_mcp_server.py" in fast["args"]


def test_mcp_isolated_from_core_fast_matrix() -> None:
    profile = _plan()["profiles"]["mcp"]
    assert profile["kind"] == "pytest"
    assert profile["target_seconds"] <= 4
    assert profile["args"][:2] == [
        "tests/unit/test_mcp_boundary.py",
        "tests/contract/test_mcp_server.py",
    ]
    assert "mcp" in profile["requires"]
    assert "pytest-cov" in profile["requires"]


def test_plugin_profile_runs_only_the_declared_local_transport() -> None:
    profile = _plan()["profiles"]["plugin"]
    assert profile["kind"] == "scripts"
    assert profile["requires"] == ["python", "mcp", "uv"]
    assert len(profile["scripts"]) == 1
    assert profile["scripts"][0]["path"] == "tests/plugin/stdio_smoke.py"
    assert profile["scripts"][0]["direct_mutation"] is False


def test_harness_profile_is_isolated_from_fast_and_gui() -> None:
    profile = _plan()["profiles"]["harness"]
    assert profile["kind"] == "scripts"
    assert profile["requires"] == ["python", "node", "npx", "uv"]
    assert profile["scripts"] == [
        {
            "path": "tests/clients/harness_smoke.py",
            "label": "Claude client packaging",
            "timeout_seconds": 160,
            "direct_mutation": False,
        }
    ]


def test_stateful_profile_is_bounded_and_blender_free() -> None:
    profile = _plan()["profiles"]["stateful"]
    assert profile["kind"] == "scripts"
    assert profile["target_seconds"] <= 5
    assert profile["timeout_seconds"] <= 15
    assert profile["requires"] == ["python", "jsonschema"]
    assert profile["scripts"] == [
        {
            "path": "tests/evals/stateful_workflow.py",
            "label": "stateful context and compaction eval",
            "timeout_seconds": 12,
            "direct_mutation": False,
        }
    ]


def test_smoke_profile_is_one_public_workflow() -> None:
    smoke = _plan()["profiles"]["blender-smoke"]
    assert len(smoke["scripts"]) == 1
    assert smoke["scripts"][0]["path"].endswith("smoke_workflow.py")
    assert smoke["scripts"][0]["direct_mutation"] is False


def test_headless_profile_cannot_adopt_a_running_gui() -> None:
    headless = _plan()["profiles"]["blender-headless"]
    assert headless["execution"] == "headless"
    assert headless["environment"]["BLENDER_VSE_TEST_LIVE"] == "0"


def test_full_profile_owns_every_integration_script() -> None:
    integration_scripts = {
        str(path.relative_to(ROOT)).replace("\\", "/")
        for path in (ROOT / "tests" / "integration").glob("*.py")
    }
    declared = {
        suite["path"] for suite in _plan()["profiles"]["blender-full"]["scripts"]
    }
    assert declared == integration_scripts


def test_runner_can_list_and_dry_run_profiles(capsys) -> None:
    runner_path = ROOT / "tests" / "run.py"
    spec = importlib.util.spec_from_file_location("test_profile_runner", runner_path)
    assert spec and spec.loader
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    assert runner.main(["list"]) == 0
    assert "blender-smoke" in capsys.readouterr().out
    assert runner.main(["fast", "--dry-run"]) == 0
    assert "--basetemp=" in capsys.readouterr().out
