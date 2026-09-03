"""Fixed Blender GUI bootstrap for Blender VSE Control live sessions.

Loaded only by ``live_session.ensure_live_session``. It imports the vendored
Bridge addon from this directory, registers it when necessary, and starts its
socket server. No Agent-authored code or project edit is accepted here.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import bpy


ADDON_PATH = Path(__file__).resolve().with_name("blender_bridge_addon.py")
MODULE_NAME = "blender_vse_bridge_runtime"


def _load_addon():
    module = sys.modules.get(MODULE_NAME)
    if module is not None:
        return module
    spec = importlib.util.spec_from_file_location(MODULE_NAME, ADDON_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load Blender Bridge addon: {ADDON_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


def _patch_legacy_panel_for_blender_51(host: str, port: int) -> None:
    """Repair the enabled pre-5.1 add-on panel for this Blender session.

    Older installed copies use ``icon='PLUG'``.  Blender 5.1 rejects that enum
    during every panel redraw, even though the socket server itself works.  We
    do not rewrite user files or preferences; this is a runtime-only display
    compatibility patch for the already registered panel class.
    """
    panel = getattr(bpy.types, "MCP_PT_bridge_panel", None)
    if panel is None or bpy.app.version < (5, 1, 0):
        return

    def _safe_draw(self, _context):
        layout = self.layout
        layout.label(text="Blender VSE Control Bridge", icon="PLUGIN")
        layout.label(text=f"Listening on {host}:{port}")

    try:
        panel.draw = _safe_draw
    except Exception as exc:
        print(f"BLENDER_VSE_BRIDGE_PANEL_PATCH_FAILED:{exc}")


started = False
try:
    # Prefer a normally installed/enabled Bridge addon, including older
    # compatible versions that do not expose our module-level helper API.
    result = bpy.ops.mcp.start_bridge()
    started = "FINISHED" in result or "CANCELLED" in result
except Exception:
    started = False

if not started:
    # No installed operator: load the vendored runtime under a unique module
    # name so an old ``blender_bridge_addon`` in sys.modules cannot shadow it.
    addon = _load_addon()
    if not addon.is_registered():
        addon.register()
    addon.start_bridge()
    host, port = addon.BRIDGE_HOST, addon.BRIDGE_PORT
else:
    host = "127.0.0.1"
    port = int(os.environ.get("BLENDER_BRIDGE_PORT", "10850"))

_patch_legacy_panel_for_blender_51(host, port)

print(f"BLENDER_VSE_BRIDGE_READY:{host}:{port}")
