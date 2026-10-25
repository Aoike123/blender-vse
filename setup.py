"""Bundle the canonical Skill into the wheel.

``skills/blender-vse`` stays the single source of truth for plugin hosts. The
build copies its Markdown and JSON files into ``blender_vse/skill`` so the MCP
server can serve the same Skill when installed with ``uv tool`` or pip.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py

SKILL_SOURCE = Path(__file__).resolve().parent / "skills" / "blender-vse"
SKILL_PATTERNS = ("*.md", "references/*.md", "references/*.json")


class BuildPyWithSkill(build_py):
    def run(self) -> None:
        super().run()
        target = Path(self.build_lib) / "blender_vse" / "skill"
        for pattern in SKILL_PATTERNS:
            for source in SKILL_SOURCE.glob(pattern):
                destination = target / source.relative_to(SKILL_SOURCE)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)


setup(cmdclass={"build_py": BuildPyWithSkill})
