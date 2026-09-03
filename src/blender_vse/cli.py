"""Command-line interface for :mod:`blender_vse`."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from . import __version__
from .api import BlenderVSE
from .blender import environment_report
from .catalog import OPERATION_FAMILIES, operation_catalog
from .context import CONTEXT_POLICY, DEFAULT_READ_VIEW, INCLUDE_GROUPS, READ_VIEWS


def _json_value(value: str) -> Any:
    """Load JSON directly or from ``@path``."""

    if value.startswith("@"):
        path = Path(value[1:]).expanduser()
        return json.loads(path.read_text(encoding="utf-8"))
    return json.loads(value)


def _print(result: Any) -> int:
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return 0 if not isinstance(result, dict) or result.get("ok", True) else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="blender-vse",
        description="Revision-safe control for Blender's Video Sequence Editor",
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="show environment and bridge readiness")
    sub.add_parser(
        "context-policy", help="show context views, budgets, and resume rules"
    )
    ops = sub.add_parser("ops", help="list allowlisted operations")
    ops.add_argument(
        "--family",
        choices=sorted(OPERATION_FAMILIES),
        help="show only one operation family",
    )

    read = sub.add_parser("read", help="read revision and timeline state")
    read.add_argument("project")
    read.add_argument("--create", action="store_true", help="create when missing")
    read.add_argument("--resolution", nargs=2, type=int, default=(1920, 1080))
    read.add_argument("--fps", type=int, default=30)
    read.add_argument(
        "--view",
        choices=sorted(READ_VIEWS),
        default=DEFAULT_READ_VIEW,
        help="context projection; summary is the bounded default",
    )
    read.add_argument("--frame-range", nargs=2, type=int, metavar=("START", "END"))
    read.add_argument("--strip-id", dest="strip_ids", action="append")
    read.add_argument("--channel", dest="channels", action="append", type=int)
    read.add_argument("--type", dest="strip_types", action="append")
    read.add_argument(
        "--include",
        action="append",
        choices=sorted(INCLUDE_GROUPS),
        help="optional strip field group; may be repeated",
    )
    read.add_argument("--cursor", help="opaque next_cursor from a prior page")
    read.add_argument("--limit", type=int, help="page size for range/detail")

    patch = sub.add_parser("patch", help="apply an atomic edit patch")
    patch.add_argument("project")
    patch.add_argument("--base-revision", required=True, type=int)
    patch.add_argument("--base-timeline-hash", required=True)
    patch.add_argument("--read-token", required=True)
    patch.add_argument("--patch-id", required=True)
    patch.add_argument(
        "--commands",
        required=True,
        help="JSON array, or @path to a JSON file",
    )

    acknowledge = sub.add_parser("acknowledge", help="adopt an observed manual edit")
    acknowledge.add_argument("project")
    acknowledge.add_argument("--observed-revision", required=True, type=int)
    acknowledge.add_argument("--observed-hash", required=True)
    acknowledge.add_argument("--read-token", required=True)

    verify = sub.add_parser(
        "verify", help="verify project persistence in fresh Blender"
    )
    verify.add_argument("project")
    verify.add_argument("--expected", help="JSON object or @path")

    execute = sub.add_parser(
        "execute", help="execute an allowlisted low-level operation"
    )
    execute.add_argument("op")
    execute.add_argument("--project")
    execute.add_argument("--params", default="{}", help="JSON object or @path")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    controller = BlenderVSE()
    try:
        if args.command == "status":
            return _print({"ok": True, "environment": environment_report()})
        if args.command == "context-policy":
            return _print({"ok": True, "context_policy": CONTEXT_POLICY})
        if args.command == "ops":
            catalog = operation_catalog()
            if args.family:
                catalog = {
                    "catalog_version": catalog["catalog_version"],
                    "family": args.family,
                    "operations": catalog["families"][args.family],
                }
            return _print({"ok": True, **catalog})
        if args.command == "read":
            return _print(
                controller.read(
                    args.project,
                    create_if_missing=args.create,
                    resolution=tuple(args.resolution),
                    fps=args.fps,
                    view=args.view,
                    frame_range=tuple(args.frame_range) if args.frame_range else None,
                    strip_ids=args.strip_ids,
                    channels=args.channels,
                    strip_types=args.strip_types,
                    include=args.include,
                    cursor=args.cursor,
                    limit=args.limit,
                )
            )
        if args.command == "patch":
            commands = _json_value(args.commands)
            if not isinstance(commands, list):
                raise ValueError("--commands must contain a JSON array")
            return _print(
                controller.patch(
                    args.project,
                    base_revision=args.base_revision,
                    base_timeline_hash=args.base_timeline_hash,
                    read_token=args.read_token,
                    patch_id=args.patch_id,
                    commands=commands,
                )
            )
        if args.command == "acknowledge":
            return _print(
                controller.acknowledge(
                    args.project,
                    observed_revision=args.observed_revision,
                    observed_hash=args.observed_hash,
                    read_token=args.read_token,
                )
            )
        if args.command == "verify":
            expected = _json_value(args.expected) if args.expected else None
            if expected is not None and not isinstance(expected, dict):
                raise ValueError("--expected must contain a JSON object")
            return _print(controller.verify(args.project, expected=expected))
        if args.command == "execute":
            params = _json_value(args.params)
            if not isinstance(params, dict):
                raise ValueError("--params must contain a JSON object")
            if args.project:
                params["project"] = args.project
            return _print(controller.execute(args.op, params))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _print(
            {
                "ok": False,
                "error": {"code": "invalid_cli_input", "message": str(exc)},
            }
        )
    return 2


if __name__ == "__main__":
    sys.exit(main())
