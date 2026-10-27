"""Shared Blender VSE scene/presentation compatibility contract.

This module contains no Blender imports.  It only returns fixed, allowlisted
script fragments that are embedded by ``live_session`` and ``vse_ops``.  Keeping
the Blender 5.1 ``workspace.sequencer_scene`` rule here prevents project
creation, live-session recovery, edit execution, and persistence verification
from drifting into different definitions of "the visible timeline".
"""
from __future__ import annotations


VSE_LAYOUT_PROFILE_KEY = "blender_vse_layout_version"
VSE_LAYOUT_PROFILE_VERSION = 1
VSE_WORKSPACE_NAME = "Video Editing"
PROJECTS_DIRNAME = "blender-vse-projects"


def binding_helpers_script() -> str:
    """Return fixed bpy helpers for resolving, binding, and proving a VSE scene."""
    return r'''
def _vp_vse_strip_count(_vp_scene):
    if _vp_scene is None:
        return 0
    _vp_seq = getattr(_vp_scene, "sequence_editor", None)
    return len(_vp_seq.strips) if _vp_seq is not None else 0

def _vp_resolve_edit_scene(_vp_preferred="VideoEditing", _vp_fallback=None):
    _vp_named = bpy.data.scenes.get(_vp_preferred) if _vp_preferred else None
    if _vp_named is not None and (
            _vp_vse_strip_count(_vp_named) > 0
            or _vp_vse_strip_count(_vp_fallback) == 0):
        return _vp_named
    if _vp_fallback is not None and _vp_vse_strip_count(_vp_fallback) > 0:
        return _vp_fallback
    if len(bpy.data.scenes):
        return max(bpy.data.scenes, key=_vp_vse_strip_count)
    return _vp_fallback

def _vp_bind_vse_window(_vp_window, _vp_edit_scene):
    if _vp_window is None or _vp_edit_scene is None:
        return
    _vp_window.scene = _vp_edit_scene
    # A workspace just assigned to the window becomes active on Blender's next
    # event loop, so the Video Editing workspace is bound even before it shows.
    for _vp_workspace in (
            getattr(_vp_window, "workspace", None),
            bpy.data.workspaces.get("Video Editing")):
        if _vp_workspace is not None and hasattr(_vp_workspace, "sequencer_scene"):
            _vp_workspace.sequencer_scene = _vp_edit_scene

def _vp_bind_vse_all_windows(_vp_edit_scene):
    _vp_bound = []
    for _vp_wm in bpy.data.window_managers:
        for _vp_window in _vp_wm.windows:
            _vp_bind_vse_window(_vp_window, _vp_edit_scene)
            _vp_bound.append(_vp_vse_binding_proof(_vp_window, _vp_edit_scene))
    return _vp_bound

def _vp_vse_binding_proof(_vp_window, _vp_edit_scene):
    _vp_workspace = getattr(_vp_window, "workspace", None) if _vp_window else None
    _vp_window_scene = getattr(_vp_window, "scene", None) if _vp_window else None
    if _vp_workspace is not None and hasattr(_vp_workspace, "sequencer_scene"):
        _vp_visible_scene = getattr(_vp_workspace, "sequencer_scene", None)
        _vp_binding_supported = True
    else:
        _vp_visible_scene = _vp_window_scene
        _vp_binding_supported = False
    _vp_internal_count = _vp_vse_strip_count(_vp_edit_scene)
    _vp_visible_count = _vp_vse_strip_count(_vp_visible_scene)
    return {
        "strip_owner_scene": getattr(_vp_edit_scene, "name", None),
        "window_scene": getattr(_vp_window_scene, "name", None),
        "sequencer_scene": getattr(_vp_visible_scene, "name", None),
        "sequencer_scene_supported": _vp_binding_supported,
        "scene_binding_match": bool(
            _vp_edit_scene is not None
            and _vp_window_scene == _vp_edit_scene
            and _vp_visible_scene == _vp_edit_scene
        ),
        "internal_strip_count": _vp_internal_count,
        "visible_strip_count": _vp_visible_count,
        "visible_strip_match": _vp_internal_count == _vp_visible_count,
    }
'''


