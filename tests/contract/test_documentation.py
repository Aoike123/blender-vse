from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[2]
LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
HAN = re.compile(r"[\u3400-\u9fff]")
IGNORED_TREES = {
    ".agents",
    ".git",
    ".tmp",
    ".venv",
    ".wheel-check",
    "build",
    "dist",
    "venv",
}


def _markdown_files():
    for current, directories, files in os.walk(ROOT):
        directories[:] = [name for name in directories if name not in IGNORED_TREES]
        base = Path(current)
        for name in files:
            if name.endswith(".md"):
                yield base / name


def _local_links(markdown: Path):
    for match in LINK.finditer(markdown.read_text(encoding="utf-8")):
        target = match.group(1).strip().strip("<>")
        if not target or target.startswith(("#", "http://", "https://", "mailto:")):
            continue
        path_part = unquote(target.split("#", 1)[0])
        if path_part:
            yield (markdown.parent / path_part).resolve(), target


def test_all_relative_markdown_links_resolve() -> None:
    broken = []
    for markdown in _markdown_files():
        for target, raw in _local_links(markdown):
            if not target.exists():
                broken.append(f"{markdown.relative_to(ROOT)} -> {raw}")
    assert broken == []


def test_readmes_point_to_the_documentation_hub_and_test_flow() -> None:
    expected = {
        "README.md": ("docs/index.md", "docs/testing.md"),
        "README_zh-CN.md": ("docs/index_zh-CN.md", "docs/testing_zh-CN.md"),
    }
    for name, links in expected.items():
        text = (ROOT / name).read_text(encoding="utf-8")
        assert all(link in text for link in links)


def test_every_markdown_document_has_a_separate_chinese_mirror() -> None:
    english = [path for path in _markdown_files() if not path.name.endswith("_zh-CN.md")]
    assert english
    for path in english:
        chinese = path.with_name(f"{path.stem}_zh-CN.md")
        assert chinese.is_file(), f"missing Chinese mirror for {path.relative_to(ROOT)}"
        english_text = path.read_text(encoding="utf-8")
        chinese_text = chinese.read_text(encoding="utf-8")
        assert HAN.search(english_text) is None, f"mixed Chinese prose in {path.relative_to(ROOT)}"
        assert HAN.search(chinese_text), f"Chinese mirror has no Chinese prose: {chinese.relative_to(ROOT)}"
        assert chinese.name in english_text
        assert path.name in chinese_text


def test_security_critical_topics_are_documented() -> None:
    security = (ROOT / "SECURITY.md").read_text(encoding="utf-8").lower()
    architecture = (ROOT / "docs" / "architecture.md").read_text(
        encoding="utf-8"
    ).lower()
    assert "loopback" in security
    assert "no authentication" in security
    assert "read" in architecture and "patch" in architecture
    assert "source of truth" in architecture
