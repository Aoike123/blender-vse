"""Verify source and wheel archive contents after a package build."""

from __future__ import annotations

import argparse
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IGNORED_SOURCE_PARTS = {".agents", ".git", ".tmp", ".venv", "build", "dist"}
LOCALIZED_MARKDOWN = {
    path.relative_to(ROOT).as_posix()
    for path in ROOT.rglob("*_zh-CN.md")
    if not IGNORED_SOURCE_PARTS.intersection(path.relative_to(ROOT).parts)
}

WHEEL_REQUIRED = {
    "blender_vse/api.py",
    "blender_vse/catalog.py",
    "blender_vse/cli.py",
    "blender_vse/context.py",
    "blender_vse/context-policy.json",
    "blender_vse/mcp/__init__.py",
    "blender_vse/mcp/boundary.py",
    "blender_vse/mcp/server.py",
    "blender_vse/resume.py",
    "blender_vse/blender/bridge/blender_bridge_addon.py",
    "blender_vse/schemas/edit-command.schema.json",
    "blender_vse/schemas/media-info.schema.json",
    "blender_vse/schemas/operation-result.schema.json",
    "blender_vse/schemas/proxy-manifest.schema.json",
    "blender_vse/schemas/read-query.schema.json",
    "blender_vse/schemas/read-result.schema.json",
    "blender_vse/schemas/resume-capsule.schema.json",
    "blender_vse/schemas/timeline-state.schema.json",
}

SDIST_REQUIRED = {
    ".agents/plugins/marketplace.json",
    ".claude-plugin/marketplace.json",
    ".claude-plugin/plugin.json",
    ".codex-plugin/plugin.json",
    ".mcp.json",
    "CHANGELOG.md",
    "install.sh",
    "install.ps1",
    "CODE_OF_CONDUCT.md",
    "CONTRIBUTING.md",
    "README.md",
    "README_zh-CN.md",
    "RELEASING.md",
    "SECURITY.md",
    "THIRD_PARTY_NOTICES.md",
    "assets/manifest.json",
    "assets/icon.png",
    "assets/logo.png",
    "assets/logo-dark.png",
    "assets/social-preview.png",
    "assets/social-preview_zh-CN.png",
    "assets/source/icon.svg",
    "assets/source/logo.svg",
    "assets/source/social-preview.svg",
    "assets/source/social-preview_zh-CN.svg",
    "clients/claude/mcp.json",
    "docs/index.md",
    "docs/getting-started.md",
    "docs/api.md",
    "docs/operations.md",
    "docs/architecture.md",
    "docs/configuration.md",
    "docs/context-model.md",
    "docs/installation.md",
    "docs/mcp.md",
    "docs/plugin.md",
    "docs/testing.md",
    "evals/README.md",
    "evals/baseline.json",
    "evals/stateful-scenarios.json",
    "skills/blender-vse/SKILL.md",
    "skills/blender-vse/agents/openai.yaml",
    "skills/blender-vse/assets/icon.png",
    "skills/blender-vse/assets/logo.png",
    "skills/blender-vse/references/command-index.json",
    "skills/blender-vse/references/commands.md",
    "skills/blender-vse/references/recovery.md",
    "skills/blender-vse/scripts/generate_command_index.py",
    "scripts/build_plugin.py",
    "scripts/run_plugin_mcp.py",
    "tests/contract/test_brand_assets.py",
    "tests/contract/test_github_install.py",
    "tests/contract/test_plugin.py",
    "tests/plugin/stdio_smoke.py",
    "tests/clients/harness_smoke.py",
    "tests/evals/stateful_workflow.py",
    "tests/test-plan.json",
    "tests/run.py",
    "tests/verify_distribution.py",
} | LOCALIZED_MARKDOWN


def _one(directory: Path, pattern: str) -> Path:
    matches = sorted(directory.glob(pattern))
    if len(matches) != 1:
        raise RuntimeError(f"expected one {pattern} in {directory}, found {len(matches)}")
    return matches[0]


def verify(directory: Path) -> None:
    wheel = _one(directory, "*.whl")
    sdist = _one(directory, "*.tar.gz")

    with zipfile.ZipFile(wheel) as archive:
        wheel_names = set(archive.namelist())
        missing = sorted(WHEEL_REQUIRED - wheel_names)
        if missing:
            raise RuntimeError(f"wheel missing: {missing}")
        for suffix in (
            ".dist-info/licenses/LICENSE",
            ".dist-info/licenses/THIRD_PARTY_NOTICES.md",
            ".dist-info/licenses/LICENSES/blender-mcp-MIT.txt",
            ".dist-info/entry_points.txt",
        ):
            if not any(name.endswith(suffix) for name in wheel_names):
                raise RuntimeError(f"wheel missing metadata suffix: {suffix}")
        entry_name = next(
            name for name in wheel_names if name.endswith(".dist-info/entry_points.txt")
        )
        entry_points = archive.read(entry_name).decode("utf-8")
        for entry in (
            "blender-vse = blender_vse.cli:main",
            "blender-vse-mcp = blender_vse.mcp:main",
        ):
            if entry not in entry_points:
                raise RuntimeError(f"wheel missing console entry point: {entry}")
        if any("__pycache__" in name or name.endswith(".pyc") for name in wheel_names):
            raise RuntimeError("wheel contains Python cache artifacts")

    with tarfile.open(sdist) as archive:
        names = archive.getnames()
        roots = {name.split("/", 1)[0] for name in names if "/" in name}
        if len(roots) != 1:
            raise RuntimeError(f"source archive has ambiguous roots: {sorted(roots)}")
        root = next(iter(roots))
        relative = {
            name[len(root) + 1 :]
            for name in names
            if name.startswith(root + "/")
        }
        missing = sorted(SDIST_REQUIRED - relative)
        if missing:
            raise RuntimeError(f"source archive missing: {missing}")
        media = sorted(
            name
            for name in relative
            if Path(name).suffix.lower() in {".avi", ".mkv", ".mov", ".mp3", ".mp4"}
        )
        if media:
            raise RuntimeError(f"source archive contains opaque media: {media}")

    print(f"verified wheel: {wheel.name} ({len(wheel_names)} files)")
    print(f"verified source: {sdist.name} ({len(relative)} entries)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", default="dist", type=Path)
    args = parser.parse_args()
    verify(args.directory.resolve())


if __name__ == "__main__":
    main()
