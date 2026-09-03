from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from blender_vse.blender.runner import BlenderRunnerError
from blender_vse.blender.vse_ops import _load_proxy_manifest


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path) -> tuple[Path, dict]:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source-content")
    project_dir = tmp_path / "proxy-project"
    project_dir.mkdir()
    proxy = project_dir / "proxy_25.avi"
    proxy.write_bytes(b"proxy-content")
    manifest = project_dir / "proxy.json"
    data = {
        "version": "1.0",
        "tool": "example-ffmpeg-builder",
        "tool_version": "1.0.0",
        "profile": "blender-mjpeg",
        "scale": 25,
        "project_dir": str(project_dir),
        "source_path": str(source),
        "source_sha256": _sha256(source),
        "source_size": source.stat().st_size,
        "source_mtime_ns": source.stat().st_mtime_ns,
        "proxy_path": str(proxy),
        "proxy_sha256": _sha256(proxy),
        "proxy_size": proxy.stat().st_size,
        "source_facts": {},
        "proxy_facts": {},
        "verified": True,
        "created_at": 1.0,
    }
    return manifest, data


def _write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def test_manifest_accepts_a_host_owned_proxy_builder(tmp_path: Path) -> None:
    manifest, data = _fixture(tmp_path)
    _write(manifest, data)
    loaded = _load_proxy_manifest(str(manifest))
    assert loaded["tool"] == "example-ffmpeg-builder"
    assert loaded["manifest_path"] == str(manifest.resolve())


def test_missing_manifest_fails_before_blender(tmp_path: Path) -> None:
    with pytest.raises(BlenderRunnerError) as caught:
        _load_proxy_manifest(str(tmp_path / "missing.json"))
    assert caught.value.code == "input_missing"


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda data: data.pop("proxy_sha256"), "invalid_proxy_manifest"),
        (lambda data: data.update({"unexpected": True}), "invalid_proxy_manifest"),
        (lambda data: data.update({"verified": False}), "invalid_proxy_manifest"),
        (lambda data: data.update({"scale": 10}), "invalid_proxy_manifest"),
        (lambda data: data.update({"source_sha256": "x" * 64}), "invalid_proxy_manifest"),
    ],
)
def test_manifest_rejects_invalid_contract_fields(
    tmp_path: Path,
    mutation,
    code: str,
) -> None:
    manifest, data = _fixture(tmp_path)
    mutation(data)
    _write(manifest, data)
    with pytest.raises(BlenderRunnerError) as caught:
        _load_proxy_manifest(str(manifest))
    assert caught.value.code == code


def test_manifest_rejects_proxy_path_escape(tmp_path: Path) -> None:
    manifest, data = _fixture(tmp_path)
    escaped = tmp_path / "escaped.avi"
    escaped.write_bytes(b"proxy-content")
    data.update(
        {
            "proxy_path": str(escaped),
            "proxy_sha256": _sha256(escaped),
            "proxy_size": escaped.stat().st_size,
        }
    )
    _write(manifest, data)
    with pytest.raises(BlenderRunnerError) as caught:
        _load_proxy_manifest(str(manifest))
    assert caught.value.code == "invalid_proxy_manifest"


def test_manifest_detects_source_change(tmp_path: Path) -> None:
    manifest, data = _fixture(tmp_path)
    _write(manifest, data)
    Path(data["source_path"]).write_bytes(b"changed-source-content")
    with pytest.raises(BlenderRunnerError) as caught:
        _load_proxy_manifest(str(manifest))
    assert caught.value.code == "stale_proxy_source"


def test_manifest_detects_proxy_change(tmp_path: Path) -> None:
    manifest, data = _fixture(tmp_path)
    _write(manifest, data)
    Path(data["proxy_path"]).write_bytes(b"changed-proxy-content")
    with pytest.raises(BlenderRunnerError) as caught:
        _load_proxy_manifest(str(manifest))
    assert caught.value.code == "invalid_proxy_manifest"
