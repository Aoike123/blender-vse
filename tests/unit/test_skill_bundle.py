"""The MCP server reads the same Skill files that plugin hosts load."""

from __future__ import annotations

from pathlib import Path

import pytest

from blender_vse.skill import SKILL_FILES, read_skill_file, skill_root

SKILL = Path(__file__).resolve().parents[2] / "skills" / "blender-vse"


def test_source_checkout_resolves_the_canonical_skill() -> None:
    assert skill_root() == SKILL


def test_every_listed_skill_file_exists_and_round_trips() -> None:
    for name in SKILL_FILES:
        assert read_skill_file(name) == (SKILL / name).read_text(encoding="utf-8")


def test_skill_reader_rejects_unlisted_paths() -> None:
    with pytest.raises(KeyError):
        read_skill_file("../../pyproject.toml")