def vse_workspace_script() -> str:
    """Return fixed bpy helpers that install Blender's native editing workspace.

    Blender's factory startup has no Video Editing workspace. Duplicating the
    Layout workspace instead leaves its outliner, object properties, and
    timeline beside a single combined sequencer/preview area, so the window
    reads as a 3D scene with a timeline bolted on. The Video Editing app
    template ships the real workspace (file browser, preview, and strip
    properties above a full-width sequencer), so it is appended from there.
    """
    return f'''
import os
_vp_workspace_name = {VSE_WORKSPACE_NAME!r}
_vp_workspace_profile_key = {VSE_LAYOUT_PROFILE_KEY!r}
_vp_workspace_profile_version = {VSE_LAYOUT_PROFILE_VERSION}
_vp_projects_dirname = {PROJECTS_DIRNAME!r}
''' + r'''
def _vp_vse_workspace_usable(_vp_ws):
    """True when the workspace shows a separate preview and timeline."""
    if _vp_ws is None or not len(_vp_ws.screens):
        return False
    _vp_views = {
        getattr(_vp_a.spaces.active, "view_type", None)
        for _vp_a in _vp_ws.screens[0].areas
        if _vp_a.type == "SEQUENCE_EDITOR"
    }
    return {"PREVIEW", "SEQUENCER"} <= _vp_views

def _vp_vse_template_path():
    return os.path.join(
        bpy.utils.system_resource("SCRIPTS"), "startup",
        "bl_app_templates_system", "Video_Editing", "startup.blend")

def _vp_project_browse_dir(_vp_blend=""):
    """The workspace folder that holds blender-vse-projects, else the .blend's."""
    _vp_blend = _vp_blend or bpy.data.filepath
    if not _vp_blend:
        return ""
    _vp_dir = os.path.dirname(os.path.abspath(_vp_blend))
    _vp_probe = _vp_dir
    while True:
        if os.path.basename(_vp_probe) == _vp_projects_dirname:
            return os.path.dirname(_vp_probe)
        _vp_parent = os.path.dirname(_vp_probe)
        if _vp_parent == _vp_probe:
            return _vp_dir
        _vp_probe = _vp_parent

def _vp_point_file_browsers(_vp_ws, _vp_blend=""):
    """Open the workspace file browsers on the project folder.

    A browser already inside that folder is left where the user navigated.
    Returns the folder, or None when a browser has no params yet because
    Blender has not drawn it.
    """
    _vp_root = _vp_project_browse_dir(_vp_blend)
    if not _vp_root or _vp_ws is None:
        return _vp_root
    _vp_prefix = os.path.join(os.path.normcase(_vp_root), "")
    for _vp_screen in _vp_ws.screens:
        for _vp_a in _vp_screen.areas:
            if _vp_a.type != "FILE_BROWSER":
                continue
            _vp_space = _vp_a.spaces.active
            if getattr(_vp_space, "browse_mode", "FILES") != "FILES":
                continue
            _vp_params = getattr(_vp_space, "params", None)
            if _vp_params is None:
                return None
            _vp_current = _vp_params.directory
            if isinstance(_vp_current, bytes):
                _vp_current = os.fsdecode(_vp_current)
            _vp_current = os.path.join(os.path.normcase(os.path.abspath(_vp_current or "/")), "")
            if not _vp_current.startswith(_vp_prefix):
                # Without the trailing separator Blender can fall back to "/".
                _vp_params.directory = os.fsencode(os.path.join(_vp_root, ""))
            _vp_a.tag_redraw()
    return _vp_root

def _vp_remove_workspaces(_vp_names, _vp_persist):
    _vp_shown = {
        _vp_w.workspace for _vp_wm in bpy.data.window_managers for _vp_w in _vp_wm.windows
    }
    _vp_ids = [
        _vp_ws for _vp_ws in bpy.data.workspaces
        if _vp_ws.name in _vp_names and _vp_ws not in _vp_shown
    ]
    # Only persist the cleanup when nothing else changed since the last save,
    # so unrelated unsaved work is never written behind the user's back.
    _vp_clean = bool(bpy.data.filepath) and not bpy.data.is_dirty
    if _vp_ids:
        bpy.data.batch_remove(_vp_ids)
    if _vp_persist and _vp_clean:
        bpy.ops.wm.save_mainfile()
    return None

def _vp_install_vse_workspace(_vp_window, _vp_prune=False, _vp_blend=""):
    """Activate a usable Video Editing workspace on the window.

    An existing usable workspace is kept as the user arranged it. A missing or
    unusable one is replaced by the app-template workspace. ``_vp_prune``
    deletes every other workspace (and saves that cleanup) and is only safe
    on a freshly created project, whose other tabs are factory leftovers.
    ``_vp_blend`` names the project before its first save.
    """
    _vp_current = bpy.data.workspaces.get(_vp_workspace_name)
    _vp_report = {"installed": False, "replaced": False, "pruned": []}
    _vp_target = _vp_current if _vp_vse_workspace_usable(_vp_current) else None
    if _vp_target is None:
        _vp_template = _vp_vse_template_path()
        if not os.path.isfile(_vp_template):
            _vp_report["error"] = "Video Editing app template missing: " + _vp_template
            return _vp_report
        if _vp_current is not None:
            _vp_current.name = _vp_workspace_name + " (legacy)"
        with bpy.data.libraries.load(_vp_template, link=False) as (_vp_src, _vp_dst):
            _vp_dst.workspaces = [_vp_workspace_name]
        _vp_target = _vp_dst.workspaces[0]
        _vp_target.name = _vp_workspace_name
        _vp_target[_vp_workspace_profile_key] = _vp_workspace_profile_version
        _vp_report["installed"] = True
        _vp_report["replaced"] = _vp_current is not None
    if _vp_window is not None and _vp_window.workspace != _vp_target:
        _vp_window.workspace = _vp_target
    _vp_report["browse_dir"] = _vp_point_file_browsers(_vp_target, _vp_blend)
    if _vp_report["browse_dir"] is None and not bpy.app.background:
        # A freshly shown browser gets its params on first draw.
        bpy.app.timers.register(
            lambda: None if _vp_point_file_browsers(_vp_target, _vp_blend) is not None else 0.2,
            first_interval=0.2)
    # The legacy workspace is the broken layout this replaces; a template
    # install on a fresh project additionally drops the factory 3D tabs.
    # Blender applies the window's workspace switch on its next event loop and
    # the delete operator only acts on the active workspace, so the removal
    # runs from a timer once no window still shows a doomed workspace.
    _vp_doomed = [
        _vp_ws.name for _vp_ws in bpy.data.workspaces
        if _vp_ws != _vp_target and (
            (_vp_prune and _vp_report["installed"])
            or _vp_ws.name == _vp_workspace_name + " (legacy)")
    ]
    if _vp_doomed and not bpy.app.background:
        bpy.app.timers.register(
            lambda: _vp_remove_workspaces(_vp_doomed, _vp_prune), first_interval=0.2)
        _vp_report["pruned"] = _vp_doomed
    return _vp_report
'''
