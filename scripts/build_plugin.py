"""Build and verify a deterministic local Codex plugin archive."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
PLUGIN_NAME = "blender-vse"
BUNDLE_ROOT = "blender-vse-marketplace"
MARKETPLACE_NAME = "blender-vse-local"
FIXED_FILES = (
    ".claude-plugin/marketplace.json",
    ".claude-plugin/plugin.json",
    ".codex-plugin/plugin.json",
    ".mcp.json",
    "assets/icon.png",
    "assets/logo.png",
    "assets/logo-dark.png",
    "LICENSE",
    "README.md",
    "README_zh-CN.md",
    "THIRD_PARTY_NOTICES.md",
    "THIRD_PARTY_NOTICES_zh-CN.md",
    "pyproject.toml",
    "scripts/run_plugin_mcp.py",
    "clients/claude/mcp.json",
    "docs/configuration.md",
    "docs/configuration_zh-CN.md",
    "docs/context-model.md",
    "docs/context-model_zh-CN.md",
    "docs/installation.md",
    "docs/installation_zh-CN.md",
    "docs/mcp.md",
    "docs/mcp_zh-CN.md",
    "docs/operations.md",
    "docs/operations_zh-CN.md",
    "docs/plugin.md",
    "docs/plugin_zh-CN.md",
)
TREE_RULES = {
    "LICENSES": {".txt"},
    "skills/blender-vse": {".json", ".md", ".png", ".py", ".yaml"},
    "src/blender_vse": {".json", ".py", ".typed"},
}


def plugin_version() -> str:
    manifest = json.loads(
        (ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    return str(manifest["version"])


def default_output() -> Path:
    return ROOT / "dist" / f"{PLUGIN_NAME}-plugin-{plugin_version()}.zip"


def source_files() -> list[Path]:
    paths = [ROOT / relative for relative in FIXED_FILES]
    for relative_root, suffixes in TREE_RULES.items():
        tree = ROOT / relative_root
        paths.extend(
            path
            for path in tree.rglob("*")
            if path.is_file()
            and (path.suffix in suffixes or path.name == "py.typed")
            and "__pycache__" not in path.parts
        )
    missing = [str(path.relative_to(ROOT)) for path in paths if not path.is_file()]
    if missing:
        raise RuntimeError(f"plugin source files missing: {sorted(missing)}")
    return sorted(set(paths), key=lambda path: path.relative_to(ROOT).as_posix())


def marketplace() -> dict[str, object]:
    return {
        "name": MARKETPLACE_NAME,
        "interface": {"displayName": "Blender VSE Local"},
        "plugins": [
            {
                "name": PLUGIN_NAME,
                "source": {
                    "source": "local",
                    "path": f"./plugins/{PLUGIN_NAME}",
                },
                "policy": {
                    "installation": "AVAILABLE",
                    "authentication": "ON_INSTALL",
                },
                "category": "Productivity",
            }
        ],
    }


def _write_entry(archive: zipfile.ZipFile, name: str, data: bytes) -> None:
    info = zipfile.ZipInfo(name)
    info.date_time = (1980, 1, 1, 0, 0, 0)
    info.create_system = 3
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    archive.writestr(info, data)


def _source_bytes(path: Path) -> bytes:
    if path.suffix.lower() == ".png":
        return path.read_bytes()
    text = path.read_text(encoding="utf-8")
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def _archive_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(
        buffer,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        market_name = f"{BUNDLE_ROOT}/.agents/plugins/marketplace.json"
        market_data = json.dumps(marketplace(), indent=2, ensure_ascii=False) + "\n"
        _write_entry(archive, market_name, market_data.encode("utf-8"))
        for path in source_files():
            relative = path.relative_to(ROOT).as_posix()
            name = f"{BUNDLE_ROOT}/plugins/{PLUGIN_NAME}/{relative}"
            _write_entry(archive, name, _source_bytes(path))
    return buffer.getvalue()


def build(output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(_archive_bytes())
    return output


def verify(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise RuntimeError(f"plugin archive not found: {path}")
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise RuntimeError("plugin archive contains duplicate entries")
        expected = {
            f"{BUNDLE_ROOT}/plugins/{PLUGIN_NAME}/{item.relative_to(ROOT).as_posix()}"
            for item in source_files()
        }
        expected.add(f"{BUNDLE_ROOT}/.agents/plugins/marketplace.json")
        if set(names) != expected:
            raise RuntimeError(
                "plugin archive entries differ from the source allowlist"
            )
        for name in names:
            pure = PurePosixPath(name)
            if pure.is_absolute() or ".." in pure.parts or "\\" in name:
                raise RuntimeError(f"unsafe plugin archive path: {name}")
            lowered = name.lower()
            if any(
                marker in lowered
                for marker in ("/.git/", "/.tmp/", "/__pycache__/", ".pyc")
            ):
                raise RuntimeError(f"plugin archive contains runtime debris: {name}")
        manifest_name = f"{BUNDLE_ROOT}/plugins/{PLUGIN_NAME}/.codex-plugin/plugin.json"
        manifest = json.loads(archive.read(manifest_name).decode("utf-8"))
        if manifest.get("name") != PLUGIN_NAME:
            raise RuntimeError("plugin archive manifest name is inconsistent")
        market_name = f"{BUNDLE_ROOT}/.agents/plugins/marketplace.json"
        market = json.loads(archive.read(market_name).decode("utf-8"))
        if market != marketplace():
            raise RuntimeError("plugin archive marketplace is inconsistent")
    return {
        "path": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "files": len(names),
        "bytes": path.stat().st_size,
        "marketplace": MARKETPLACE_NAME,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    output = (args.output or default_output()).resolve()
    expected = _archive_bytes()
    if args.check:
        if not output.is_file() or output.read_bytes() != expected:
            print(f"plugin archive is missing or stale: {output}", file=sys.stderr)
            return 1
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(expected)
    result = verify(output)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
