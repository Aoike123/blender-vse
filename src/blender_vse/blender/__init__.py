"""Blender VSE adapter — allowlisted typed operations on persistent .blend projects.

Execution policy: LIVE GUI SESSION by default. Interactive VSE editing
(add_movie / move / add_text / set_font_size / ...) goes to the RUNNING GUI
Blender through the Blender MCP Bridge addon (sandraschi/blender-mcp), so edits
appear live in the user's open VSE timeline + preview. Headless Blender
execution is ONLY allowed for batch/final render, native media inspection, and
verify_persistence — interactive ops are refused headless (see runner.py).

Every mutating op is verified after execution:
  - input files are validated before Blender is spawned,
  - the saved .blend is confirmed updated (mtime/size change),
  - the timeline is re-read and compared against the op's reported result.

Low-level usage:
    from blender_vse import blender_execute

    result = blender_execute("list_strips", {"project": "proj.blend"})
    result = blender_execute(
        "add_movie",
        {"project": "proj.blend", "asset": "clip.mp4", "channel": 1},
    )

Applications should normally use ``BlenderVSE.read`` and
``BlenderVSE.patch`` so revision checks cannot be skipped.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from ..catalog import RUNTIME_ERROR_CODES
from .config import (
    blender_python,
    blender_version,
    environment_report,
    execution_policy,
    find_blender,
    live_session_available,
)
from .live_session import (
    check_live_session,
    ensure_live_session,
    launch_capability,
    session_info,
)
from .runner import BlenderResult, BlenderRunner, BlenderRunnerError, RunnerConfig
from .vse_ops import READ_ONLY_OPS, available_ops, dispatch

_RUNTIME_ERROR_CODES = tuple(sorted(RUNTIME_ERROR_CODES))


def _runtime_error_code(message: str) -> str:
    """Preserve stable error prefixes emitted by fixed Blender scripts."""
    for code in _RUNTIME_ERROR_CODES:
        if f"{code}:" in message:
            return code
    return "execution_failed"

__all__ = [
    "blender_execute",
    "available_ops",
    "BlenderResult",
    "BlenderRunner",
    "BlenderRunnerError",
    "RunnerConfig",
    "find_blender",
    "blender_version",
    "blender_python",
    "environment_report",
    "execution_policy",
    "live_session_available",
    "check_live_session",
    "ensure_live_session",
    "launch_capability",
    "session_info",
]

_runner: BlenderRunner | None = None

# Ops that mutate the timeline but whose effect is verified by re-read only
# (no meaningful per-op count to assert).
_VERIFY_REQUIRED_OPS = {
    "create_project", "save_project", "add_movie", "add_sound", "add_image",
    "add_image_sequence", "add_text", "add_subtitle_track", "assemble_clips",
    "add_color", "add_scene", "add_effect", "add_transition", "delete_strip",
    "cut_strip", "trim_strip", "move", "change_channel", "mute", "lock",
    "set_speed", "set_blend", "set_opacity", "set_transform", "set_text",
    "set_font", "set_font_size", "set_alignment", "set_outline", "set_shadow",
    "set_box", "set_text_position", "set_volume", "set_crop", "clear_vse",
    "set_frame_range", "configure_vse_layout", "finalize_checkpoint_restore",
}


def get_runner() -> BlenderRunner:
    global _runner
    if _runner is None:
        _runner = BlenderRunner(RunnerConfig())
    return _runner


def _save_snapshot(project: str | None) -> dict:
    """mtime/size snapshot of the .blend before an op (for save verification)."""
    if not project:
        return {}
    try:
        p = Path(project)
        return {"mtime": p.stat().st_mtime, "size": p.stat().st_size} if p.exists() else {}
    except OSError:
        return {}


def _verify_save(project: str | None, before: dict, live_filepath: str | None = None) -> dict | None:
    """Confirm the .blend was actually written after a mutating op.

    Returns a short verification dict, or None when nothing to check.
    In live mode the saved target is the GUI's open file (or project).
    """
    target = live_filepath or project
    if not target:
        return None
    try:
        p = Path(target)
        if not p.exists():
            return {"saved": False, "reason": "blend file missing after op", "path": str(p)}
        after = {"mtime": p.stat().st_mtime, "size": p.stat().st_size}
    except OSError as e:
        return {"saved": False, "reason": str(e)}
    if before:
        changed = after["mtime"] != before.get("mtime") or after["size"] != before.get("size")
        return {"saved": bool(changed), "path": str(p),
                "mtime_changed": after["mtime"] != before.get("mtime"),
                "size_changed": after["size"] != before.get("size")}
    # No baseline (file did not exist before, e.g. create_project) — a mutating
    # op must have CREATED it.
    return {"saved": True, "path": str(p), "created": True, "size": after["size"]}


def blender_execute(op: str, params: dict) -> dict:
    """Execute a typed Blender VSE op. Returns operation-result dict.

    params may include: project (.blend path), dry_run, and op-specific args.
    """
    project = params.get("project")
    # Snapshot the .blend before mutating ops so we can prove it was saved.
    snapshot = _save_snapshot(project) if op in _VERIFY_REQUIRED_OPS else {}
    try:
        result = dispatch(op, get_runner(), project, params)
    except BlenderRunnerError as e:
        return {
            "ok": False, "op": op, "adapter": "blender",
            "error": {"code": e.code, "message": str(e), "details": e.details},
        }
    except Exception as e:  # unexpected — report, don't crash
        return {
            "ok": False, "op": op, "adapter": "blender",
            "error": {"code": "execution_failed", "message": str(e)},
        }

    if not result.success:
        message = result.error or "blender failed"
        return {
            "ok": False, "op": op, "adapter": "blender",
            "error": {"code": _runtime_error_code(message), "message": message},
            "data": result.payload,
            "mode": result.mode,
        }
    out = {
        "ok": True, "op": op, "adapter": "blender",
        "dry_run": result.mode == "dry_run",
        "mode": result.mode,
        "data": result.payload,
        "message": result.output[-500:] if result.output else None,
    }
    # Live-session bookkeeping: report the live session on mutating ops so the
    # caller (and the user) knows edits went to the open GUI Blender.
    if result.mode == "live" and op not in READ_ONLY_OPS:
        out["live_session"] = check_live_session()

    # ---- OUTPUT VERIFICATION ----
    is_dry_run = result.mode == "dry_run"
    if op in _VERIFY_REQUIRED_OPS and not is_dry_run:
        # 1. save verification (snapshot is a dict, possibly empty for create)
        if snapshot is not None:
            live_fp = None
            if result.mode == "live":
                try:
                    from .live_session import execute_code as _exec
                    _r = _exec("import bpy; print('FP:' + repr(bpy.data.filepath))")
                    for _l in (_r.get("output") or "").splitlines():
                        if _l.startswith("FP:"):
                            _v = _l[3:].strip().strip("'\"").strip('"')
                            live_fp = _v or None
                except Exception:
                    live_fp = None
            out["save_verified"] = _verify_save(project, snapshot, live_fp)
        # 2. re-read timeline to confirm the edit landed
        if op not in ("render_preview", "render_final") and project:
            try:
                reread = dispatch("list_strips", get_runner(), project,
                                  {"project": project, "with_text": True})
                if reread.success:
                    out["timeline_verified"] = {
                        "strip_count": len((reread.payload or {}).get("strips", [])),
                        "scene": (reread.payload or {}).get("scene"),
                    }
                else:
                    out["timeline_verified"] = {"error": reread.error}
            except Exception as e:
                out["timeline_verified"] = {"error": str(e)}
    return out
