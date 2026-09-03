from __future__ import annotations

import json
import re
from pathlib import Path

from blender_vse import __version__

ROOT = Path(__file__).resolve().parents[2]


def test_package_and_source_versions_match() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)
    assert match
    assert match.group(1) == __version__


def test_branch_coverage_floor_stays_meaningful() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r"^fail_under\s*=\s*(\d+)", pyproject, re.MULTILINE)
    assert match
    assert int(match.group(1)) >= 75


def test_source_distribution_manifest_contains_public_artifacts() -> None:
    manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")
    for name in (
        "README_zh-CN.md",
        "RELEASING.md",
        "SECURITY.md",
        "THIRD_PARTY_NOTICES.md",
    ):
        assert f"include {name}" in manifest
    assert "recursive-include docs *.md" in manifest
    assert "recursive-include tests *.py *.md *.json" in manifest


def test_license_and_third_party_notice_are_present() -> None:
    assert "GNU AFFERO GENERAL PUBLIC LICENSE" in (ROOT / "LICENSE").read_text(
        encoding="utf-8"
    )
    assert "MIT License" in (
        ROOT / "LICENSES" / "blender-mcp-MIT.txt"
    ).read_text(encoding="utf-8")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'license = "AGPL-3.0-only"' in pyproject
    assert "THIRD_PARTY_NOTICES.md" in pyproject


def test_test_plan_is_valid_json() -> None:
    plan = json.loads((ROOT / "tests" / "test-plan.json").read_text(encoding="utf-8"))
    assert plan["version"] == 1


def test_ci_runs_parallel_gates_and_builds_once() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    assert workflow.count("python -m build") == 1
    assert "python tests/run.py fast" in workflow
    assert "python tests/run.py coverage" in workflow
    assert "persist-credentials: false" in workflow
    assert "contents: read" in workflow
