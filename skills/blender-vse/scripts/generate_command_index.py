"""Generate the Skill's patch-command index from canonical host-side code."""

from __future__ import annotations

import argparse
import inspect
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
OUTPUT = ROOT / "skills" / "blender-vse" / "references" / "command-index.json"

POLICY_EXCLUSIONS = {
    "acknowledge_revision": "use the dedicated blender_acknowledge tool",
    "apply_patch": "the outer blender_patch tool already owns the transaction",
    "batch": "the outer blender_patch command list is already atomic",
    "configure_vse_layout": "visible-session setup owns the editor layout",
    "create_project": "use blender_read with create_if_missing=true",
    "save_project": "a successful outer patch saves the project",
}


def _source_contract():
    if str(SRC) not in sys.path:
        sys.path.insert(0, str(SRC))
    from blender_vse.blender import vse_ops
    from blender_vse.catalog import (
        CATALOG_VERSION,
        CONTROL_PLANE_COMMANDS,
        OPERATION_FAMILIES,
        PUBLIC_OPERATIONS,
        READ_ONLY_OPERATIONS,
    )

    return (
        vse_ops,
        CATALOG_VERSION,
        CONTROL_PLANE_COMMANDS,
        OPERATION_FAMILIES,
        PUBLIC_OPERATIONS,
        READ_ONLY_OPERATIONS,
    )


def _annotation(value: Any) -> str | None:
    if value is inspect.Signature.empty:
        return None
    if isinstance(value, str):
        return value
    return getattr(value, "__name__", str(value))


def _parameter_text(parameter: inspect.Parameter) -> str:
    result = parameter.name
    annotation = _annotation(parameter.annotation)
    if annotation:
        result += f": {annotation}"
    if parameter.default is not inspect.Signature.empty:
        result += f" = {parameter.default!r}"
    return result


def _command_signature(function: Any) -> str:
    parameters = [
        _parameter_text(parameter)
        for parameter in inspect.signature(function).parameters.values()
        if parameter.name != "project"
        and parameter.kind is not inspect.Parameter.VAR_KEYWORD
    ]
    return "(" + ", ".join(parameters) + ")"


def build_index() -> dict[str, Any]:
    (
        vse_ops,
        catalog_version,
        control_plane_commands,
        operation_families,
        public_operations,
        read_only_operations,
    ) = _source_contract()
    family_by_operation = {
        operation: family
        for family, operations in operation_families.items()
        for operation in operations
    }
    command_names = (
        set(public_operations) - set(read_only_operations) - set(POLICY_EXCLUSIONS)
    ) | set(control_plane_commands)
    families: dict[str, dict[str, Any]] = {}
    family_order = [*operation_families, "control_plane"]
    for family in family_order:
        names = sorted(
            name
            for name in command_names
            if (
                "control_plane"
                if name in control_plane_commands
                else family_by_operation[name]
            )
            == family
        )
        if not names:
            continue
        families[family] = {}
        for name in names:
            families[family][name] = {
                "signature": _command_signature(getattr(vse_ops, name))
            }
    return {
        "version": 1,
        "catalog_version": catalog_version,
        "description": (
            "Patch operations approved for the blender-vse Skill. Project and "
            "revision fields belong to the outer MCP tool call."
        ),
        "total_commands": sum(len(commands) for commands in families.values()),
        "policy_exclusions": POLICY_EXCLUSIONS,
        "families": families,
    }


def serialized_index() -> str:
    return json.dumps(build_index(), indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    expected = serialized_index()
    if args.check:
        try:
            current = args.output.read_text(encoding="utf-8")
        except OSError:
            current = ""
        if current != expected:
            print(f"stale command index: {args.output}", file=sys.stderr)
            return 1
        print(f"command index is current: {args.output}")
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(expected, encoding="utf-8", newline="\n")
    print(f"wrote {build_index()['total_commands']} commands: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
