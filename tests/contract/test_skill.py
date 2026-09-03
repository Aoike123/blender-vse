from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

from jsonschema import Draft7Validator

from blender_vse.catalog import (
    CONTROL_PLANE_COMMANDS,
    PUBLIC_OPERATIONS,
    READ_ONLY_OPERATIONS,
)

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "blender-vse"
INDEX = SKILL / "references" / "command-index.json"
GENERATOR = SKILL / "scripts" / "generate_command_index.py"
POLICY_EXCLUSIONS = {
    "acknowledge_revision",
    "apply_patch",
    "batch",
    "configure_vse_layout",
    "create_project",
    "save_project",
}


def _load_generator():
    spec = importlib.util.spec_from_file_location("skill_command_index", GENERATOR)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _indexed_commands(index: dict) -> set[str]:
    return {command for commands in index["families"].values() for command in commands}


def test_command_index_matches_catalog_and_runtime_signatures(capsys) -> None:
    generator = _load_generator()
    committed = json.loads(INDEX.read_text(encoding="utf-8"))

    assert committed == generator.build_index()
    assert generator.main(["--check"]) == 0
    assert "command index is current" in capsys.readouterr().out

    indexed = _indexed_commands(committed)
    expected = (
        set(PUBLIC_OPERATIONS) - set(READ_ONLY_OPERATIONS) - POLICY_EXCLUSIONS
    ) | set(CONTROL_PLANE_COMMANDS)
    assert indexed == expected
    assert committed["total_commands"] == len(indexed)
    assert set(committed["policy_exclusions"]) == POLICY_EXCLUSIONS
    assert not indexed.intersection(READ_ONLY_OPERATIONS)


def test_patch_examples_validate_and_use_indexed_commands() -> None:
    reference = (SKILL / "references" / "commands.md").read_text(encoding="utf-8")
    examples = re.findall(r"```json\s*(.*?)```", reference, flags=re.DOTALL)
    assert examples
    schema = json.loads(
        (
            ROOT / "src" / "blender_vse" / "schemas" / "edit-command.schema.json"
        ).read_text(encoding="utf-8")
    )
    validator = Draft7Validator(schema)
    indexed = _indexed_commands(json.loads(INDEX.read_text(encoding="utf-8")))

    for block in examples:
        commands = json.loads(block)
        assert isinstance(commands, list) and commands
        for command in commands:
            validator.validate(command)
            assert command["op"] in indexed


def test_skill_has_bounded_progressive_disclosure_and_exact_tool_surface() -> None:
    instruction_files = [
        SKILL / "SKILL.md",
        SKILL / "references" / "commands.md",
        SKILL / "references" / "recovery.md",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in instruction_files)
    tool_names = set(re.findall(r"\bblender_[a-z_]+\b", combined))
    assert tool_names == {
        "blender_read",
        "blender_patch",
        "blender_acknowledge",
        "blender_verify",
    }
    assert all(path.stat().st_size <= 10_000 for path in instruction_files)
    assert INDEX.stat().st_size <= 20_000
    assert "TODO" not in combined
    assert "references/commands.md" in instruction_files[0].read_text(encoding="utf-8")
    assert "references/recovery.md" in instruction_files[0].read_text(encoding="utf-8")


def test_skill_ui_metadata_declares_local_mcp_dependency() -> None:
    metadata = (SKILL / "agents" / "openai.yaml").read_text(encoding="utf-8")
    assert 'value: "blender-vse-control"' in metadata
    assert 'transport: "stdio"' in metadata
    assert "allow_implicit_invocation: true" in metadata
    assert "$blender-vse" in metadata
    assert 'icon_small: "./assets/icon.png"' in metadata
    assert 'icon_large: "./assets/logo.png"' in metadata
    assert 'brand_color: "#E87D0D"' in metadata
    assert (SKILL / "assets" / "icon.png").is_file()
    assert (SKILL / "assets" / "logo.png").is_file()
    description = re.search(r'short_description: "([^"]+)"', metadata)
    assert description and 25 <= len(description.group(1)) <= 64
