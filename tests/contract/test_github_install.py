from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MARKETPLACE = ROOT / ".agents" / "plugins" / "marketplace.json"
PLUGIN_MANIFEST = ROOT / ".codex-plugin" / "plugin.json"
GITHUB_URL = "https://github.com/Aoike123/blender-vse-control.git"


def test_repo_is_a_single_plugin_github_marketplace() -> None:
    marketplace = json.loads(MARKETPLACE.read_text(encoding="utf-8"))
    assert marketplace["name"] == "blender-vse"
    assert marketplace["interface"] == {"displayName": "Blender VSE"}
    assert len(marketplace["plugins"]) == 1

    entry = marketplace["plugins"][0]
    assert entry == {
        "name": "blender-vse",
        "source": {
            "source": "url",
            "url": GITHUB_URL,
            "ref": "main",
        },
        "policy": {
            "installation": "AVAILABLE",
            "authentication": "ON_INSTALL",
        },
        "category": "Productivity",
    }


def test_marketplace_remote_matches_plugin_publisher_metadata() -> None:
    manifest = json.loads(PLUGIN_MANIFEST.read_text(encoding="utf-8"))
    marketplace = json.loads(MARKETPLACE.read_text(encoding="utf-8"))
    entry = marketplace["plugins"][0]

    assert entry["name"] == manifest["name"]
    assert entry["source"]["url"] == manifest["repository"] + ".git"
    assert entry["source"]["source"] == "url"
    assert "path" not in entry["source"]


def test_each_readme_leads_with_localized_install_intent() -> None:
    cases = (
        (
            "README.md",
            "Install this plugin: https://github.com/Aoike123/blender-vse-control",
            "## Core guarantees",
        ),
        (
            "README_zh-CN.md",
            "帮我安装这个插件：https://github.com/Aoike123/blender-vse-control",
            "## 核心保证",
        ),
    )
    for name, prompt, section in cases:
        readme = (ROOT / name).read_text(encoding="utf-8")
        assert prompt in readme
        assert readme.index(prompt) < readme.index(section)
