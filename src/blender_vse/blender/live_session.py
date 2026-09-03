"""Live Blender GUI session client using the bundled Blender MCP Bridge.

Connection model (upstream architecture, NOT headless subprocess):

    application / blender-vse
        -> live_session (this module)
        -> Blender MCP Bridge addon (TCP socket, default 127.0.0.1:10850)
        -> the CURRENTLY RUNNING Blender GUI instance

The bridge addon (addon/blender_bridge_addon.py from sandraschi/blender-mcp)
runs inside the user's GUI Blender. It exposes a tiny TCP socket server with a
4-byte big-endian length prefix + JSON body wire format:

    -> {"type": "ping"}                          {"status": "success", ...}
    -> {"type": "execute_code", "params": {"code": "..."}}
       {"status": "success", "result": {"success": bool, "output": str, "error": str}}
Code executes on Blender's MAIN thread (via bpy.app.timers), so bpy calls are
safe and edits appear live in the user's open VSE timeline / preview.

This module is the ONLY place that speaks the bridge protocol. vse_ops stays
adapter-agnostic (it still returns bpy script text); the runner decides
live_session vs headless execution.

Security: same contract as the headless runner — only execute scripts produced
by vse_ops.py templates. The bridge executes allowlisted fixed scripts only.
"""
from __future__ import annotations

import json
import os
import socket
import struct
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from .config import runtime_tmp_dir
from .presentation_contract import (
    VSE_LAYOUT_PROFILE_KEY,
    VSE_LAYOUT_PROFILE_VERSION,
    binding_helpers_script,
)

def _setting(primary: str, legacy: str, default: str) -> str:
    return os.environ.get(primary) or os.environ.get(legacy) or default


def _loopback_host(host: str) -> bool:
    normalized = host.strip().lower().strip("[]")
    return normalized == "localhost" or normalized == "::1" or normalized.startswith("127.")


BRIDGE_HOST = os.environ.get(
    "BLENDER_BRIDGE_HOST", os.environ.get("BLENDER_HOST", "127.0.0.1")
)
if not _loopback_host(BRIDGE_HOST):
    raise RuntimeError(
        "BLENDER_BRIDGE_HOST must be loopback because the bridge has no "
        "authentication; use 127.0.0.1, ::1, or localhost"
    )
BRIDGE_PORT = int(os.environ.get("BLENDER_BRIDGE_PORT", "10850"))
BRIDGE_TIMEOUT = int(os.environ.get("BLENDER_BRIDGE_TIMEOUT", "30"))
SESSION_START_TIMEOUT = float(
    _setting("BLENDER_VSE_START_TIMEOUT", "VP_BLENDER_START_TIMEOUT", "45")
)
SESSION_VISIBILITY_GRACE = float(
    _setting("BLENDER_VSE_VISIBILITY_GRACE", "VP_BLENDER_VISIBILITY_GRACE", "5")
)
SESSION_STABILITY_SAMPLES = int(
    _setting("BLENDER_VSE_STABILITY_SAMPLES", "VP_BLENDER_STABILITY_SAMPLES", "3")
)
SESSION_STABILITY_INTERVAL = float(
    _setting("BLENDER_VSE_STABILITY_INTERVAL", "VP_BLENDER_STABILITY_INTERVAL", "0.35")
)
SESSION_AUTOSTART = _setting(
    "BLENDER_VSE_AUTOSTART", "VP_BLENDER_AUTOSTART", "1"
).strip().lower() \
    not in {"0", "false", "no", "off"}

_BRIDGE_DIR = Path(__file__).resolve().parent / "bridge"
_GUI_BOOTSTRAP = _BRIDGE_DIR / "auto_startup.py"
_launch_lock = threading.Lock()
_launch_process: subprocess.Popen | None = None

# A bridge socket can become reachable before Blender has created a desktop
# window.  These states are therefore observations, not readiness.  The
# session gate keeps polling them until the complete GUI/VSE proof is present.
_TRANSIENT_DISCOVERY_CODES = {
    "bridge_unreachable",
    "session_identity_pending",
    "gui_not_visible",
    "gui_not_stable",
    "vse_not_visible",
    "vse_content_not_framed",
}


