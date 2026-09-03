"""
blender_bridge_addon.py — Blender MCP Socket Bridge (v2)

Vendored and locally hardened by Blender VSE Control. Upstream provenance and
the MIT license are recorded in THIRD_PARTY_NOTICES.md.

Canonical location: addon/blender_bridge_addon.py
Download: https://github.com/sandraschi/blender-mcp/releases/latest/download/blender_bridge_addon.py

Installs as a Blender addon. Creates a TCP socket server inside Blender so the
blender-mcp server can send bpy scripts directly (no HTTP polling).

Install: Edit > Preferences > Add-ons > Install > pick this file > enable it.

Environment variables (all optional):
  BLENDER_BRIDGE_PORT    — TCP port (default 10850)
  BLENDER_BRIDGE_HOST    — bind address (default 127.0.0.1)
"""

bl_info = {
    "name": "Blender VSE Control Bridge",
    "author": "sandraschi",
    "version": (0, 5, 0),
    "blender": (4, 2, 0),
    "location": "Properties > Scene > Blender VSE Control",
    "description": "Local TCP bridge used by Blender VSE Control",
    "category": "System",
}

import json
import logging
import os
import socket
import struct
import threading
import traceback

import bpy

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config from env vars
# ---------------------------------------------------------------------------

BRIDGE_HOST = os.environ.get("BLENDER_BRIDGE_HOST", "127.0.0.1")
_normalized_bridge_host = BRIDGE_HOST.strip().lower().strip("[]")
if not (
    _normalized_bridge_host == "localhost"
    or _normalized_bridge_host == "::1"
    or _normalized_bridge_host.startswith("127.")
):
    raise RuntimeError(
        "Blender MCP Bridge has no authentication and may only bind to a "
        "loopback host (127.0.0.1, ::1, or localhost)"
    )
BRIDGE_PORT = int(os.environ.get("BLENDER_BRIDGE_PORT", "10850"))

_stop_event = threading.Event()
_server_thread: threading.Thread | None = None
_server_socket: socket.socket | None = None

# Main-thread task queue (thread-safe via threading.Event)
_pending_task: dict | None = None
_pending_event = threading.Event()
_result_event = threading.Event()
_result_data: dict | None = None


# ---------------------------------------------------------------------------
# Add-on preferences
# ---------------------------------------------------------------------------

class MCP_AddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __name__

    bridge_port: bpy.props.IntProperty(
        name="Bridge Port",
        description="TCP port for the socket bridge",
        default=BRIDGE_PORT,
        min=1024,
        max=65535,
    )
    auto_start_bridge: bpy.props.BoolProperty(
        name="Start Bridge with Blender",
        description="Automatically start the local Blender VSE bridge when Blender opens",
        default=True,
    )

    def draw(self, context):
        layout = self.layout
        box = layout.box()
        box.prop(self, "bridge_port")
        box.prop(self, "auto_start_bridge")


# ---------------------------------------------------------------------------
# Socket server — runs in background thread
# ---------------------------------------------------------------------------

def _get_prefs():
    try:
        addon = bpy.context.preferences.addons.get(__name__)
        if addon and hasattr(addon, "preferences"):
            return addon.preferences
    except Exception:
        pass
    return None


def _handle_client(client: socket.socket):
    """Handle one connected MCP server in a thread."""
    global _pending_task, _pending_event, _result_data, _result_event
    buf = b""
    header_len = struct.calcsize("!I")

    try:
        while not _stop_event.is_set():
            # Read 4-byte length prefix
            while len(buf) < header_len:
                chunk = client.recv(4096)
                if not chunk:
                    return
                buf += chunk
            body_len = struct.unpack("!I", buf[:header_len])[0]
            buf = buf[header_len:]

            # Read body
            while len(buf) < body_len:
                chunk = client.recv(4096)
                if not chunk:
                    return
                buf += chunk
            body = buf[:body_len]
            buf = buf[body_len:]

            try:
                msg = json.loads(body.decode("utf-8"))
            except json.JSONDecodeError as e:
                _send_response(client, {"status": "error", "message": f"Invalid JSON: {e}"})
                continue

            cmd = msg.get("type", "")
            params = msg.get("params", {})

            if cmd == "ping":
                _send_response(client, {"status": "success", "result": {"pong": True}})
                continue

            if cmd == "execute_code":
                code = params.get("code", "")
                if not code.strip():
                    _send_response(client, {"status": "error", "message": "Empty code"})
                    continue

                # Hand off to main thread via timer
                _pending_task = {"code": code}
                _pending_event.set()
                _result_event.clear()
                _result_data = None

                # Wait for result (with timeout)
                if _result_event.wait(timeout=180):
                    result = _result_data or {}
                    _send_response(client, {
                        "status": "success" if result.get("success") else "error",
                        "result": result,
                    })
                else:
                    _send_response(client, {
                        "status": "error",
                        "message": "Execution timed out (180s)",
                    })
                continue

            _send_response(client, {"status": "error", "message": f"Unknown command: {cmd}"})
    except (ConnectionError, BrokenPipeError, OSError):
        pass
    finally:
        try:
            client.close()
        except Exception:
            pass


def _send_response(client: socket.socket, data: dict):
    payload = json.dumps(data).encode("utf-8")
    client.sendall(struct.pack("!I", len(payload)) + payload)


