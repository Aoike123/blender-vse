from __future__ import annotations

import hashlib
import json
import struct
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "assets"


def _png_size(path: Path) -> tuple[int, int]:
    header = path.read_bytes()[:24]
    assert header[:8] == b"\x89PNG\r\n\x1a\n"
    assert header[12:16] == b"IHDR"
    return struct.unpack(">II", header[16:24])


def test_published_brand_assets_match_manifest() -> None:
    manifest = json.loads((ASSETS / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 1
    assert manifest["brand"] == "Blender VSE Control"
    assert len(manifest["assets"]) == 5
    for entry in manifest["assets"]:
        path = ROOT / entry["path"]
        source = ROOT / entry["source"]
        assert path.is_file() and source.is_file()
        assert _png_size(path) == tuple(entry["dimensions"])
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"]


def test_vector_sources_are_self_contained() -> None:
    for name in ("icon.svg", "logo.svg", "social-preview.svg", "social-preview_zh-CN.svg"):
        path = ASSETS / "source" / name
        root = ET.parse(path).getroot()
        assert root.tag.endswith("svg")
        assert "<image" not in path.read_text(encoding="utf-8")
