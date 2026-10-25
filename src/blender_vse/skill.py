"""Locate the bundled ``blender-vse`` Skill for the MCP server.

Wheels carry a copy under ``blender_vse/skill`` (see ``setup.py``). Source
checkouts and the plugin tree read the canonical ``skills/blender-vse`` folder.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

SKILL_FILES = (
    "SKILL.md",
    "SKILL_zh-CN.md",
    "references/commands.md",
    "references/commands_zh-CN.md",
    "references/recovery.md",
    "references/recovery_zh-CN.md",
    "references/command-index.json",
)


def skill_root() -> Path | None:
    """Return the folder holding ``SKILL.md``, or ``None`` when it is missing."""

    packaged = Path(str(resources.files(__package__).joinpath("skill")))
    source = Path(__file__).resolve().parents[2] / "skills" / "blender-vse"
    for candidate in (packaged, source):
        if (candidate / "SKILL.md").is_file():
            return candidate
    return None


def read_skill_file(name: str) -> str:
    """Return one Skill file by its path relative to the Skill folder."""

    if name not in SKILL_FILES:
        raise KeyError(name)
    root = skill_root()
    if root is None:
        raise FileNotFoundError("the blender-vse Skill is not bundled with this install")
    return (root / name).read_text(encoding="utf-8")


__all__ = ["SKILL_FILES", "read_skill_file", "skill_root"]