def _server_loop():
    global _server_socket
    _server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    _server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    _server_socket.settimeout(1.0)
    try:
        _server_socket.bind((BRIDGE_HOST, BRIDGE_PORT))
        _server_socket.listen(5)
        _log.info("MCP Bridge socket server listening on %s:%d", BRIDGE_HOST, BRIDGE_PORT)
    except OSError as e:
        _log.error("MCP Bridge could not bind: %s", e)
        _server_socket = None
        return

    while not _stop_event.is_set():
        try:
            client, addr = _server_socket.accept()
            _log.info("MCP server connected from %s", addr)
            t = threading.Thread(target=_handle_client, args=(client,), daemon=True)
            t.start()
        except socket.timeout:
            continue
        except OSError:
            break

    _log.info("MCP Bridge socket server stopped")


# ---------------------------------------------------------------------------
# Main-thread timer — safe to call bpy here
# ---------------------------------------------------------------------------

def _process_pending():
    global _pending_task, _pending_event, _result_data, _result_event
    if _pending_task is None:
        return 0.1

    task = _pending_task
    _pending_task = None
    _pending_event.clear()

    try:
        code = task.get("code", "")
        error_msg = None
        import io
        import sys

        output = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = output
        try:
            exec(compile(code, "<blender_vse_bridge>", "exec"), {"bpy": bpy})
        except Exception:
            error_msg = traceback.format_exc()
        finally:
            sys.stdout = old_stdout
        result = {
            "success": error_msg is None,
            "output": output.getvalue(),
            "error": error_msg,
        }

    except Exception:
        result = {"success": False, "error": traceback.format_exc()}

    _result_data = result
    _result_event.set()
    return 0.1


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------


class MCP_OT_start_bridge(bpy.types.Operator):
    bl_idname = "mcp.start_bridge"
    bl_label = "Start MCP Bridge"

    def execute(self, context):
        if bridge_running():
            self.report({"WARNING"}, "Bridge already running")
            return {"CANCELLED"}
        start_bridge()
        self.report({"INFO"}, f"MCP Bridge started on port {BRIDGE_PORT}")
        return {"FINISHED"}


class MCP_OT_stop_bridge(bpy.types.Operator):
    bl_idname = "mcp.stop_bridge"
    bl_label = "Stop MCP Bridge"

    def execute(self, context):
        global _server_socket
        _stop_event.set()
        if _server_socket:
            try:
                _server_socket.close()
            except Exception:
                pass
            _server_socket = None
        if bpy.app.timers.is_registered(_process_pending):
            bpy.app.timers.unregister(_process_pending)
        self.report({"INFO"}, "MCP Bridge stopped")
        return {"FINISHED"}


class MCP_PT_bridge_panel(bpy.types.Panel):
    bl_label = "Blender VSE Control Bridge"
    bl_idname = "MCP_PT_bridge_panel"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"

    def draw(self, context):
        layout = self.layout

        row = layout.row()
        if _server_thread and _server_thread.is_alive():
            row.operator("mcp.stop_bridge", text="Stop Bridge", icon="X")
            layout.label(text=f"Status: Connected on port {BRIDGE_PORT}", icon="CHECKMARK")
        else:
            row.operator("mcp.start_bridge", text="Start Bridge", icon="PLAY")
            layout.label(text="Status: Not running", icon="ERROR")

        layout.separator()
        # Blender 5.1 removed the old PLUG icon enum.  PLUGIN is available in
        # both supported Blender generations and avoids a draw exception that
        # otherwise floods the console every time this panel is repainted.
        layout.label(text="Port: " + str(BRIDGE_PORT), icon="PLUGIN")


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

_classes = [
    MCP_AddonPreferences,
    MCP_OT_start_bridge,
    MCP_OT_stop_bridge,
    MCP_PT_bridge_panel,
]


def is_registered() -> bool:
    """True when this addon's Blender classes are already registered."""
    return hasattr(bpy.types, "MCP_OT_start_bridge")


def bridge_running() -> bool:
    return bool(_server_thread and _server_thread.is_alive())


def start_bridge() -> bool:
    """Start the socket bridge without relying on UI/operator context."""
    global _server_thread, _stop_event, BRIDGE_PORT
    if bridge_running():
        return False
    prefs = _get_prefs()
    if prefs:
        BRIDGE_PORT = prefs.bridge_port
    _stop_event.clear()
    if not bpy.app.timers.is_registered(_process_pending):
        bpy.app.timers.register(_process_pending, first_interval=0.1)
    _server_thread = threading.Thread(target=_server_loop, daemon=True)
    _server_thread.start()
    return True


def _auto_start_bridge():
    """Timer callback used after normal addon registration on GUI startup."""
    if bpy.app.background:
        return None
    prefs = _get_prefs()
    if prefs is not None and not prefs.auto_start_bridge:
        return None
    start_bridge()
    return None


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    if not bpy.app.background and not bpy.app.timers.is_registered(_auto_start_bridge):
        bpy.app.timers.register(_auto_start_bridge, first_interval=0.5)


def unregister():
    global _server_socket
    _stop_event.set()
    if _server_socket:
        try:
            _server_socket.close()
        except Exception:
            pass
        _server_socket = None
    if bpy.app.timers.is_registered(_process_pending):
        bpy.app.timers.unregister(_process_pending)
    if bpy.app.timers.is_registered(_auto_start_bridge):
        bpy.app.timers.unregister(_auto_start_bridge)
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
