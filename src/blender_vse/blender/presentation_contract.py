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
    _vp_workspace = getattr(_vp_window, "workspace", None)
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