class LiveSessionError(Exception):
    def __init__(self, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.code = code
        self.details = details


def bridge_config() -> dict:
    """Current bridge endpoint configuration (for reporting)."""
    return {"host": BRIDGE_HOST, "port": BRIDGE_PORT}


def _send_cmd(cmd: dict, timeout: int = BRIDGE_TIMEOUT) -> dict[str, Any]:
    """Send one command to the bridge addon and return the decoded response.

    Wire format: 4-byte big-endian length prefix + UTF-8 JSON body.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((BRIDGE_HOST, BRIDGE_PORT))
        payload = json.dumps(cmd).encode("utf-8")
        sock.sendall(struct.pack("!I", len(payload)) + payload)

        header = b""
        while len(header) < 4:
            chunk = sock.recv(4 - len(header))
            if not chunk:
                raise ConnectionError("Bridge closed connection mid-header")
            header += chunk
        body_len = struct.unpack("!I", header)[0]

        body = b""
        while len(body) < body_len:
            chunk = sock.recv(body_len - len(body))
            if not chunk:
                raise ConnectionError("Bridge closed connection mid-body")
            body += chunk
        return json.loads(body.decode("utf-8"))
    except (ConnectionRefusedError, OSError, socket.timeout) as e:
        raise LiveSessionError("bridge_unreachable", str(e)) from e
    finally:
        try:
            sock.close()
        except Exception:
            pass


def ping() -> bool:
    """True if a live Blender GUI bridge is reachable right now."""
    try:
        resp = _send_cmd({"type": "ping"}, timeout=2)
        return bool(resp.get("status") == "success" and resp.get("result", {}).get("pong"))
    except LiveSessionError:
        return False


def session_info() -> dict[str, Any]:
    """Return identity and project state for the connected GUI session."""
    if not ping():
        return {
            "connected": False,
            "host": BRIDGE_HOST,
            "port": BRIDGE_PORT,
        }
    code = (
        binding_helpers_script()
        + f"_vp_layout_profile_key = {json.dumps(VSE_LAYOUT_PROFILE_KEY)}\n"
        + f"_vp_layout_profile_expected = {VSE_LAYOUT_PROFILE_VERSION}\n"
        + r'''
import bpy, json, os
_wm = getattr(bpy.context, "window_manager", None)
_windows = list(_wm.windows) if _wm else []
_window = getattr(bpy.context, "window", None) or (_windows[0] if _windows else None)
_screen = getattr(_window, "screen", None) if _window else None
_areas = list(_screen.areas) if _screen else []
_native = {
    "native_window_checked": False,
    "native_window_visible": False,
    "native_window_handles": [],
    "native_window_titles": [],
    "window_station": None,
    "thread_desktop": None,
    "input_desktop": None,
    "interactive_desktop": os.name != "nt",
    "process_session_id": None,
    "active_console_session_id": None,
    "interactive_session": os.name != "nt",
}
if os.name == "nt":
    try:
        import ctypes
        from ctypes import wintypes
        _user32 = ctypes.windll.user32
        _kernel32 = ctypes.windll.kernel32
        _user32.GetProcessWindowStation.restype = wintypes.HANDLE
        _user32.GetThreadDesktop.argtypes = [wintypes.DWORD]
        _user32.GetThreadDesktop.restype = wintypes.HANDLE
        _user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        _user32.OpenInputDesktop.restype = wintypes.HANDLE
        _user32.GetUserObjectInformationW.argtypes = [
            wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID,
            wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
        ]
        _user32.GetUserObjectInformationW.restype = wintypes.BOOL
        _pid = os.getpid()
        _handles = []
        _titles = []
        _enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def _visit(_hwnd, _lparam):
            _owner = wintypes.DWORD()
            _user32.GetWindowThreadProcessId(_hwnd, ctypes.byref(_owner))
            if _owner.value == _pid and _user32.IsWindowVisible(_hwnd):
                _handles.append(int(_hwnd))
                _length = int(_user32.GetWindowTextLengthW(_hwnd))
                _buffer = ctypes.create_unicode_buffer(_length + 1)
                if _length:
                    _user32.GetWindowTextW(_hwnd, _buffer, _length + 1)
                _titles.append(_buffer.value)
            return True
        _callback = _enum_proc(_visit)
        _user32.EnumWindows(_callback, 0)

        _UOI_NAME = 2
        def _object_name(_handle):
            if not _handle:
                return None
            _needed = wintypes.DWORD()
            _user32.GetUserObjectInformationW(_handle, _UOI_NAME, None, 0, ctypes.byref(_needed))
            if not _needed.value:
                return None
            _buffer = ctypes.create_unicode_buffer(max(1, _needed.value // 2))
            if not _user32.GetUserObjectInformationW(
                    _handle, _UOI_NAME, _buffer, _needed.value, ctypes.byref(_needed)):
                return None
            return _buffer.value

        _station = _user32.GetProcessWindowStation()
        _thread_desktop_handle = _user32.GetThreadDesktop(_kernel32.GetCurrentThreadId())
        _input_desktop_handle = _user32.OpenInputDesktop(0, False, 0x0001)
        _thread_desktop = _object_name(_thread_desktop_handle)
        _input_desktop = _object_name(_input_desktop_handle)
        if _input_desktop_handle:
            _user32.CloseDesktop(_input_desktop_handle)

        _session_id = wintypes.DWORD()
        _kernel32.ProcessIdToSessionId(_pid, ctypes.byref(_session_id))
        _active_session_id = int(_kernel32.WTSGetActiveConsoleSessionId())
        _native.update({
            "native_window_checked": True,
            "native_window_visible": bool(_handles),
            "native_window_handles": _handles,
            "native_window_titles": _titles,
            "window_station": _object_name(_station),
            "thread_desktop": _thread_desktop,
            "input_desktop": _input_desktop,
            "interactive_desktop": bool(_thread_desktop and _thread_desktop == _input_desktop),
            "process_session_id": int(_session_id.value),
            "active_console_session_id": _active_session_id,
            "interactive_session": int(_session_id.value) == _active_session_id,
        })
    except Exception as _native_exc:
        _native["native_window_error"] = str(_native_exc)
_edit_scene = _vp_resolve_edit_scene("VideoEditing", getattr(_window, "scene", None))
_binding = _vp_vse_binding_proof(_window, _edit_scene)
_window_candidates = []
for _candidate in _windows:
    _candidate_screen = getattr(_candidate, "screen", None)
    _candidate_areas = list(_candidate_screen.areas) if _candidate_screen else []
    _window_candidates.append({
        "workspace": _candidate.workspace.name if _candidate.workspace else None,
        "screen": _candidate_screen.name if _candidate_screen else None,
        "scene": _candidate.scene.name if _candidate.scene else None,
        "vse_area_count": sum(1 for _a in _candidate_areas if _a.type == "SEQUENCE_EDITOR"),
    })
print("VP_SESSION:" + json.dumps({
    "pid": os.getpid(),
    "blender_version": bpy.app.version_string,
    "background": bool(bpy.app.background),
    "filepath": bpy.data.filepath,
    "is_dirty": bool(bpy.data.is_dirty),
    "scene": bpy.context.scene.name if bpy.context.scene else None,
    "window_count": len(_windows),
    "workspace": _window.workspace.name if _window and _window.workspace else None,
    "screen": _screen.name if _screen else None,
    "area_types": [a.type for a in _areas],
    "vse_area_count": sum(1 for a in _areas if a.type == "SEQUENCE_EDITOR"),
    "window_candidates": _window_candidates,
    "layout_profile_version": int(
        _window.workspace.get(_vp_layout_profile_key, 0) or 0
    ) if _window and _window.workspace else 0,
    "layout_profile_current": bool(
        _window and _window.workspace
        and int(_window.workspace.get(_vp_layout_profile_key, 0) or 0)
            == _vp_layout_profile_expected
    ),
    **_binding,
    **_native,
}, ensure_ascii=False))
''')
    try:
        result = execute_code(code, timeout=10)
    except LiveSessionError as exc:
        return {
            "connected": False,
            "host": BRIDGE_HOST,
            "port": BRIDGE_PORT,
            "error": str(exc),
        }
    for line in (result.get("output") or "").splitlines():
        if line.startswith("VP_SESSION:"):
            try:
                payload = json.loads(line[len("VP_SESSION:"):])
            except json.JSONDecodeError:
                break
            return {
                "connected": True,
                "host": BRIDGE_HOST,
                "port": BRIDGE_PORT,
                **payload,
            }
    return {
        "connected": True,
        "host": BRIDGE_HOST,
        "port": BRIDGE_PORT,
        "error": "bridge responded but did not return session identity",
    }


def launch_capability() -> dict[str, Any]:
    """Report whether this machine can auto-launch a live Blender session.

    This function is intentionally side-effect free and is safe to call from
    tool discovery/get_status().
    """
    from .config import find_blender

    blender = find_blender()
    return {
        "autostart_enabled": SESSION_AUTOSTART,
        "blender_executable": blender,
        "bootstrap": str(_GUI_BOOTSTRAP),
        "bootstrap_exists": _GUI_BOOTSTRAP.is_file(),
        "launchable": bool(SESSION_AUTOSTART and blender and _GUI_BOOTSTRAP.is_file()),
        "connected": ping(),
    }


def _norm_path(value: str | Path | None) -> str:
    if not value:
        return ""
    return os.path.normcase(os.path.abspath(os.fspath(value)))


def _visible_window_evidence(pid: int | None) -> dict[str, Any]:
    """Return OS-level evidence that ``pid`` owns a visible desktop window.

    Blender's bridge runs before the native window is necessarily discoverable.
    On Windows, ``EnumWindows`` is the authoritative replacement for the racy
    ``Process.MainWindowHandle`` snapshot.  Other platforms use Blender's
    internal non-background/window-count evidence from :func:`session_info`.
    """
    if not pid:
        return {
            "platform": os.name,
            "checked": os.name == "nt",
            "visible": False,
            "window_handles": [],
            "all_window_handles": [],
            "window_titles": [],
        }
    if os.name != "nt":
        return {
            "platform": os.name,
            "checked": False,
            "visible": True,
            "window_handles": [],
            "all_window_handles": [],
            "window_titles": [],
        }

    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        handles: list[int] = []
        all_handles: list[int] = []
        titles: list[str] = []
        enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def _visit(hwnd, _lparam):
            owner = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value != int(pid):
                return True
            all_handles.append(int(hwnd))
            if not user32.IsWindowVisible(hwnd):
                return True
            handles.append(int(hwnd))
            length = int(user32.GetWindowTextLengthW(hwnd))
            if length:
                buffer = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buffer, length + 1)
                titles.append(buffer.value)
            else:
                titles.append("")
            return True

        callback = enum_proc(_visit)
        user32.EnumWindows(callback, 0)
        return {
            "platform": os.name,
            "checked": True,
            "visible": bool(handles),
            "window_handles": handles,
            "all_window_handles": all_handles,
            "window_titles": titles,
        }
    except Exception as exc:
        return {
            "platform": os.name,
            "checked": True,
            "visible": False,
            "window_handles": [],
            "all_window_handles": [],
            "window_titles": [],
            "error": str(exc),
        }


def _request_visible_window(pid: int | None) -> None:
    """Best-effort restore for a managed GUI window that exists but is hidden."""
    if os.name != "nt" or not pid:
        return
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def _visit(hwnd, _lparam):
            owner = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value == int(pid):
                # SW_RESTORE makes a minimized/hidden top-level Blender window
                # visible without depending on the Agent to find or focus it.
                user32.ShowWindowAsync(hwnd, 9)
            return True

        callback = enum_proc(_visit)
        user32.EnumWindows(callback, 0)
    except Exception:
        pass


def _with_visibility_proof(
    info: dict[str, Any],
    *,
    restore: bool = False,
) -> dict[str, Any]:
    """Attach fail-closed GUI evidence to a connected session observation."""
    external_evidence = _visible_window_evidence(info.get("pid"))
    native_checked = bool(info.get("native_window_checked"))
    if native_checked:
        evidence = {
            "platform": os.name,
            "checked": True,
            "source": "inside_blender",
            "visible": bool(info.get("native_window_visible")),
            "window_handles": info.get("native_window_handles", []),
            "window_titles": info.get("native_window_titles", []),
            "window_station": info.get("window_station"),
            "thread_desktop": info.get("thread_desktop"),
            "input_desktop": info.get("input_desktop"),
            "interactive_desktop": bool(info.get("interactive_desktop")),
            "process_session_id": info.get("process_session_id"),
            "active_console_session_id": info.get("active_console_session_id"),
            "interactive_session": bool(info.get("interactive_session")),
            "external_observer": external_evidence,
        }
    else:
        evidence = {**external_evidence, "source": "external_fallback"}
    internal_visible = (
        not bool(info.get("background"))
        and int(info.get("window_count") or 0) > 0
    )
    if restore and not native_checked and internal_visible and not evidence.get("visible"):
        _request_visible_window(info.get("pid"))
        evidence = _visible_window_evidence(info.get("pid"))
    os_visible = bool(evidence.get("visible"))
    interactive = True
    if native_checked and os.name == "nt":
        interactive = bool(
            evidence.get("interactive_desktop")
            and evidence.get("interactive_session")
            and str(evidence.get("window_station") or "").lower() == "winsta0"
        )
    visible = bool(internal_visible and os_visible and interactive)
    enriched = {
        **info,
        "gui_visible": visible,
        "window_evidence": evidence,
    }
    if visible:
        return enriched
    return {
        **enriched,
        "ready": False,
        "transient": True,
        "code": "gui_not_visible",
        "message": (
            "The Blender Bridge answered, but no visible Blender desktop "
            "window has been discovered yet. Waiting for GUI discovery is "
            "mandatory; Blender operations remain locked."
        ),
    }


def _stable_visible_session() -> dict[str, Any]:
    """Require consecutive passive GUI/VSE observations before unlocking."""
    samples: list[dict[str, Any]] = []
    stable_handles: set[int] | None = None
    count = max(2, SESSION_STABILITY_SAMPLES)
    for index in range(count):
        current = _with_visibility_proof(session_info(), restore=False)
        current_handles = set(
            int(h) for h in current.get("window_evidence", {}).get("window_handles", [])
        )
        stable_handles = (
            current_handles if stable_handles is None else stable_handles & current_handles
        )
        samples.append({
            "gui_visible": bool(current.get("gui_visible")),
            "window_handles": current.get("window_evidence", {}).get("window_handles", []),
            "workspace": current.get("workspace"),
            "vse_area_count": current.get("vse_area_count", 0),
        })
        if (
            not current.get("gui_visible")
            or int(current.get("vse_area_count") or 0) < 1
            or not stable_handles
        ):
            return {
                **current,
                "ready": False,
                "transient": True,
                "code": "gui_not_stable",
                "message": (
                    "Blender visibility was only transient. The native window "
                    "and VSE area must remain visible across consecutive checks."
                ),
                "stability_samples": samples,
            }
        if index + 1 < count:
            time.sleep(max(0.05, SESSION_STABILITY_INTERVAL))
    return {
        **current,
        "stability_samples": samples,
        "stable_window_handles": sorted(stable_handles or set()),
        "stable_visible": True,
    }


def _activate_vse_workspace(info: dict[str, Any]) -> dict[str, Any]:
    """Open the edit scene and prove that its content is actually presented.

    Merely finding a ``SEQUENCE_EDITOR`` area is not enough: Blender persists
    each area's pan/zoom independently, so a healthy project can open with all
    strips outside the visible region and a black preview.  Readiness therefore
    also binds the named edit scene, places the playhead on visual content, and
    frames both the timeline and preview through fixed UI operators.
    """
    code = (
        binding_helpers_script()
        + f"_vp_layout_profile_key = {json.dumps(VSE_LAYOUT_PROFILE_KEY)}\n"
        + f"_vp_layout_profile_expected = {VSE_LAYOUT_PROFILE_VERSION}\n"
        + r'''
import bpy, json, os
# Runtime-only compatibility repair for an already-enabled legacy Bridge
# panel. This also covers sessions that were open before the controller attached,
# where auto_startup.py was never executed.
_panel = getattr(bpy.types, "MCP_PT_bridge_panel", None)
if _panel is not None and bpy.app.version >= (5, 1, 0):
    def _vp_safe_bridge_draw(self, _context):
        _layout = self.layout
        _layout.label(text="Blender VSE Control Bridge", icon="PLUGIN")
        _layout.label(text="Listening on 127.0.0.1:" + os.environ.get("BLENDER_BRIDGE_PORT", "10850"))
    try:
        _panel.draw = _vp_safe_bridge_draw
    except Exception:
        pass
_wm = getattr(bpy.context, "window_manager", None)
_windows = list(_wm.windows) if _wm else []
_window = getattr(bpy.context, "window", None) or (_windows[0] if _windows else None)
if len(_windows) > 1:
    print("VP_VSE:" + json.dumps({
        "ready": False,
        "code": "window_ambiguous",
        "reason": "multiple Blender windows require explicit window correlation",
        "window_count": len(_windows),
    }))
elif _window is None:
    print("VP_VSE:" + json.dumps({"ready": False, "reason": "no_window"}))
else:
    _target = bpy.data.workspaces.get("Video Editing")
    _workspace_created = False
    if _target is None:
        try:
            bpy.ops.workspace.duplicate()
            _target = _window.workspace
            _target.name = "Video Editing"
            _workspace_created = True
        except Exception:
            _target = None
    if _target is not None and _window.workspace != _target:
        _window.workspace = _target
    # The .blend may persist another scene on the window even though the named
    # edit scene owns the strips. Prefer the contract scene, then the populated
    # current scene, then the most populated scene in the project.
    _scene = _vp_resolve_edit_scene("VideoEditing", _window.scene)
    # Blender 5.1 decouples the VSE from ``window.scene``. Each workspace has
    # its own ``sequencer_scene``; when that pointer is empty the editors show
    # the prominent "New" control and an empty timeline even though the scene
    # itself owns strips. Bind both explicitly so the visible VSE presents the
    # same named edit scene that the adapter reads and mutates.
    _vp_bind_vse_window(_window, _scene)
    _binding = _vp_vse_binding_proof(_window, _scene)

    _screen = _window.screen
    _areas = list(_screen.areas) if _screen else []
    # Session readiness performs the smallest safe repair only: bind the edit
    # scene, frame content, and fit the preview.  It never rewrites a healthy
    # user's pane arrangement.  The versioned four-pane profile is applied by
    # create_project/configure_vse_layout and persisted explicitly.
    if _workspace_created and not any(a.type == "SEQUENCE_EDITOR" for a in _areas):
        _primary = max(
            _areas,
            key=lambda _a: int(getattr(_a, "width", 0)) * int(getattr(_a, "height", 0)),
            default=None,
        )
        if _primary is not None:
            _primary.type = "SEQUENCE_EDITOR"
            _primary.spaces.active.view_type = "SEQUENCER_PREVIEW"
            _areas = list(_screen.areas)
    _seq = getattr(_scene, "sequence_editor", None)
    _strips = list(_seq.strips) if _seq is not None else []
    _visual_types = {"MOVIE", "IMAGE", "TEXT", "COLOR", "SCENE", "META", "ADJUSTMENT"}
    _visuals = [s for s in _strips if not getattr(s, "mute", False) and s.type in _visual_types]
    _frame = int(_scene.frame_current)
    _active_visuals = [
        s for s in _visuals
        if int(s.frame_final_start) <= _frame < int(s.frame_final_end)
    ]
    if _visuals and not _active_visuals:
        _frame = min(int(s.frame_final_start) for s in _visuals)
        _scene.frame_set(_frame)
        _active_visuals = [
            s for s in _visuals
            if int(s.frame_final_start) <= _frame < int(s.frame_final_end)
        ]
    else:
        # Re-evaluate the current frame so the preview cache follows the newly
        # selected workspace/scene even when the frame number did not change.
        _scene.frame_set(_frame)

    def _vp_media_path(_strip):
        _raw = ""
        if _strip.type == "MOVIE":
            _raw = getattr(_strip, "filepath", "") or ""
        elif _strip.type == "SOUND":
            _sound = getattr(_strip, "sound", None)
            _raw = getattr(_sound, "filepath", "") if _sound is not None else ""
        elif _strip.type == "IMAGE":
            _raw = getattr(_strip, "filepath", "") or ""
            if not _raw:
                _directory = getattr(_strip, "directory", "") or ""
                _elements = getattr(_strip, "elements", None)
                _filename = _elements[0].filename if _elements and len(_elements) else ""
                if _filename:
                    _raw = os.path.join(_directory, _filename)
        return os.path.normpath(bpy.path.abspath(_raw)) if _raw else ""

    _missing_current_media = []
    for _strip in _active_visuals:
        if _strip.type not in {"MOVIE", "IMAGE"}:
            continue
        _path = _vp_media_path(_strip)
        if not _path or not os.path.isfile(_path):
            _missing_current_media.append({"strip": _strip.name, "path": _path})

    _timeline_views = 0
    _preview_views = 0
    _timeline_framed = 0
    _preview_fitted = 0
    _ui_errors = []
    _timeline_min = min((int(s.frame_final_start) for s in _strips), default=1)
    _timeline_max = max((int(s.frame_final_end) for s in _strips), default=max(2, int(_scene.frame_end)))
    _channel_max = max((int(getattr(s, "channel", 1)) for s in _strips), default=1)
    for _area in _areas:
        if _area.type == "SEQUENCE_EDITOR":
            _space = _area.spaces.active
            _view_type = getattr(_space, "view_type", "SEQUENCER")
            # A combined sequencer/preview editor can expose more than one
            # WINDOW region. Trying only the first one may address the preview
            # half while asking a timeline operator to run (or vice versa),
            # which makes Blender 5.1 reject the context even though the area
            # itself is correct.
            _regions = [r for r in _area.regions if r.type == "WINDOW"]
            if _view_type in {"SEQUENCER", "SEQUENCER_PREVIEW"}:
                _timeline_views += 1
            if _view_type in {"PREVIEW", "SEQUENCER_PREVIEW"}:
                _preview_views += 1
                # Always show the composited result and make the image fit the
                # visible preview region, instead of persisting a stale soloed
                # channel or off-canvas zoom from another monitor layout.
                try:
                    _space.display_channel = 0
                    _space.display_mode = "IMAGE"
                    _space.preview_channels = "COLOR"
                    if hasattr(_space, "use_zoom_to_fit"):
                        _space.use_zoom_to_fit = True
                except Exception as _preview_state_exc:
                    _ui_errors.append({"view_type": _view_type, "error": str(_preview_state_exc)})

            _timeline_done = False
            _preview_done = False
            for _region in _regions:
                try:
                    with bpy.context.temp_override(
                            window=_window, screen=_screen, area=_area, region=_region,
                            space_data=_space, scene=_scene):
                        if _view_type in {"SEQUENCER", "SEQUENCER_PREVIEW"} and not _timeline_done:
                            try:
                                _result = bpy.ops.sequencer.view_all()
                                _timeline_done = "FINISHED" in _result
                            except Exception:
                                _timeline_done = False
                            if not _timeline_done:
                                # Generic View2D framing is a safe GUI fallback
                                # when the sequencer-specific operator rejects a
                                # valid Blender 5.1 sub-region context or
                                # returns CANCELLED without raising.
                                _result = bpy.ops.view2d.smoothview(
                                    xmin=_timeline_min - 30,
                                    xmax=_timeline_max + 30,
                                    ymin=0,
                                    ymax=_channel_max + 2,
                                    wait_for_input=False,
                                )
                                _timeline_done = "FINISHED" in _result
                        if _view_type in {"PREVIEW", "SEQUENCER_PREVIEW"} and not _preview_done:
                            try:
                                _result = bpy.ops.sequencer.view_all_preview()
                                _preview_done = "FINISHED" in _result
                            except Exception:
                                # use_zoom_to_fit above is persistent and does
                                # not require an operator context.
                                _preview_done = bool(getattr(_space, "use_zoom_to_fit", False))
                except Exception as _ui_exc:
                    _ui_errors.append({
                        "view_type": _view_type,
                        "region": [int(getattr(_region, "x", 0)), int(getattr(_region, "y", 0)),
                                   int(getattr(_region, "width", 0)), int(getattr(_region, "height", 0))],
                        "error": str(_ui_exc),
                    })
            if _timeline_done:
                _timeline_framed += 1
            if _preview_done:
                _preview_fitted += 1
            _area.tag_redraw()

    _timeline_bounds = None
    if _strips:
        _timeline_bounds = [
            min(int(s.frame_final_start) for s in _strips),
            max(int(s.frame_final_end) for s in _strips),
        ]
    _has_content = bool(_strips)
    _has_visual_content = bool(_visuals)
    _timeline_ready = _timeline_views > 0 and _timeline_framed == _timeline_views
    _preview_ready = _preview_views == 0 or _preview_fitted == _preview_views
    _current_frame_ready = not _has_visual_content or bool(_active_visuals)
    _media_ready = not _missing_current_media
    _binding_ready = bool(
        _binding.get("scene_binding_match")
        and _binding.get("visible_strip_match")
    )
    _content_ready = (
        _binding_ready
        and
        (not _has_content or _timeline_ready)
        and _preview_ready
        and _current_frame_ready
        and _media_ready
    )
    _code = None
    if not _binding.get("sequencer_scene"):
        _code = "vse_scene_unbound"
    elif not _binding.get("scene_binding_match"):
        _code = "vse_scene_mismatch"
    elif not _binding.get("visible_strip_match"):
        _code = "vse_visible_strip_mismatch"
    elif _missing_current_media:
        _code = "vse_media_missing"
    elif _has_content and not (_timeline_ready and _preview_ready):
        _code = "vse_content_not_framed"
    elif not _current_frame_ready:
        _code = "vse_current_frame_empty"
    print("VP_VSE:" + json.dumps({
        "ready": any(a.type == "SEQUENCE_EDITOR" for a in _areas) and _content_ready,
        "code": _code,
        "workspace": _window.workspace.name if _window.workspace else None,
        "screen": _screen.name if _screen else None,
        "scene": _scene.name,
        "vse_area_count": sum(1 for a in _areas if a.type == "SEQUENCE_EDITOR"),
        "area_types": [a.type for a in _areas],
        "strip_count": len(_strips),
        "playhead": _frame,
        "timeline_bounds": _timeline_bounds,
        "timeline_view_count": _timeline_views,
        "preview_view_count": _preview_views,
        "timeline_framed_count": _timeline_framed,
        "preview_fitted_count": _preview_fitted,
        "current_frame_visual_count": len(_active_visuals),
        "missing_current_media": _missing_current_media,
        "content_display_ready": _content_ready,
        "ui_errors": _ui_errors,
        "layout_profile_version": int(
            _window.workspace.get(_vp_layout_profile_key, 0) or 0
        ) if _window.workspace else 0,
        "layout_profile_current": bool(
            _window.workspace
            and int(_window.workspace.get(_vp_layout_profile_key, 0) or 0)
                == _vp_layout_profile_expected
        ),
        **_binding,
    }, ensure_ascii=False))
''')
    try:
        result = execute_code(code, timeout=10)
    except LiveSessionError as exc:
        return {
            **info,
            "ready": False,
            "transient": True,
            "code": "vse_not_visible",
            "message": f"Could not verify the visible VSE workspace yet: {exc}",
        }
    for line in (result.get("output") or "").splitlines():
        if not line.startswith("VP_VSE:"):
            continue
        try:
            state = json.loads(line[len("VP_VSE:"):])
        except json.JSONDecodeError:
            break
        if state.get("ready"):
            return {**info, **state}
        code = state.get("code") or "vse_not_visible"
        return {
            **info,
            **state,
            "ready": False,
            "transient": code in _TRANSIENT_DISCOVERY_CODES,
            "code": code,
            "message": (
                "Blender is visible, but the requested timeline content is not "
                "yet presented in the Video Editing workspace. Blender "
                "operations remain locked."
            ),
        }
    return {
        **info,
        "ready": False,
        "transient": True,
        "code": "vse_not_visible",
        "message": "Blender did not return VSE workspace readiness evidence.",
    }


def _check_project_match(info: dict[str, Any], project: str | Path | None) -> dict[str, Any]:
    """Protect an already-open human project from a silent session switch."""
    if not project or not info.get("connected"):
        return info
    requested = Path(project)
    current = info.get("filepath") or ""
    if not current:
        # A blank startup file is safe. The caller may create a new project or
        # open the requested file through the normal typed operation path.
        return {**info, "requested_project": str(requested)}
    if _norm_path(current) != _norm_path(requested):
        return {
            **info,
            "ready": False,
            "code": "project_mismatch",
            "requested_project": str(requested),
            "message": (
                "A Blender bridge is connected, but that GUI has a different "
                f"project open ({current}). Refusing to switch it silently; "
                "save/close that project or start a separate configured session."
            ),
        }
    return {**info, "ready": True, "requested_project": str(requested)}


def _prepare_connected_session(project: str | Path | None) -> dict[str, Any]:
    """Prove project identity, native GUI visibility, and a visible VSE area."""
    info = session_info()
    if not info.get("connected"):
        return {
            **info,
            "ready": False,
            "transient": True,
            "code": "session_identity_pending",
            "message": "The Bridge answered, but session identity is not available yet.",
        }

    if project:
        requested = Path(project)
        current = info.get("filepath") or ""
        if not current and info.get("is_dirty"):
            return {
                **info,
                "ready": False,
                "code": "unsaved_session_dirty",
                "requested_project": str(requested),
                "message": (
                    "The connected blank Blender session has unsaved work. "
                    "Refusing to adopt or create a named project automatically."
                ),
            }
        if requested.is_file() and not current:
            code = f'''
import bpy
bpy.ops.wm.open_mainfile(filepath={json.dumps(str(requested.resolve()))})
print("VP_PROJECT_OPENED:" + bpy.data.filepath)
'''
            try:
                opened = execute_code(code, timeout=30)
            except LiveSessionError as exc:
                return {
                    **info,
                    "ready": False,
                    "code": "project_open_failed",
                    "requested_project": str(requested),
                    "message": str(exc),
                }
            if not opened.get("success"):
                return {
                    **info,
                    "ready": False,
                    "code": "project_open_failed",
                    "requested_project": str(requested),
                    "message": opened.get("error") or "Blender could not open the project",
                }
            info = session_info()

        matched = _check_project_match(info, project)
        if matched.get("code") == "project_mismatch":
            return matched
        info = matched

    visible = _with_visibility_proof(info, restore=False)
    if not visible.get("gui_visible"):
        return visible

    vse = _activate_vse_workspace(visible)
    if not vse.get("ready"):
        return vse

    # Re-read after switching workspaces and require consecutive passive
    # observations.  A one-frame HWND appearance is not a user-visible GUI.
    final_info = _stable_visible_session()
    if not final_info.get("stable_visible"):
        return final_info
    if int(final_info.get("vse_area_count") or 0) < 1:
        return {
            **final_info,
            "ready": False,
            "transient": True,
            "code": "vse_not_visible",
            "message": "No visible VSE area was discovered after workspace activation.",
        }

    proof = {
        "pid": final_info.get("pid"),
        "filepath": final_info.get("filepath") or "",
        "requested_project": str(project) if project else None,
        "workspace": final_info.get("workspace"),
        "screen": final_info.get("screen"),
        "vse_area_count": final_info.get("vse_area_count"),
        "gui_visible": True,
        "window_handles": (
            final_info.get("window_evidence", {}).get("window_handles", [])
        ),
        "scene": vse.get("scene"),
        "strip_owner_scene": vse.get("strip_owner_scene"),
        "window_scene": vse.get("window_scene"),
        "sequencer_scene": vse.get("sequencer_scene"),
        "scene_binding_match": bool(vse.get("scene_binding_match")),
        "internal_strip_count": vse.get("internal_strip_count", 0),
        "visible_strip_count": vse.get("visible_strip_count", 0),
        "visible_strip_match": bool(vse.get("visible_strip_match")),
        "strip_count": vse.get("internal_strip_count", vse.get("strip_count", 0)),
        "playhead": vse.get("playhead"),
        "timeline_bounds": vse.get("timeline_bounds"),
        "timeline_view_count": vse.get("timeline_view_count", 0),
        "preview_view_count": vse.get("preview_view_count", 0),
        "timeline_framed_count": vse.get("timeline_framed_count", 0),
        "preview_fitted_count": vse.get("preview_fitted_count", 0),
        "current_frame_visual_count": vse.get("current_frame_visual_count", 0),
        "content_display_ready": bool(vse.get("content_display_ready")),
        "layout_profile_version": vse.get("layout_profile_version", 0),
        "layout_profile_current": bool(vse.get("layout_profile_current")),
        "verified_at": time.time(),
    }
    return {
        **final_info,
        "workspace": final_info.get("workspace"),
        "screen": final_info.get("screen"),
        "vse_area_count": final_info.get("vse_area_count"),
        "content_display": {
            key: vse.get(key) for key in (
                "scene", "strip_owner_scene", "window_scene",
                "sequencer_scene", "scene_binding_match",
                "internal_strip_count", "visible_strip_count",
                "visible_strip_match", "strip_count", "playhead", "timeline_bounds",
                "timeline_view_count", "preview_view_count",
                "timeline_framed_count", "preview_fitted_count",
                "current_frame_visual_count", "missing_current_media",
                "content_display_ready", "ui_errors", "layout_profile_version",
                "layout_profile_current",
            )
        },
        "ready": True,
        "state": "ready",
        "transient": False,
        "session_proof": proof,
    }


def _launch_blender_gui(project: str | Path | None = None) -> subprocess.Popen:
    """Launch visible Blender GUI with the fixed bridge bootstrap script."""
    from .config import find_blender

    blender = find_blender()
    if not blender:
        raise LiveSessionError("blender_missing", "Blender executable was not found")
    if not _GUI_BOOTSTRAP.is_file():
        raise LiveSessionError(
            "bootstrap_missing", f"Blender bridge bootstrap is missing: {_GUI_BOOTSTRAP}")

    args = [blender]
    if project and Path(project).is_file():
        args.append(str(Path(project).resolve()))
    args.extend(["--python", str(_GUI_BOOTSTRAP)])

    env = os.environ.copy()
    env["BLENDER_BRIDGE_HOST"] = BRIDGE_HOST
    env["BLENDER_BRIDGE_PORT"] = str(BRIDGE_PORT)
    if project:
        env["BLENDER_VSE_TARGET_PROJECT"] = str(Path(project).resolve())
        env["VP_BLENDER_TARGET_PROJECT"] = str(Path(project).resolve())

    log_dir = runtime_tmp_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "blender-live-session.log"
    log_handle = log_path.open("a", encoding="utf-8", errors="replace")
    log_handle.write(
        f"\n--- launch {time.strftime('%Y-%m-%d %H:%M:%S')} "
        f"project={project or '<blank>'} ---\n"
    )
    log_handle.flush()

    project_parent = Path(project).resolve().parent if project else None
    working_dir = project_parent if project_parent and project_parent.is_dir() else log_dir

    kwargs: dict[str, Any] = {
        "cwd": str(working_dir),
        "env": env,
        "stdin": subprocess.DEVNULL,
        "stdout": log_handle,
        "stderr": subprocess.STDOUT,
    }
    if os.name == "nt":
        # Keep Blender as a visible, independent GUI application. Never use a
        # hidden/headless process for interactive VSE editing.
        kwargs["creationflags"] = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0)
        )
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
        startup.wShowWindow = 1  # SW_SHOWNORMAL — override a hidden parent shell.
        kwargs["startupinfo"] = startup
    try:
        process = subprocess.Popen(args, **kwargs)
    finally:
        # Popen duplicates the handle for the child process.
        log_handle.close()
    process.session_log = str(log_path)  # type: ignore[attr-defined]
    return process


def _can_repair_hidden_session(result: dict[str, Any], project: str | Path | None) -> bool:
    """True only for a clean hidden session that owns the requested project."""
    if not SESSION_AUTOSTART or not project:
        return False
    last = result.get("last_observation") or result
    if last.get("code") not in {"gui_not_visible", "gui_not_stable"} or not last.get("pid"):
        return False
    if last.get("is_dirty"):
        return False
    current = last.get("filepath") or ""
    requested = str(Path(project))
    if current and _norm_path(current) != _norm_path(requested):
        return False
    # A clean blank startup session is also safe when creating a named project.
    return bool(current or not Path(project).exists())


def _shutdown_hidden_session(result: dict[str, Any], *, timeout: float = 10.0) -> bool:
    """Close one proven-clean invisible GUI via a fixed infrastructure script."""
    last = result.get("last_observation") or result
    if last.get("is_dirty"):
        return False
    code = r'''
import bpy
def _vp_quit_hidden_session():
    try:
        bpy.ops.wm.quit_blender()
    except Exception:
        pass
    return None
bpy.app.timers.register(_vp_quit_hidden_session, first_interval=0.1)
print("VP_HIDDEN_SESSION_QUIT_SCHEDULED")
'''
    try:
        scheduled = execute_code(code, timeout=5)
    except LiveSessionError:
        return False
    if "VP_HIDDEN_SESSION_QUIT_SCHEDULED" not in (scheduled.get("output") or ""):
        return False
    deadline = time.monotonic() + max(1.0, timeout)
    while time.monotonic() < deadline:
        if not ping():
            return True
        time.sleep(0.1)
    return False


def shutdown_live_session_for_restore(
    project: str | Path,
    *,
    timeout: float = 15.0,
) -> dict[str, Any]:
    """Save and close the exact visible project before a checkpoint replace.

    Replacing a ``.blend`` while Blender still holds the old project in memory
    creates a disk/memory split and the next save can overwrite the restored
    file.  This fixed infrastructure action is therefore mandatory before the
    host copies a checkpoint over the canonical project path.
    """
    global _launch_process

    requested = Path(project).resolve()
    prepared = _prepare_connected_session(requested)
    if not prepared.get("ready"):
        return {
            **prepared,
            "closed": False,
            "code": prepared.get("code") or "restore_session_not_ready",
        }
    current = prepared.get("filepath") or ""
    if _norm_path(current) != _norm_path(requested):
        return {
            **prepared,
            "closed": False,
            "code": "project_mismatch",
            "message": "Refusing to close a different Blender project for restore.",
        }
    code = f'''
import bpy
bpy.ops.wm.save_as_mainfile(filepath={json.dumps(str(requested))})
def _vp_quit_for_checkpoint_restore():
    try:
        bpy.ops.wm.quit_blender()
    except Exception:
        pass
    return None
bpy.app.timers.register(_vp_quit_for_checkpoint_restore, first_interval=0.1)
print("VP_RESTORE_SESSION_QUIT_SCHEDULED")
'''
    try:
        scheduled = execute_code(code, timeout=10)
    except LiveSessionError as exc:
        return {
            **prepared,
            "closed": False,
            "code": "restore_session_close_failed",
            "message": str(exc),
        }
    if "VP_RESTORE_SESSION_QUIT_SCHEDULED" not in (scheduled.get("output") or ""):
        return {
            **prepared,
            "closed": False,
            "code": "restore_session_close_failed",
            "message": "Blender did not acknowledge the restore shutdown request.",
        }
    deadline = time.monotonic() + max(1.0, float(timeout))
    while time.monotonic() < deadline:
        if not ping():
            _launch_process = None
            return {
                "closed": True,
                "project": str(requested),
                "pid": prepared.get("pid"),
            }
        time.sleep(0.1)
    return {
        **prepared,
        "closed": False,
        "code": "restore_session_close_timeout",
        "message": "Blender did not close before checkpoint replacement timeout.",
    }


def _wait_for_ready_session(
    project: str | Path | None,
    *,
    deadline: float,
    launched: bool,
    process: subprocess.Popen | None,
    session_log: str | None = None,
) -> dict[str, Any]:
    """Mandatory discovery loop from process start through full GUI readiness."""
    started_at = time.monotonic()
    attempts = 0
    observed_states: list[str] = []
    last: dict[str, Any] = {
        "ready": False,
        "code": "bridge_unreachable",
        "message": "Waiting for the Blender Bridge to become reachable.",
    }

    while time.monotonic() < deadline:
        attempts += 1
        if ping():
            last = _prepare_connected_session(project)
            state = str(last.get("code") or last.get("state") or "bridge_found")
            if not observed_states or observed_states[-1] != state:
                observed_states.append(state)
            if last.get("ready"):
                waited = max(0.0, time.monotonic() - started_at)
                return {
                    **last,
                    "launched": launched,
                    "pid": last.get("pid") or (process.pid if process else None),
                    "session_log": session_log,
                    "discovery": {
                        "mandatory": True,
                        "attempts": attempts,
                        "waited_seconds": round(waited, 3),
                        "observed_states": observed_states,
                    },
                }
            if last.get("code") not in _TRANSIENT_DISCOVERY_CODES:
                return {
                    **last,
                    "launched": launched,
                    "pid": last.get("pid") or (process.pid if process else None),
                    "session_log": session_log,
                    "discovery": {
                        "mandatory": True,
                        "attempts": attempts,
                        "observed_states": observed_states,
                    },
                }
        elif not observed_states or observed_states[-1] != "bridge_unreachable":
            observed_states.append("bridge_unreachable")

        if process is not None and process.poll() is not None:
            return {
                **last,
                "ready": False,
                "launched": launched,
                "pid": process.pid,
                "session_log": session_log,
                "code": "blender_exited",
                "message": "Blender exited before the visible GUI session became ready.",
                "discovery": {
                    "mandatory": True,
                    "attempts": attempts,
                    "observed_states": observed_states,
                },
            }
        time.sleep(0.25)

    waited = max(0.0, time.monotonic() - started_at)
    return {
        **last,
        "ready": False,
        "launched": launched,
        "pid": last.get("pid") or (process.pid if process else None),
        "session_log": session_log,
        "code": "session_discovery_timeout",
        "message": (
            "Blender was started or detected, but the mandatory discovery "
            "sequence did not reach visible GUI + Bridge + project + VSE "
            f"readiness before timeout. Last state: {last.get('code') or 'unknown'}."
        ),
        "last_observation": last,
        "discovery": {
            "mandatory": True,
            "attempts": attempts,
            "waited_seconds": round(waited, 3),
            "observed_states": observed_states,
        },
    }


def ensure_live_session(
    project: str | Path | None = None,
    *,
    timeout: float | None = None,
    launch: bool = True,
) -> dict[str, Any]:
    """Ensure a visible Blender GUI + Bridge session is ready.

    Reuses an existing bridge when available. Otherwise it launches Blender
    with a fixed, vendored bootstrap (never Agent-authored bpy), waits for the
    TCP handshake, and returns structured readiness information.
    """
    global _launch_process

    wait_seconds = SESSION_START_TIMEOUT if timeout is None else max(1.0, float(timeout))
    deadline = time.monotonic() + wait_seconds

    if ping():
        # A TCP handshake alone is not readiness.  In particular, the Bridge
        # can answer before Windows exposes Blender's native GUI window.
        first_deadline = min(
            deadline,
            time.monotonic() + max(1.0, SESSION_VISIBILITY_GRACE),
        )
        observed = _wait_for_ready_session(
            project,
            deadline=first_deadline,
            launched=False,
            process=None,
        )
        if observed.get("ready") or not _can_repair_hidden_session(observed, project):
            return observed

        # A clean, identity-matched Blender that has a Bridge but no native
        # desktop window cannot satisfy the user contract.  Repair it once by
        # closing only that invisible saved session and relaunching visibly.
        old_pid = (observed.get("last_observation") or observed).get("pid")
        if not _shutdown_hidden_session(observed):
            return {
                **observed,
                "code": "hidden_session_repair_failed",
                "message": (
                    "A clean hidden Blender session was detected, but it could "
                    "not be closed safely for visible relaunch."
                ),
            }
        with _launch_lock:
            try:
                _launch_process = _launch_blender_gui(project)
            except (OSError, LiveSessionError) as exc:
                code = exc.code if isinstance(exc, LiveSessionError) else "launch_failed"
                return {
                    "ready": False,
                    "launched": False,
                    "code": code,
                    "message": str(exc),
                    "repaired_hidden_pid": old_pid,
                }
        repaired = _wait_for_ready_session(
            project,
            deadline=time.monotonic() + wait_seconds,
            launched=True,
            process=_launch_process,
            session_log=getattr(_launch_process, "session_log", None),
        )
        repaired["repaired_hidden_session"] = True
        repaired["repaired_hidden_pid"] = old_pid
        return repaired

    capability = launch_capability()
    if not launch or not capability["launchable"]:
        return {
            **capability,
            "ready": False,
            "launched": False,
            "code": "bridge_unreachable",
            "message": (
                "No live Blender bridge is connected and automatic GUI launch "
                "is unavailable. Check Blender installation or set "
                "BLENDER_VSE_AUTOSTART=1."
            ),
        }

    process: subprocess.Popen | None = None
    launched = False
    with _launch_lock:
        # Another thread/process may have established the bridge while this
        # caller waited for the launch lock.
        if ping():
            return _wait_for_ready_session(
                project,
                deadline=deadline,
                launched=False,
                process=None,
            )

        # If a prior call timed out while Blender was still booting, continue
        # discovering that managed process.  Never spawn a duplicate merely
        # because the first discovery window elapsed.
        if _launch_process is not None and _launch_process.poll() is None:
            process = _launch_process
            launched = True
        else:
            try:
                _launch_process = _launch_blender_gui(project)
                process = _launch_process
                launched = True
            except (OSError, LiveSessionError) as exc:
                code = exc.code if isinstance(exc, LiveSessionError) else "launch_failed"
                return {
                    **capability,
                    "ready": False,
                    "launched": False,
                    "code": code,
                    "message": str(exc),
                }

    return _wait_for_ready_session(
        project,
        deadline=deadline,
        launched=launched,
        process=process,
        session_log=getattr(process, "session_log", None),
    )


def execute_code(code: str, timeout: int = BRIDGE_TIMEOUT) -> dict[str, Any]:
    """Execute bpy code inside the live GUI Blender (main thread).

    Returns a dict with keys: success, output, error.
    Raises LiveSessionError if the bridge is unreachable.
    """
    resp = _send_cmd({"type": "execute_code", "params": {"code": code}}, timeout=timeout)
    if resp.get("status") != "success":
        raise LiveSessionError(
            "bridge_error",
            resp.get("message") or resp.get("result", {}).get("error") or "unknown bridge error",
        )
    inner = resp.get("result", {})
    return {
        "success": bool(inner.get("success", True)),
        "output": inner.get("output", "") or "",
        "error": inner.get("error"),
    }


# ---------------------------------------------------------------------------
# Refresh helpers — run AFTER every mutating VSE edit so the user's open GUI
# (timeline + preview) reflects the change immediately.
# ---------------------------------------------------------------------------


def refresh_ui_script() -> str:
    """bpy script that redraws sequencer areas + refreshes current frame/preview.

    This is appended after every mutating op in live_session mode. It:
      1. re-evaluates strip state (scene.update / update_tag — both work),
      2. re-sets the current frame so the VSE preview recomputes,
      3. tags every SEQUENCE_EDITOR / SEQUENCE_PREVIEW area for redraw.
    """
    return '''
scene = bpy.context.scene
try:
    scene.update()
except AttributeError:
    scene.update_tag()
# force preview recompute for the current frame
cf = scene.frame_current
scene.frame_set(cf)
for area in bpy.context.screen.areas:
    if area.type in {"SEQUENCE_EDITOR", "SEQUENCE_PREVIEW"}:
        area.tag_redraw()
'''


def capture_preview_script(filepath: str) -> str:
    """bpy script that screenshots the VSE preview area.

    The upstream addon's screenshot_viewport only handles VIEW_3D; the VSE
    preview needs its own area override. Returns PNG at ``filepath``.
    """
    return f'''
import os
os.makedirs(os.path.dirname({json.dumps(filepath)}), exist_ok=True)
area = None
combined = None
for a in bpy.context.screen.areas:
    if a.type != "SEQUENCE_EDITOR":
        continue
    view_type = getattr(a.spaces.active, "view_type", "SEQUENCER")
    if view_type == "PREVIEW":
        area = a
        break
    if view_type == "SEQUENCER_PREVIEW":
        combined = a
if area is None:
    area = combined
if area is None:
    raise RuntimeError("no VSE PREVIEW area open (open the Video Editing workspace)")
region = next((r for r in area.regions if r.type == "WINDOW"), None)
with bpy.context.temp_override(area=area, region=region, space_data=area.spaces.active):
    bpy.ops.screen.screenshot_area(filepath={json.dumps(filepath)})
'''


def check_live_session() -> dict:
    """Structured live-session status for environment_report / tooling."""
    alive = ping()
    identity = session_info() if alive else {}
    project = identity.get("filepath") or None
    info = _prepare_connected_session(project) if alive else {}
    proof = info.get("session_proof") or {}
    ready = bool(alive and info.get("ready") and proof.get("content_display_ready"))
    if ready:
        hint = None
    elif alive:
        hint = (
            "The Blender Bridge is reachable, but stable interactive-desktop "
            "window + Video Sequence Editor proof is missing. Operations stay "
            "locked until ensure_live_session completes discovery or repair."
        )
    else:
        hint = (
            "No live Blender GUI bridge detected. The next Blender capability "
            "will run the mandatory visible-GUI bootstrap and discovery flow."
        )
    return {
        "live_session": alive,
        "gui_visible": bool(info.get("gui_visible")),
        "pid": info.get("pid"),
        "workspace": info.get("workspace"),
        "vse_area_count": info.get("vse_area_count", 0),
        "strip_owner_scene": proof.get("strip_owner_scene"),
        "window_scene": proof.get("window_scene"),
        "sequencer_scene": proof.get("sequencer_scene"),
        "scene_binding_match": bool(proof.get("scene_binding_match")),
        "internal_strip_count": proof.get("internal_strip_count", 0),
        "visible_strip_count": proof.get("visible_strip_count", 0),
        "visible_strip_match": bool(proof.get("visible_strip_match")),
        "content_display_ready": bool(proof.get("content_display_ready")),
        "code": info.get("code"),
        "window_evidence": info.get("window_evidence"),
        "bridge_host": BRIDGE_HOST,
        "bridge_port": BRIDGE_PORT,
        "mode": "live_session" if ready else "not_ready",
        "hint": hint,
    }
