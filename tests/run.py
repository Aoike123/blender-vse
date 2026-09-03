"""Run one declared test profile from ``tests/test-plan.json``."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
PLAN_PATH = Path(__file__).with_name("test-plan.json")


def load_plan() -> dict[str, Any]:
    return json.loads(PLAN_PATH.read_text(encoding="utf-8"))


def _command_text(command: list[str]) -> str:
    return subprocess.list2cmdline(command)


def _base_environment() -> dict[str, str]:
    env = dict(os.environ)
    src = str(ROOT / "src")
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = src + (os.pathsep + existing if existing else "")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.setdefault("BLENDER_VSE_TMP_DIR", str(ROOT / ".tmp" / "runtime"))
    return env


def _missing_requirements(requirements: list[str]) -> list[str]:
    missing = []
    if "pytest" in requirements and importlib.util.find_spec("pytest") is None:
        missing.append("pytest (install .[test])")
    if "pytest-cov" in requirements and importlib.util.find_spec("pytest_cov") is None:
        missing.append("pytest-cov (install .[coverage])")
    if "jsonschema" in requirements and importlib.util.find_spec("jsonschema") is None:
        missing.append("jsonschema (install .[test])")
    if "mcp" in requirements and importlib.util.find_spec("mcp") is None:
        missing.append("mcp (install .[test])")
    if "uv" in requirements and shutil.which("uv") is None:
        missing.append("uv executable")
    if "node" in requirements and shutil.which("node") is None:
        missing.append("Node.js executable")
    if "npx" in requirements and shutil.which("npx") is None:
        missing.append("npx executable")
    if "dsh" in requirements and shutil.which("dsh") is None:
        missing.append("DSH executable")
    if "blender" in requirements or "ffmpeg" in requirements:
        sys.path.insert(0, str(ROOT / "src"))
        from blender_vse.blender.config import find_blender, find_ffmpeg

        if "blender" in requirements and not find_blender():
            missing.append("Blender executable")
        if "ffmpeg" in requirements and not find_ffmpeg():
            missing.append("FFmpeg executable")
    return missing


def _run_command(
    command: list[str],
    *,
    env: dict[str, str],
    timeout: int,
    dry_run: bool,
) -> tuple[bool, float, str]:
    print("$ " + _command_text(command), flush=True)
    if dry_run:
        return True, 0.0, "dry-run"
    started = time.perf_counter()
    try:
        result = subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, time.perf_counter() - started, f"timeout after {timeout}s"
    duration = time.perf_counter() - started
    return result.returncode == 0, duration, f"exit {result.returncode}"


def _generate_fixtures(
    env: dict[str, str],
    dry_run: bool,
    timeout: int,
) -> bool:
    command = [sys.executable, str(ROOT / "tests" / "fixtures" / "generate_media.py")]
    passed, duration, status = _run_command(
        command,
        env=env,
        timeout=timeout,
        dry_run=dry_run,
    )
    print(f"  {'PASS' if passed else 'FAIL'} fixtures ({duration:.2f}s, {status})")
    return passed


def run_profile(name: str, profile: dict[str, Any], args: argparse.Namespace) -> int:
    (ROOT / ".tmp").mkdir(exist_ok=True)
    env = _base_environment()
    started = time.perf_counter()
    target = int(profile["target_seconds"])
    hard_timeout = int(profile["timeout_seconds"])
    deadline = started + hard_timeout
    print(f"PROFILE {name}: {profile['description']}")
    print(
        f"Target: {target}s; hard timeout: {hard_timeout}s; "
        f"requires: {', '.join(profile['requires'])}"
    )
    if not args.dry_run:
        missing = _missing_requirements(profile["requires"])
        if missing:
            print("Missing requirements: " + ", ".join(missing))
            return 2

    if profile["kind"] == "pytest":
        pytest_tmp = ROOT / ".tmp" / (
            f"pytest-{name}-{sys.version_info.major}{sys.version_info.minor}-"
            f"{os.getpid()}-{time.time_ns()}"
        )
        command = [
            sys.executable,
            "-m",
            "pytest",
            *profile["args"],
            f"--basetemp={pytest_tmp}",
            *args.pytest_arg,
        ]
        try:
            passed, duration, status = _run_command(
                command,
                env=env,
                timeout=hard_timeout,
                dry_run=args.dry_run,
            )
        finally:
            shutil.rmtree(pytest_tmp, ignore_errors=True)
        pace = "within target" if duration <= target else "over target"
        print(
            f"{'PASS' if passed else 'FAIL'} {name} "
            f"({duration:.2f}s, {pace}, {status})"
        )
        return 0 if passed else 1

    if profile.get("fixtures") and not _generate_fixtures(
        env,
        args.dry_run,
        timeout=min(120, hard_timeout),
    ):
        return 1

    execution = profile.get("execution")
    if execution:
        env["BLENDER_VSE_EXECUTION"] = execution
    env.update(profile.get("environment", {}))

    results: list[tuple[str, bool, float, str]] = []
    for suite in profile["scripts"]:
        remaining = int(deadline - time.perf_counter())
        if remaining <= 0:
            results.append((suite["label"], False, 0.0, "profile hard timeout exhausted"))
            break
        suite_env = dict(env)
        if suite.get("direct_mutation"):
            suite_env["BLENDER_VSE_ALLOW_DIRECT_MUTATION"] = "1"
        else:
            suite_env.pop("BLENDER_VSE_ALLOW_DIRECT_MUTATION", None)
            suite_env.pop("VP_ALLOW_DIRECT_MUTATION", None)
        command = [sys.executable, str(ROOT / suite["path"])]
        passed, duration, status = _run_command(
            command,
            env=suite_env,
            timeout=min(int(suite["timeout_seconds"]), remaining),
            dry_run=args.dry_run,
        )
        results.append((suite["label"], passed, duration, status))
        print(
            f"  {'PASS' if passed else 'FAIL'} {suite['label']} "
            f"({duration:.2f}s, {status})"
        )
        if not passed and not args.keep_going:
            break

    elapsed = time.perf_counter() - started
    print("\nSummary")
    for label, passed, duration, status in results:
        print(f"  {'PASS' if passed else 'FAIL'} {label}: {duration:.2f}s ({status})")
    pace = "within target" if elapsed <= target else "over target"
    print(
        f"Total: {elapsed:.2f}s / target {target}s / hard timeout "
        f"{hard_timeout}s ({pace})"
    )
    return 0 if results and all(item[1] for item in results) else 1


def main(argv: list[str] | None = None) -> int:
    plan = load_plan()
    profiles = plan["profiles"]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", choices=["list", *profiles])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--keep-going",
        action="store_true",
        help="continue a script profile after a failure",
    )
    parser.add_argument(
        "pytest_arg",
        nargs="*",
        help="extra pytest arguments for fast/coverage profiles",
    )
    args = parser.parse_args(argv)
    if args.profile == "list":
        for name, profile in profiles.items():
            print(
                f"{name:18} {profile['kind']:7} "
                f"target={profile['target_seconds']:>4}s  "
                f"timeout={profile['timeout_seconds']:>4}s  {profile['description']}"
            )
        return 0
    return run_profile(args.profile, profiles[args.profile], args)


if __name__ == "__main__":
    raise SystemExit(main())
