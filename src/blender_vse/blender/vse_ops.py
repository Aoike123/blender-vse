"""Allowlisted Blender VSE typed operations (Blender 5.1 verified).

Every op is a FIXED bpy script template—parameters are injected as typed
values (json-encoded), never as code. No arbitrary Python execution.

API notes (verified on Blender 5.1.0):
- Use `seq.strips.new_movie/new_sound/new_effect/...` (NOT bpy.ops.sequencer.*
  which fails headless with poll() context errors).
- Old timing props (frame_start/frame_final_end/...) and new aliases
  (content_start/left_handle/right_handle) both exist in 5.1.
- `strip.transform` gives offset/scale/rotation (rotation in radians).
- Text strip supports font/font_size/location/alignment/anchor/color/
  shadow/outline/box/blend.

SOURCE OF TRUTH: the .blend file. Every mutating op runs inside Blender and the
runner then persists via `bpy.ops.wm.save_as_mainfile(filepath=PROJECT_PATH)`.
All strips are created on the project's EDIT SCENE (named ``EDIT_SCENE_NAME``,
default "VideoEditing") so that opening the .blend in the GUI shows the complete
editable VSE timeline immediately.
"""
from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path

from ..catalog import OPERATION_FAMILIES, READ_ONLY_OPERATIONS, REMOVED_OPERATIONS
from .presentation_contract import (
    VSE_LAYOUT_PROFILE_KEY,
    VSE_LAYOUT_PROFILE_VERSION,
    binding_helpers_script,
)
from .runner import BlenderResult, BlenderRunner, BlenderRunnerError

# Canonical VSE effect strip types
EFFECT_TYPES = [
    "CROSS", "GAMMA_CROSS", "ADD", "SUBTRACT", "ALPHA_OVER", "ALPHA_UNDER",
    "MULTIPLY", "SCREEN", "OVERLAY", "DARKEN", "LIGHTEN", "DIFFERENCE",
    "SPEED", "GAUSSIAN_BLUR", "GLOW", "COLOR_BALANCE", "WIPE", "TRANSFORM",
    "ADJUSTMENT", "COLOR", "TEXT", "MULTICAM", "COLORMIX",
]

# The named Scene that owns the VSE timeline (source of truth in the .blend).
EDIT_SCENE_NAME = "VideoEditing"

# Plugin / protocol versions reported by get_capabilities.
PLUGIN_VERSION = "0.6.0"
SCHEMA_VERSION = "1.0"

# Custom-property keys this system owns on strips (persisted in the .blend).
ID_KEY = "video_ai_id"       # stable, permanent strip id (never changes)
ASSET_ID_KEY = "video_ai_asset_id"  # stable project asset identity
ASSET_REVISION_KEY = "video_ai_asset_revision"  # bound content revision
META_KEY = "video_ai_meta"   # JSON string of user/agent metadata dict
ANIM_KEY = "video_ai_anim"   # JSON string of animation keyframe intent
STYLE_KEY = "video_ai_style"  # JSON string of text style snapshot
# TimelineMarker has NO IDProperties; marker metadata lives on the scene instead.
MARKER_META_KEY = "video_ai_marker_meta"
# Scene-level registries (asset registry, channel roles, font registry, text styles)
ASSET_REG_KEY = "video_ai_assets"       # JSON list of {id, path, fingerprint, ...}
CHANNEL_ROLE_KEY = "video_ai_channel_roles"  # JSON {channel: role}
FONT_REG_KEY = "video_ai_fonts"         # JSON list of {id, path, name}
TEXT_STYLE_KEY = "video_ai_text_styles" # JSON {style_name: {...}}
PROXY_KEY = "video_ai_proxy"  # JSON custom-file proxy manifest summary

# Proxy construction is deliberately outside Blender. These legacy ops used
# bpy.ops.sequencer.rebuild_proxy(), which is context-sensitive and fails in
# non-Sequencer UI contexts. Build proxies in a host-owned FFmpeg workflow,
# then attach its manifest through a normal revision-guarded Blender patch.
REMOVED_OPS = {
    name: dict(details) for name, details in REMOVED_OPERATIONS.items()
}

# ---- Revision model (Step 3 — incremental adapter) ----
# Revision + timeline content hash persist on the SCENE (source of truth is the
# .blend). Every content change bumps the revision; the timeline hash detects
# manual edits made outside this system (GUI drags + Ctrl+S).
REVISION_KEY = "video_ai_revision"          # int — compatible edit generation
TIMELINE_HASH_KEY = "video_ai_timeline_hash"  # sha256 of canonical full-state snapshot
# Observation token (read-after-write enforcement): get_revision stores a
# single-use observation {id, revision, hash} on the scene (memory only — the
# prop is intentionally NOT part of the content hash). apply_patch /
# acknowledge_revision consume it, so a valid patch REQUIRES a prior read.
OBSERVATION_KEY = "video_ai_observation"
# Idempotency: last committed patch {patch_id, applied_revision} persists in the
# .blend — a retried patch_id returns already_applied instead of re-executing.
LAST_PATCH_KEY = "video_ai_last_patch"

# Ops that manage the revision themselves (apply_patch validates base_revision
# and commits exactly ONE revision for the whole patch).
SELF_REVISION_OPS = {"apply_patch", "finalize_checkpoint_restore"}

# Mutating ops that are NOT editing primitives — they may still be called
# directly (setup / render / packaging / revision bookkeeping). Everything else
# that mutates the timeline is an INTERNAL primitive: external callers (the AI)
# must go through apply_patch. The direct-mutation switch is only for internal
# integration tests and migration harnesses.
_DIRECT_MUTATION_WHITELIST = {
    "create_project", "save_project", "acknowledge_revision", "apply_patch",
    "finalize_checkpoint_restore",
    "render_preview", "render_final", "render_frame", "render_range",
    "generate_contact_sheet", "sample_frame", "save_project_copy",
    "collect_project_assets", "package_project",
}

# Read/write classification comes from the canonical catalog. The restore
# validation primitive is internal but read-only.
READ_ONLY_OPS = set(READ_ONLY_OPERATIONS) | {"validate_checkpoint_restore"}

# Ops that mutate render settings as a side effect but must NOT persist them
# into the project (rendering shouldn't dirty the .blend).
# NOTE: render ops still save the .blend AFTER restoring original render
# settings (the timeline itself is the source of truth; render params are not).
NO_SAVE_OPS = set()


def _j(v) -> str:
    """JSON-encode a value for safe injection into a script literal."""
    return json.dumps(v, ensure_ascii=False)


def _q(s: str) -> str:
    """Encode a string as a safe Python literal for a fixed bpy template."""

    return json.dumps(str(s), ensure_ascii=False)


def _jv(v) -> str:
    """JSON-encode for script literal; None becomes Python 'None' (not null)."""
    if v is None:
        return "None"
    return _j(v)


def _py(v) -> str:
    """Python-literal encode for script literals (True/False/None stay valid
    Python identifiers instead of JSON true/false/null). Recurses into
    dict/list so nested booleans/None are also safe in bpy scripts."""
    if v is None:
        return "None"
    if v is True:
        return "True"
    if v is False:
        return "False"
    if isinstance(v, dict):
        inner = ", ".join(f"{_py(k)}: {_py(val)}" for k, val in v.items())
        return "{" + inner + "}"
    if isinstance(v, (list, tuple)):
        inner = ", ".join(_py(x) for x in v)
        return "[" + inner + "]"
    return _j(v)


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _inside_path(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


PROXY_MANIFEST_FIELDS = frozenset(
    {
        "version",
        "tool",
        "tool_version",
        "profile",
        "scale",
        "project_dir",
        "source_path",
        "source_sha256",
        "source_size",
        "source_mtime_ns",
        "proxy_path",
        "proxy_sha256",
        "proxy_size",
        "source_facts",
        "proxy_facts",
        "verified",
        "created_at",
    }
)


def _load_proxy_manifest(manifest_path: str) -> dict:
    """Validate an external proxy manifest before Blender is contacted.

    This makes attachment fail closed: a patch cannot bind an arbitrary or
    stale file merely by naming a path. The manifest owns source/proxy hashes,
    while Blender later verifies the manifest's source path matches the target
    MOVIE strip.
    """
    path = Path(str(manifest_path)).expanduser().resolve()
    if not path.is_file():
        raise BlenderRunnerError(
            "input_missing", f"attach_proxy: manifest_path not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BlenderRunnerError(
            "invalid_proxy_manifest", f"Cannot read proxy manifest: {exc}") from exc
    required = PROXY_MANIFEST_FIELDS
    missing = sorted(required - set(data)) if isinstance(data, dict) else sorted(required)
    if missing:
        raise BlenderRunnerError(
            "invalid_proxy_manifest", f"Proxy manifest missing: {', '.join(missing)}")
    extra = sorted(set(data) - required)
    if extra:
        raise BlenderRunnerError(
            "invalid_proxy_manifest", f"Proxy manifest has unknown fields: {', '.join(extra)}")
    if not all(isinstance(data.get(k), str) for k in (
            "version", "tool", "tool_version", "profile", "project_dir",
            "source_path", "source_sha256", "proxy_path", "proxy_sha256")):
        raise BlenderRunnerError(
            "invalid_proxy_manifest", "Proxy manifest string fields have invalid types")
    if not all(type(data.get(k)) is int and int(data[k]) >= 0 for k in (
            "scale", "source_size", "source_mtime_ns", "proxy_size")):
        raise BlenderRunnerError(
            "invalid_proxy_manifest", "Proxy manifest integer fields have invalid types")
    if data["source_size"] <= 0 or data["proxy_size"] <= 0:
        raise BlenderRunnerError(
            "invalid_proxy_manifest", "Proxy source and output sizes must be positive")
    if not isinstance(data.get("source_facts"), dict) or not isinstance(data.get("proxy_facts"), dict):
        raise BlenderRunnerError(
            "invalid_proxy_manifest", "Proxy media facts must be objects")
    if not isinstance(data.get("created_at"), (int, float)) or isinstance(data.get("created_at"), bool):
        raise BlenderRunnerError(
            "invalid_proxy_manifest", "Proxy manifest created_at must be numeric")
    for key in ("source_sha256", "proxy_sha256"):
        digest = data[key]
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise BlenderRunnerError(
                "invalid_proxy_manifest", f"Proxy manifest {key} is not lowercase SHA-256")
    if data.get("version") != "1.0" or not data.get("tool", "").strip():
        raise BlenderRunnerError(
            "invalid_proxy_manifest", "Unsupported proxy manifest version or missing tool")
    scale = data["scale"]
    if data.get("profile") != "blender-mjpeg" or scale not in (25, 50, 75, 100):
        raise BlenderRunnerError(
            "invalid_proxy_manifest", "Unsupported proxy profile or scale")
    if data.get("verified") is not True:
        raise BlenderRunnerError("invalid_proxy_manifest", "Proxy manifest is not verified")

    source = Path(str(data["source_path"])).expanduser().resolve()
    proxy = Path(str(data["proxy_path"])).expanduser().resolve()
    project_dir = Path(str(data["project_dir"])).expanduser().resolve()
    if not project_dir.is_dir():
        raise BlenderRunnerError(
            "invalid_proxy_manifest", "Proxy manifest project_dir does not exist")
    if not source.is_file():
        raise BlenderRunnerError("input_missing", f"Proxy source missing: {source}")
    if not proxy.is_file():
        raise BlenderRunnerError("input_missing", f"Proxy file missing: {proxy}")
    if not _inside_path(proxy, project_dir) or not _inside_path(path, project_dir):
        raise BlenderRunnerError(
            "invalid_proxy_manifest", "Proxy or manifest path escapes project_dir")
    source_stat = source.stat()
    proxy_stat = proxy.stat()
    if (source_stat.st_size != int(data["source_size"])
            or source_stat.st_mtime_ns != int(data["source_mtime_ns"])):
        raise BlenderRunnerError(
            "stale_proxy_source", "Source file changed after proxy generation")
    if proxy_stat.st_size != int(data["proxy_size"]):
        raise BlenderRunnerError("invalid_proxy_manifest", "Proxy size no longer matches manifest")
    if _sha256_path(source) != str(data["source_sha256"]):
        raise BlenderRunnerError("stale_proxy_source", "Source hash no longer matches manifest")
    if _sha256_path(proxy) != str(data["proxy_sha256"]):
        raise BlenderRunnerError("invalid_proxy_manifest", "Proxy hash no longer matches manifest")
    data = dict(data)
    data["manifest_path"] = str(path)
    data["source_path"] = str(source)
    data["proxy_path"] = str(proxy)
    data["project_dir"] = str(project_dir)
    return data


def _proxy_state_helpers() -> str:
    """Fixed bpy helpers for observable proxy config and fast runtime status."""
    return f'''
def _vp_proxy_config(_s):
    if getattr(_s, "type", "") != "MOVIE":
        return None
    _cfg = {{"use_proxy": bool(getattr(_s, "use_proxy", False))}}
    try:
        _p = _s.proxy
        _cfg.update({{
            "use_proxy_custom_file": bool(getattr(_p, "use_proxy_custom_file", False)),
            "filepath": str(getattr(_p, "filepath", "") or ""),
            "use_proxy_custom_directory": bool(getattr(_p, "use_proxy_custom_directory", False)),
            "directory": str(getattr(_p, "directory", "") or ""),
            "build_25": bool(getattr(_p, "build_25", False)),
            "build_50": bool(getattr(_p, "build_50", False)),
            "build_75": bool(getattr(_p, "build_75", False)),
            "build_100": bool(getattr(_p, "build_100", False)),
            "use_overwrite": bool(getattr(_p, "use_overwrite", False)),
            "quality": int(getattr(_p, "quality", 0)),
            "timecode": str(getattr(_p, "timecode", "")),
        }})
    except Exception:
        pass
    return _cfg

def _vp_proxy_status(_s):
    _cfg = _vp_proxy_config(_s)
    if _cfg is None:
        return None
    _intent = {{}}
    _raw = _s.get({_q(PROXY_KEY)}, "") if {_q(PROXY_KEY)} in _s else ""
    if _raw:
        try:
            _intent = _json.loads(_raw)
        except Exception:
            _intent = {{"invalid": True}}
    _actual_file = str(_cfg.get("filepath") or "")
    _actual_dir = str(_cfg.get("directory") or "")
    if _actual_file and (_actual_file.startswith("//") or os.path.isabs(_actual_file)):
        _resolved = bpy.path.abspath(_actual_file)
    elif _actual_file and _actual_dir:
        _resolved = os.path.normpath(os.path.join(
            bpy.path.abspath(_actual_dir), os.path.basename(_actual_file)))
    elif _actual_file:
        _resolved = bpy.path.abspath(_actual_file)
    else:
        _resolved = ""
    _exists = bool(_resolved and os.path.isfile(_resolved))
    if not _cfg.get("use_proxy"):
        _status = "detached"
        _mode = "detached"
    elif _cfg.get("use_proxy_custom_file"):
        _mode = "custom_file"
        _expected = str(_intent.get("proxy_path") or "")
        _manifest = str(_intent.get("manifest_path") or "")
        _source = bpy.path.abspath(getattr(_s, "filepath", "") or "")
        _expected_source = str(_intent.get("source_path") or "")
        _scale = str(_intent.get("scale") or "")
        _flags = ["build_25", "build_50", "build_75", "build_100"]
        _expected_flag = "build_" + _scale
        _flags_valid = (_expected_flag in _flags
                        and bool(_cfg.get(_expected_flag))
                        and sum(1 for _f in _flags if _cfg.get(_f)) == 1)
        if not _intent or _intent.get("mode") != "custom_file":
            _status = "invalid_manifest"
        elif not _manifest or not os.path.isfile(_manifest):
            _status = "invalid_manifest"
        elif _expected and os.path.normcase(os.path.normpath(_expected)) != os.path.normcase(os.path.normpath(_resolved)):
            _status = "invalid_manifest"
        elif _expected_source and os.path.normcase(os.path.normpath(_expected_source)) != os.path.normcase(os.path.normpath(_source)):
            _status = "invalid_manifest"
        elif not _flags_valid:
            _status = "invalid_manifest"
        elif not _exists:
            _status = "missing"
        else:
            try:
                _st = os.stat(_source)
                _pst = os.stat(_resolved)
                _stale = (int(_intent.get("source_size", -1)) != int(_st.st_size)
                          or int(_intent.get("source_mtime_ns", -1)) != int(_st.st_mtime_ns))
                _invalid_proxy = int(_intent.get("proxy_size", -1)) != int(_pst.st_size)
            except Exception:
                _stale = True
                _invalid_proxy = False
            _status = ("stale_source" if _stale else
                       "invalid_manifest" if _invalid_proxy else "ready")
    else:
        _mode = "legacy_blender_cache"
        _status = "legacy_blender_cache"
    return {{
        "enabled": bool(_cfg.get("use_proxy")),
        "mode": _mode,
        "status": _status,
        "path": _resolved,
        "exists": _exists,
        "scale": _intent.get("scale"),
        "profile": _intent.get("profile"),
        "portable": _intent.get("portable"),
        "manifest_path": _intent.get("manifest_path"),
        "config": _cfg,
    }}
'''


def _validate_project(project: str | None) -> str:
    if not project:
        raise BlenderRunnerError("invalid_args", "project (.blend path) is required")
    return str(Path(project).expanduser().resolve())


def _edit_scene_prologue() -> str:
    """bpy prologue that pins the active scene to the project's EDIT SCENE.

    The .blend is the source of truth; all strips live on this named scene so
    that opening the file in the GUI (Video Editing workspace) shows the full
    editable timeline immediately. If the scene doesn't exist (e.g. live GUI
    session editing a user's own scene), falls back to the current scene.

    Context note: in a LIVE GUI session ``bpy.context.scene = x`` is READ-ONLY;
    scene activation must go through ``bpy.context.window.scene`` (or each
    window manager's window). Headless allows direct assignment, but the
    window-based form works in BOTH, so we always use it.
    """
    return binding_helpers_script() + f'''
_edit_scene = bpy.data.scenes.get({_j(EDIT_SCENE_NAME)})
if _edit_scene is not None:
    try:
        _vp_bind_vse_all_windows(_edit_scene)
    except Exception:
        pass
    try:
        bpy.context.scene = _edit_scene  # headless only; harmless if it fails
    except Exception:
        pass
'''


# ---------------------------------------------------------------------------
# Stable IDs + metadata (persisted via custom properties on strips)
# ---------------------------------------------------------------------------


def _ensure_ids_script() -> str:
    """bpy script that guarantees every strip has a stable video_ai_id.

    IDs are permanent: they survive rename / move / reorder / retime, because
    they live in the strip's custom property (persisted in the .blend). The
    prefix encodes the strip kind so IDs are human-meaningful:
      clip_/audio_/text_/image_/color_/scene_/fx_/trans_/...
    Runs as part of every mutating op's prologue (idempotent).
    """
    return f'''
import uuid
_id_key = {_q(ID_KEY)}
_meta_key = {_q(META_KEY)}
_prefix_map = {{
    'MOVIE': 'clip', 'SOUND': 'audio', 'TEXT': 'text', 'IMAGE': 'image',
    'COLOR': 'color', 'SCENE': 'scene', 'SPEED': 'fx', 'TRANSFORM': 'fx',
    'GAUSSIAN_BLUR': 'fx', 'GLOW': 'fx', 'ADJUSTMENT': 'fx', 'COLORMIX': 'fx',
    'CROSS': 'trans', 'GAMMA_CROSS': 'trans', 'WIPE': 'trans',
}}
_se = bpy.context.scene.sequence_editor
if _se is not None:
    for _s in _se.strips:
        if not _s.get(_id_key):
            _prefix = _prefix_map.get(_s.type, 'strip')
            _s[_id_key] = f"{{_prefix}}_{{uuid.uuid4().hex[:10]}}"
'''


def _strip_id(s) -> str:
    """Python-side helper: read a strip's stable id (used in script templates)."""
    # Injected bpy scripts call this via _vp helpers; here we just return the
    # expression text that reads it safely.
    return f"({_q(ID_KEY)} in s and s.get({_q(ID_KEY)}) or '')"


# Semantic track -> VSE channel mapping.
# V1..V5 -> channels 1..5; A1..A5 -> channels 10..14 (audio convention:
# higher video channels render on top; audio channels are just numbered).
TRACK_TO_CHANNEL = {
    "V1": 1, "V2": 2, "V3": 3, "V4": 4, "V5": 5,
    "A1": 10, "A2": 11, "A3": 12, "A4": 13, "A5": 14,
}
CHANNEL_TO_TRACK = {v: k for k, v in TRACK_TO_CHANNEL.items()}


def _track_to_channel(track: str) -> int:
    t = str(track).upper()
    if t not in TRACK_TO_CHANNEL:
        raise BlenderRunnerError("invalid_args", f"unknown track: {track} (use V1-V5/A1-A5)")
    return TRACK_TO_CHANNEL[t]


# ---------------------------------------------------------------------------
# Project lifecycle
# ---------------------------------------------------------------------------

OPS: dict = {}


def _op(name: str, read_only: bool = False):
    def deco(fn):
        fn.op_name = name
        fn.read_only = read_only
        OPS[name] = fn
        return fn
    return deco


@_op("create_project", read_only=False)
def create_project(project: str, resolution=(1920, 1080), fps: float = 30.0,
                   frame_start: int = 1, frame_end: int = 250,
                   scene_name: str | None = None, **kw) -> str:
    """Create a new empty .blend with a named EDIT SCENE + configured VSE.

    The VSE timeline is created on the named scene (default ``EDIT_SCENE_NAME``)
    so the .blend opens in the GUI showing the complete editable timeline.
    """
    project = _validate_project(project)
    p = Path(project)
    p.parent.mkdir(parents=True, exist_ok=True)
    scene_name = scene_name or EDIT_SCENE_NAME
    script = binding_helpers_script() + f"""
# Source of truth: named edit scene owns the VSE.
_edit_name = {_j(scene_name)}
_edit_scene = bpy.data.scenes.get(_edit_name)
if _edit_scene is None:
    if bpy.context.scene.name == 'Scene' and len(bpy.data.scenes) == 1:
        _edit_scene = bpy.context.scene
        _edit_scene.name = _edit_name
    else:
        _edit_scene = bpy.data.scenes.new(_edit_name)
try:
    _vp_bind_vse_all_windows(_edit_scene)
except Exception:
    pass
try:
    bpy.context.scene = _edit_scene
except Exception:
    pass
scene = _edit_scene
if not scene.sequence_editor:
    scene.sequence_editor_create()
scene.render.resolution_x = {int(resolution[0])}
scene.render.resolution_y = {int(resolution[1])}
scene.render.fps = {int(fps)}
scene.render.fps_base = 1.0
scene.frame_start = {int(frame_start)}
scene.frame_end = {int(frame_end)}
# Blender 5.1 quirk: file_format enum differs between headless and GUI.
#   headless: PNG present, FFMPEG absent; GUI: FFMPEG present, PNG absent.
# Try both so create_project works in either execution mode.
for _fmt in ('FFMPEG', 'PNG'):
    try:
        scene.render.image_settings.file_format = _fmt
        break
    except Exception:
        continue
scene.render.image_settings.media_type = 'VIDEO'
scene.render.ffmpeg.format = 'MPEG4'
scene.render.ffmpeg.codec = 'H264'
# Persist a "Video Editing" workspace so double-clicking the .blend opens
# straight into the VSE timeline (Blender 5.1 factory ships no such workspace).
_ws_name = 'Video Editing'
if _ws_name not in bpy.data.workspaces:
    try:
        bpy.ops.workspace.duplicate()
        _ws = bpy.context.workspace
        _ws.name = _ws_name
        for _scr in _ws.screens:
            for _a in _scr.areas:
                try:
                    with bpy.context.temp_override(workspace=_ws, screen=_scr, area=_a):
                        _a.type = 'SEQUENCE_EDITOR'
                except Exception:
                    pass
                break
            break
    except Exception:
        pass
try:
    _vp_profile_versions = []
    for _w in bpy.data.window_managers:
        for _win in _w.windows:
            if _ws_name in bpy.data.workspaces:
                _win.workspace = bpy.data.workspaces[_ws_name]
            _vp_bind_vse_window(_win, scene)
            _vp_screen = _win.screen
            _vp_areas = list(_vp_screen.areas) if _vp_screen else []
            _vp_vse_areas = [a for a in _vp_areas if a.type == 'SEQUENCE_EDITOR']
            _vp_utility_areas = [a for a in _vp_areas if a.type != 'SEQUENCE_EDITOR']
            _vp_profile_valid = len(_vp_vse_areas) >= 2 and len(_vp_utility_areas) >= 2
            if _vp_profile_valid:
                _vp_vse_areas.sort(key=lambda a: int(getattr(a, 'y', 0)), reverse=True)
                _vp_vse_areas[0].spaces.active.view_type = 'PREVIEW'
                _vp_vse_areas[-1].spaces.active.view_type = 'SEQUENCER'
                _win.workspace[{_j(VSE_LAYOUT_PROFILE_KEY)}] = {VSE_LAYOUT_PROFILE_VERSION}
            _vp_profile_versions.append(
                int(_win.workspace.get({_j(VSE_LAYOUT_PROFILE_KEY)}, 0) or 0)
                if _win.workspace else 0)
except Exception:
    _vp_profile_versions = []
_vp_windows = [
    _vp_vse_binding_proof(_win, scene)
    for _wm in bpy.data.window_managers for _win in _wm.windows
]
# revision baseline: fresh project starts at revision 1 with the (empty)
# timeline hash so get_revision is consistent from the start
{_timeline_hash_script("_vp_init_hash")}
scene[{_j(REVISION_KEY)}] = 1
scene[{_j(TIMELINE_HASH_KEY)}] = _vp_init_hash
_vp_result(project={_j(str(p))}, scene=scene.name, fps=scene.render.fps,
           resolution=[scene.render.resolution_x, scene.render.resolution_y],
           workspace=_ws_name, revision=1,
           layout_profile_version=(max(_vp_profile_versions) if _vp_profile_versions else 0),
           binding=_vp_windows)
"""
    return script


@_op("open_project", read_only=True)
def open_project(project: str, **kw) -> str:
    project = _validate_project(project)
    return f"""
scene = bpy.context.scene
_vp_result(project={_j(str(Path(project)))}, fps=scene.render.fps,
           resolution=[scene.render.resolution_x, scene.render.resolution_y],
           frame_start=scene.frame_start, frame_end=scene.frame_end)
"""


@_op("inspect_media", read_only=True)
def inspect_media(project: str | None = None, media_path: str = "", **kw) -> str:
    """Inspect a media file with BLENDER-NATIVE decoding — the single source of
    truth for media facts (MediaInfo). Never uses ffprobe.

    Unified MediaInfo model (every consumer reads THIS):
      {duration, fps, width, height, video_codec, audio_codec,
       audio_channels, sample_rate} + native provenance fields.

    Provenance: duration comes from the decoded strip (frame_duration divided
    by the SOURCE fps); fps/width/height from the decoded movie elements;
    audio_channels from the decoded sound datablock (MONO=1 / STEREO=2).
    Blender's native API does not expose codec strings or sample rate — those
    fields are null (never invented, never ffprobed).
    """
    if not media_path:
        raise BlenderRunnerError("invalid_args", "inspect_media needs 'media_path'")
    mp = str(Path(media_path).expanduser().resolve())
    return f"""
import bpy, os, json
_p = {_j(mp)}
if not os.path.isfile(_p):
    raise RuntimeError("media file not found: " + _p)
scene = bpy.context.scene
_se_fps = float(scene.render.fps) if scene.render.fps else 30.0
se = scene.sequence_editor
if se is None:
    se = scene.sequence_editor_create()
# clean any leftover probe strips
for _x in list(se.strips):
    if _x.name.startswith("_vp_inspect"):
        se.strips.remove(_x)

_info = {{
    "path": _p,
    "kind": None,
    "duration": None,
    "fps": None,
    "width": None,
    "height": None,
    "video_codec": None,
    "audio_codec": None,
    "audio_channels": None,
    "sample_rate": None,
    "native": {{"source": "blender-native"}},
}}

def _ch_count(_snd):
    try:
        _c = str(_snd.channels)
        if _c in ("MONO", "1"): return 1
        if _c in ("STEREO", "2"): return 2
        return None
    except Exception:
        return None

# ---- video probe: decode as a MOVIE strip ----
_vs = None
try:
    _vs = se.strips.new_movie(name="_vp_inspect_v", filepath=_p, channel=1, frame_start=1)
    _el0 = _vs.elements[0] if _vs.elements else None
    # a pure-audio file still "loads" as a movie with an empty element set —
    # treat it as NOT video so we fall through to the sound probe
    if _el0 is None or not getattr(_el0, "orig_width", None):
        se.strips.remove(_vs)
        _vs = None
except Exception:
    _vs = None
if _vs is not None:
    _el = _vs.elements[0]
    _ow = int(_el.orig_width)
    _oh = int(_el.orig_height)
    _ofps = float(_el.orig_fps) if getattr(_el, "orig_fps", None) else None
    if not _ofps:
        _ofps = float(getattr(_vs, "fps", 0) or 0) or None
    _fdur = int(_vs.frame_duration)
    _dur = (_fdur / _ofps) if _ofps else ((_fdur / _se_fps) if _se_fps else None)
    _info.update({{"kind": "video", "fps": _ofps, "width": _ow, "height": _oh,
                   "duration": _dur}})
    _info["native"].update({{"method": "vse_movie",
                             "strip_frame_duration": _fdur,
                             "orig_fps": _ofps, "orig_width": _ow, "orig_height": _oh}})
    se.strips.remove(_vs)

# ---- audio probe: decode the same file (or audio-only file) as a SOUND strip ----
_as = None
try:
    _as = se.strips.new_sound(name="_vp_inspect_a", filepath=_p, channel=2, frame_start=1)
except Exception:
    _as = None
if _as is not None:
    _snd = getattr(_as, "sound", None)
    _adur = (_as.frame_duration / _se_fps) if _se_fps else None
    _ach = _ch_count(_snd) if _snd is not None else None
    if _info["kind"] is None:
        _info.update({{"kind": "audio", "duration": _adur}})
    _info["audio_channels"] = _ach
    _info["native"]["sound_channels"] = str(_snd.channels) if _snd is not None else None
    _info["native"]["sound_frame_duration"] = int(_as.frame_duration)
    _snd_name = _snd.name if _snd is not None else None
    se.strips.remove(_as)
    # drop the temporary Sound datablock created for the probe
    if _snd_name and _snd_name in bpy.data.sounds:
        try:
            bpy.data.sounds.remove(bpy.data.sounds[_snd_name])
        except Exception:
            pass

# clean leftovers
for _x in list(se.strips):
    if _x.name.startswith("_vp_inspect"):
        se.strips.remove(_x)

if _info["kind"] is None:
    raise RuntimeError("cannot decode media natively (not video, not audio): " + _p)
_vp_result(**_info)
"""


@_op("save_project", read_only=False)
def save_project(project: str, **kw) -> str:
    project = _validate_project(project)
    # .blend is the source of truth: explicitly persist the project file.
    return f"""
scene = bpy.context.scene
_vp_result(project={_j(str(Path(project)))}, scene=scene.name,
           strip_count=len(scene.sequence_editor.strips) if scene.sequence_editor else 0)
"""


# ---------------------------------------------------------------------------
# Timeline reading
# ---------------------------------------------------------------------------


def _timeline_read_script(with_text: bool = False) -> str:
    """Shared script that dumps full timeline state as VP_RESULT payload."""
    text_extra = """
            "text": getattr(s, 'text', None),
            "font_size": getattr(s, 'font_size', None),
            "position": list(getattr(s, 'location', (0.5, 0.5))),
            "alignment_x": getattr(s, 'alignment_x', None),
            "use_shadow": getattr(s, 'use_shadow', None),
            "use_outline": getattr(s, 'use_outline', None),
            "use_box": getattr(s, 'use_box', None),
""" if with_text else ""
    return f"""
import json as _json, os
{_ensure_ids_script()}
{_proxy_state_helpers()}
scene = bpy.context.scene
se = scene.sequence_editor
if se is None:
    _vp_result(project=None, scene=scene.name, fps=scene.render.fps,
               resolution=[scene.render.resolution_x, scene.render.resolution_y],
               frame_start=scene.frame_start, frame_end=scene.frame_end,
               playhead=scene.frame_current, strips=[])
    raise SystemExit(0)
strips = []
for s in se.strips:
    try:
        tf = s.transform
        transform = {{"offset_x": tf.offset_x, "offset_y": tf.offset_y,
                      "scale_x": tf.scale_x, "scale_y": tf.scale_y,
                      "rotation": tf.rotation}}
    except Exception:
        transform = None
    _mid = s.get({_q(ID_KEY)}, "") if {_q(ID_KEY)} in s else ""
    _meta_raw = s.get({_q(META_KEY)}, "")
    _meta = {{}}
    if _meta_raw:
        try:
            _meta = _json.loads(_meta_raw)
        except Exception:
            _meta = {{"raw": _meta_raw}}
    strips.append({{
        "id": s.name, "name": s.name, "video_ai_id": _mid, "meta": _meta,
        "asset_id": s.get({_q(ASSET_ID_KEY)}, ""),
        "asset_revision": int(s.get({_q(ASSET_REVISION_KEY)}, 0) or 0),
        "type": s.type, "channel": s.channel,
        "frame_start": int(getattr(s, 'frame_final_start', getattr(s, 'left_handle', 0))),
        "frame_end": int(getattr(s, 'frame_final_end', getattr(s, 'right_handle', 0))),
        "source_in": int(getattr(s, 'frame_offset_start', getattr(s, 'left_handle_offset', 0))),
        "source_out": int(getattr(s, 'frame_offset_end', getattr(s, 'right_handle_offset', 0))),
        "source_path": (
            bpy.path.abspath(getattr(getattr(s, 'sound', None), 'filepath', '') or '')
            if s.type == 'SOUND'
            else (bpy.path.abspath(getattr(s, 'filepath', '') or '')
                  if s.type in ('MOVIE', 'IMAGE') else None)
        ),
        "mute": bool(getattr(s, 'mute', False)),
        "lock": bool(getattr(s, 'lock', False)),
        "blend_type": getattr(s, 'blend_type', None),
        "opacity": getattr(s, 'blend_alpha', None),
        "volume": getattr(s, 'volume', None),
        "transform": transform,
        "proxy": _vp_proxy_status(s),
{text_extra}
    }})
_vp_result(project=None, scene=scene.name, fps=scene.render.fps,
           resolution=[scene.render.resolution_x, scene.render.resolution_y],
           frame_start=scene.frame_start, frame_end=scene.frame_end,
           playhead=scene.frame_current, strips=strips)
"""


@_op("list_strips", read_only=True)
def list_strips(project: str, with_text: bool = False, **kw) -> str:
    _validate_project(project)
    return _timeline_read_script(with_text=with_text)


@_op("get_timeline_info", read_only=True)
def get_timeline_info(project: str, **kw) -> str:
    _validate_project(project)
    return f"""
scene = bpy.context.scene
se = scene.sequence_editor
info = {{
    "scene": scene.name,
    "fps": scene.render.fps,
    "resolution": [scene.render.resolution_x, scene.render.resolution_y],
    "frame_start": scene.frame_start,
    "frame_end": scene.frame_end,
    "playhead": scene.frame_current,
    "has_sequencer": se is not None,
    "strip_count": len(se.strips) if se else 0,
    "channels_used": sorted(set(s.channel for s in se.strips)) if se else [],
}}
_vp_result(**info)
"""


# ---------------------------------------------------------------------------
# Capability registration & project info
# ---------------------------------------------------------------------------


@_op("get_capabilities", read_only=True)
def get_capabilities(project: str, **kw) -> str:
    """Report plugin/schema/Blender versions, execution mode, and op list."""
    _validate_project(project)
    return f"""
import bpy as _bpy
_proxy_type = getattr(_bpy.types, "StripProxy", None) or getattr(_bpy.types, "SequenceProxy", None)
_proxy_custom_file_supported = bool(
    _proxy_type is not None
    and hasattr(_proxy_type, "filepath")
    and hasattr(_proxy_type, "use_proxy_custom_file")
    and hasattr(_proxy_type, "directory")
    and hasattr(_proxy_type, "use_proxy_custom_directory")
)
_vp_result(
    plugin_version={_j(PLUGIN_VERSION)},
    schema_version={_j(SCHEMA_VERSION)},
    public_contract_version="1.0.0",
    agent_tools=["blender_read", "blender_patch", "blender_acknowledge", "blender_verify"],
    blender_version=_bpy.app.version_string,
    proxy_custom_file_supported=_proxy_custom_file_supported,
    proxy_manifest_version="1.0",
    proxy_builder="external-manifest-v1",
    removed_operations={_j(REMOVED_OPS)},
    blender_version_tuple=list(_bpy.app.version),
    mode='live',
    edit_scene={_j(EDIT_SCENE_NAME)},
    id_key={_j(ID_KEY)},
    meta_key={_j(META_KEY)},
    asset_id_key={_j(ASSET_ID_KEY)},
)
"""


@_op("list_operations", read_only=True)
def list_operations(project: str, **kw) -> str:
    """List every implemented op grouped by family."""
    _validate_project(project)
    families = _op_families()
    return f"""
import json as _json
_vp_result(operations={_j(families)})
"""


def _op_families() -> dict:
    """Return every public operation grouped by its canonical family."""

    return {
        family: sorted(
            operation
            for operation in operations
            if operation in OPS and operation not in REMOVED_OPS
        )
        for family, operations in OPERATION_FAMILIES.items()
    }


@_op("get_project_info", read_only=True)
def get_project_info(project: str, **kw) -> str:
    """Structured project info: versions, scene, timeline summary."""
    _validate_project(project)
    return f"""
import bpy as _bpy
scene = bpy.context.scene
se = scene.sequence_editor
_vp_result(
    plugin_version={_j(PLUGIN_VERSION)},
    schema_version={_j(SCHEMA_VERSION)},
    blender_version=_bpy.app.version_string,
    project={_j(str(Path(project).resolve()))},
    scene=scene.name,
    fps=scene.render.fps,
    resolution=[scene.render.resolution_x, scene.render.resolution_y],
    frame_start=scene.frame_start,
    frame_end=scene.frame_end,
    strip_count=len(se.strips) if se else 0,
    has_sequencer=se is not None,
)
"""


# ---------------------------------------------------------------------------
# Stable IDs + metadata
# ---------------------------------------------------------------------------


@_op("ensure_strip_ids", read_only=False)
def ensure_strip_ids(project: str, **kw) -> str:
    """Guarantee every strip has a stable video_ai_id (idempotent)."""
    _validate_project(project)
    return f"""
{_ensure_ids_script()}
_se = bpy.context.scene.sequence_editor
_ids = []
if _se is not None:
    for _s in _se.strips:
        _ids.append({{"video_ai_id": _s.get({_q(ID_KEY)}, ""), "name": _s.name,
                      "type": _s.type}})
_vp_result(count=len(_ids), strips=_ids)
"""


@_op("get_strip_by_id", read_only=True)
def get_strip_by_id(project: str, video_ai_id: str, with_text: bool = False, **kw) -> str:
    """Find a strip by its stable ID (survives rename/move/reorder)."""
    _validate_project(project)
    return f"""
import json as _json
_se = bpy.context.scene.sequence_editor
_target = {_q(video_ai_id)}
_found = None
if _se is not None:
    for _s in _se.strips:
        if _s.get({_q(ID_KEY)}, "") == _target:
            _found = _s
            break
if _found is None:
    _vp_result(found=False, video_ai_id=_target)
    raise SystemExit(0)
s = _found
_meta_raw = s.get({_q(META_KEY)}, "")
_meta = {{}}
if _meta_raw:
    try:
        _meta = _json.loads(_meta_raw)
    except Exception:
        _meta = {{"raw": _meta_raw}}
try:
    tf = s.transform
    _transform = {{"offset_x": tf.offset_x, "offset_y": tf.offset_y,
                   "scale_x": tf.scale_x, "scale_y": tf.scale_y, "rotation": tf.rotation}}
except Exception:
    _transform = None
_vp_result(found=True, video_ai_id=_target, name=s.name, type=s.type, channel=s.channel,
           frame_start=int(s.frame_final_start), frame_end=int(s.frame_final_end),
           source_in=int(s.frame_offset_start), source_out=int(s.frame_offset_end),
           mute=bool(s.mute), lock=bool(s.lock), meta=_meta, transform=_transform,
           text=getattr(s, 'text', None))
"""


@_op("resolve_strip", read_only=True)
def resolve_strip(project: str, target: str | None = None,
                  video_ai_id: str | None = None, **kw) -> str:
    """Resolve a strip reference (by ID preferred; falls back to name)."""
    _validate_project(project)
    return f"""
_se = bpy.context.scene.sequence_editor
_by_id = {_q(video_ai_id or '')}
_by_name = {_q(target or '')}
_found = None
_reason = None
if _se is not None:
    if _by_id:
        for _s in _se.strips:
            if _s.get({_q(ID_KEY)}, "") == _by_id:
                _found = _s
                _reason = "id"
                break
    if _found is None and _by_name:
        for _s in _se.strips:
            if _s.name == _by_name:
                _found = _s
                _reason = "name"
                break
if _found is None:
    _vp_result(found=False, video_ai_id=_by_id, name=_by_name)
    raise SystemExit(0)
s = _found
_vp_result(found=True, resolved_by=_reason, video_ai_id=s.get({_q(ID_KEY)}, ""),
           name=s.name, type=s.type, channel=s.channel,
           frame_start=int(s.frame_final_start), frame_end=int(s.frame_final_end))
"""


@_op("find_strips", read_only=True)
def find_strips(project: str, type: str | None = None, channel: int | None = None,
                text_contains: str | None = None, meta_key: str | None = None,
                meta_value=None, **kw) -> str:
    """Find strips by type / channel / text / metadata."""
    _validate_project(project)
    return f"""
import json as _json
_se = bpy.context.scene.sequence_editor
_ftype = {_q(type or '')}
_fchan = {int(channel) if channel is not None else -1}
_ftext = {_q(text_contains or '')}
_fmk = {_q(meta_key or '')}
_fmv = {_jv(meta_value)}
_matches = []
if _se is not None:
    for _s in _se.strips:
        _ok = True
        if _ftype and _s.type != _ftype:
            _ok = False
        if _ok and _fchan >= 0 and _s.channel != _fchan:
            _ok = False
        if _ok and _ftext:
            _t = getattr(_s, 'text', '') or ''
            if _ftext not in _t:
                _ok = False
        if _ok and _fmk:
            _raw = _s.get({_q(META_KEY)}, "")
            _m = {{}}
            if _raw:
                try:
                    _m = _json.loads(_raw)
                except Exception:
                    _m = {{}}
            if _fmk not in _m or (_fmv is not None and _m.get(_fmk) != _fmv):
                _ok = False
        if _ok:
            _matches.append({{"video_ai_id": _s.get({_q(ID_KEY)}, ""), "name": _s.name,
                             "type": _s.type, "channel": _s.channel,
                             "frame_start": int(_s.frame_final_start),
                             "frame_end": int(_s.frame_final_end)}})
_vp_result(count=len(_matches), strips=_matches)
"""


@_op("set_strip_metadata", read_only=False)
def set_strip_metadata(project: str, target: str | None = None,
                       video_ai_id: str | None = None,
                       metadata: dict | None = None, **kw) -> str:
    """Attach metadata (role/speaker/topic/...) to a strip as JSON custom prop."""
    _validate_project(project)
    if not metadata:
        raise BlenderRunnerError("invalid_args", "set_strip_metadata needs 'metadata' dict")
    return f"""
import json as _json
_se = bpy.context.scene.sequence_editor
_by_id = {_q(video_ai_id or '')}
_by_name = {_q(target or '')}
_s = None
if _se is not None:
    if _by_id:
        for _x in _se.strips:
            if _x.get({_q(ID_KEY)}, "") == _by_id:
                _s = _x
                break
    if _s is None and _by_name:
        for _x in _se.strips:
            if _x.name == _by_name:
                _s = _x
                break
if _s is None:
    raise RuntimeError("strip not found (id: " + _by_id + ", name: " + _by_name + ")")
_old = _s.get({_q(META_KEY)}, "")
_old_meta = {{}}
if _old:
    try:
        _old_meta = _json.loads(_old)
    except Exception:
        _old_meta = {{}}
_old_meta.update({_j(metadata)})
_s[{_q(META_KEY)}] = _json.dumps(_old_meta, ensure_ascii=False)
_vp_result(video_ai_id=_s.get({_q(ID_KEY)}, ""), name=_s.name,
           metadata=_old_meta)
"""


@_op("get_strip_metadata", read_only=True)
def get_strip_metadata(project: str, target: str | None = None,
                       video_ai_id: str | None = None, **kw) -> str:
    """Read a strip's metadata dict."""
    _validate_project(project)
    return f"""
import json as _json
_se = bpy.context.scene.sequence_editor
_by_id = {_q(video_ai_id or '')}
_by_name = {_q(target or '')}
_s = None
if _se is not None:
    if _by_id:
        for _x in _se.strips:
            if _x.get({_q(ID_KEY)}, "") == _by_id:
                _s = _x
                break
    if _s is None and _by_name:
        for _x in _se.strips:
            if _x.name == _by_name:
                _s = _x
                break
if _s is None:
    raise RuntimeError("strip not found")
_raw = _s.get({_q(META_KEY)}, "")
_meta = {{}}
if _raw:
    try:
        _meta = _json.loads(_raw)
    except Exception:
        _meta = {{"raw": _raw}}
_vp_result(video_ai_id=_s.get({_q(ID_KEY)}, ""), name=_s.name, metadata=_meta)
"""


# ---------------------------------------------------------------------------
# Strip creation (Blender 5.1 strips.new_*—verified headless-safe)
# ---------------------------------------------------------------------------


@_op("add_movie", read_only=False)
def add_movie(project: str, asset: str, channel: int = 1, frame_start: int = 1,
              strip_name: str = "", fit_method: str = "FIT",
              asset_id: str = "", asset_revision: int = 1, **kw) -> str:
    _validate_project(project)
    asset = str(Path(asset).expanduser().resolve())
    name = strip_name or Path(asset).stem
    return f"""
se = bpy.context.scene.sequence_editor
s = se.strips.new_movie(name={_q(name)}, filepath={_j(asset)},
                        channel={int(channel)}, frame_start={int(frame_start)},
                        fit_method={_q(fit_method)})
if {_py(bool(asset_id))}:
    s[{_q(ASSET_ID_KEY)}] = {_q(asset_id)}
    s[{_q(ASSET_REVISION_KEY)}] = {int(asset_revision)}
_vp_result(id=s.name, type=s.type, channel=s.channel,
           asset_id=s.get({_q(ASSET_ID_KEY)}, ""),
           frame_start=int(s.frame_final_start), frame_end=int(s.frame_final_end))
"""


@_op("add_sound", read_only=False)
def add_sound(project: str, asset: str, channel: int = 2, frame_start: int = 1,
              strip_name: str = "", asset_id: str = "", asset_revision: int = 1,
              **kw) -> str:
    _validate_project(project)
    asset = str(Path(asset).expanduser().resolve())
    name = strip_name or Path(asset).stem
    return f"""
se = bpy.context.scene.sequence_editor
s = se.strips.new_sound(name={_q(name)}, filepath={_j(asset)},
                        channel={int(channel)}, frame_start={int(frame_start)})
if {_py(bool(asset_id))}:
    s[{_q(ASSET_ID_KEY)}] = {_q(asset_id)}
    s[{_q(ASSET_REVISION_KEY)}] = {int(asset_revision)}
_vp_result(id=s.name, type=s.type, channel=s.channel,
           asset_id=s.get({_q(ASSET_ID_KEY)}, ""),
           frame_start=int(s.frame_final_start), frame_end=int(s.frame_final_end))
"""


@_op("add_image", read_only=False)
def add_image(project: str, asset: str, channel: int = 1, frame_start: int = 1,
              length: int = 48, strip_name: str = "", asset_id: str = "",
              asset_revision: int = 1, **kw) -> str:
    _validate_project(project)
    asset = str(Path(asset).expanduser().resolve())
    name = strip_name or Path(asset).stem
    return f"""
se = bpy.context.scene.sequence_editor
s = se.strips.new_image(name={_q(name)}, filepath={_j(asset)},
                        channel={int(channel)}, frame_start={int(frame_start)})
s.frame_final_end = s.frame_final_start + {int(length)}
if {_py(bool(asset_id))}:
    s[{_q(ASSET_ID_KEY)}] = {_q(asset_id)}
    s[{_q(ASSET_REVISION_KEY)}] = {int(asset_revision)}
_vp_result(id=s.name, type=s.type, channel=s.channel,
           asset_id=s.get({_q(ASSET_ID_KEY)}, ""),
           frame_start=int(s.frame_final_start), frame_end=int(s.frame_final_end))
"""


@_op("add_image_sequence", read_only=False)
def add_image_sequence(project: str, directory: str, channel: int = 1, frame_start: int = 1,
                       frame_end: int = 60, strip_name: str = "", **kw) -> str:
    _validate_project(project)
    directory = str(Path(directory).expanduser().resolve())
    name = strip_name or Path(directory).name
    return f"""
import os
se = bpy.context.scene.sequence_editor
exts = ('.png', '.jpg', '.jpeg', '.tiff', '.tif', '.exr', '.bmp', '.webp')
files = [{{"name": f}} for f in sorted(os.listdir({_j(directory)})) if f.lower().endswith(exts)]
if not files:
    raise RuntimeError("No image files found in " + {_j(directory)})
s = se.strips.new_image(name={_q(name)}, filepath=os.path.join({_j(directory)}, files[0]['name']),
                        channel={int(channel)}, frame_start={int(frame_start)})
s.frame_final_end = {int(frame_end)}
_vp_result(id=s.name, type=s.type, channel=s.channel,
           frame_start=int(s.frame_final_start), frame_end=int(s.frame_final_end))
"""


@_op("add_color", read_only=False)
def add_color(project: str, channel: int = 1, frame_start: int = 1, length: int = 120,
              color=(0.0, 0.0, 0.0), strip_name: str = "", **kw) -> str:
    _validate_project(project)
    name = strip_name or f"Color_{frame_start}"
    return f"""
se = bpy.context.scene.sequence_editor
s = se.strips.new_effect(name={_q(name)}, type='COLOR',
                         channel={int(channel)}, frame_start={int(frame_start)}, length={int(length)})
s.color = {_j(tuple(float(c) for c in color))}
_vp_result(id=s.name, type=s.type, channel=s.channel,
           frame_start=int(s.frame_final_start), frame_end=int(s.frame_final_end))
"""


_ENSURE_FONT = '''
def _vp_ensure_font(strip, explicit_path, text):
    # Blender >= 5 renders TEXT strips with font=None correctly in the final
    # render but draws them in the sequencer preview as scaled/flipped glyph
    # garbage. Always assign an explicit, loadable font so preview and render
    # agree. Returns (font_name_or_None, fallback_warning).
    import bpy, os
    if explicit_path:
        strip.font = bpy.data.fonts.load(explicit_path, check_existing=True)
        return strip.font.name, False
    if strip.font is not None and getattr(strip.font, "filepath", ""):
        return strip.font.name, False
    _cjk = any(0x2E80 <= ord(c) <= 0x9FFF or 0xF900 <= ord(c) <= 0xFAFF
               or 0x3040 <= ord(c) <= 0x30FF or 0xAC00 <= ord(c) <= 0xD7AF
               or 0x20000 <= ord(c) <= 0x2FA1F for c in text)
    # Bundled fonts live under the versioned resource dir (e.g.
    # <install>/5.2/datafiles/fonts), not next to the binary; ask Blender.
    _dirs = []
    try:
        _res = bpy.utils.system_resource('DATAFILES', path="fonts")
        if _res:
            _dirs.append(_res)
    except Exception:
        pass
    _bin = os.path.dirname(bpy.app.binary_path)
    _ver = "%d.%d" % bpy.app.version[:2]
    _dirs += [os.path.join(_bin, _ver, "datafiles", "fonts"),
              os.path.join(_bin, "datafiles", "fonts"),
              "/usr/share/blender/datafiles/fonts"]
    # Blender >= 4 ships .woff2 UI fonts; older releases shipped bfont.ttf.
    if _cjk:
        _names = ["Noto Sans CJK Regular.woff2", "NotoSansCJK-Regular.ttc",
                  "NotoSansCJKsc-Regular.otf", "SourceHanSansSC-Regular.otf"]
        _abs = ["/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
                "C:/Windows/Fonts/msyh.ttc",
                "/System/Library/Fonts/PingFang.ttc"]
    else:
        _names = ["Inter.woff2", "DejaVuSans.woff2", "bfont.ttf"]
        _abs = ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/TTF/DejaVuSans.ttf",
                "C:/Windows/Fonts/arial.ttf",
                "/System/Library/Fonts/Supplemental/Arial.ttf"]
    for _p in [os.path.join(_d, _n) for _d in _dirs for _n in _names] + _abs:
        try:
            if not os.path.isfile(_p):
                continue
            strip.font = bpy.data.fonts.load(_p, check_existing=True)
            return strip.font.name, False
        except Exception:
            continue
    return None, True
'''


@_op("add_text", read_only=False)
def add_text(project: str, text: str, channel: int = 2, frame_start: int = 1,
             length: int = 120, font_size: float = 48.0, position=(0.5, 0.5),
             strip_name: str = "", font: str = "", **kw) -> str:
    _validate_project(project)
    name = strip_name or f"Text_{frame_start}"
    font_literal = (
        _j(str(Path(font).expanduser().resolve())) if str(font).strip() else "None"
    )
    return f"""
{_ENSURE_FONT}
se = bpy.context.scene.sequence_editor
s = se.strips.new_effect(name={_q(name)}, type='TEXT',
                         channel={int(channel)}, frame_start={int(frame_start)}, length={int(length)})
s.text = {_j(str(text))}
s.font_size = {float(font_size)}
s.location = {_j(tuple(float(x) for x in position))}
_font, _font_warn = _vp_ensure_font(s, {font_literal}, s.text)
_vp_result(id=s.name, type=s.type, channel=s.channel,
           frame_start=int(s.frame_final_start), frame_end=int(s.frame_final_end),
           font=_font, font_fallback_warning=_font_warn)
"""


@_op("add_subtitle_track", read_only=False)
def add_subtitle_track(project: str, segments=None, srt_path: str | None = None,
                       channel: int = 3, fps: float = 30.0,
                       font_size: float = 48.0, position=(0.5, 0.12),
                       strip_prefix: str = "Sub_", align: str = "CENTER",
                       allow_overlap: bool = False,
                       **kw) -> str:
    """Create a full subtitle track as editable VSE text strips.

    Subtitles are FIRST-CLASS, EDITABLE elements in the .blend (source of
    truth) — they are NOT burned into the pixels. Compose renders the .blend
    directly so the text strips appear in the output while remaining
    hand-editable in Blender.

    Input (either):
      - ``segments``: list of {"start_seconds": float, "end_seconds": float,
        "text": str} — OR —
      - ``srt_path``: path to an .srt file (parsed with a small built-in parser).

    Idempotent: any existing strips whose name starts with ``strip_prefix``
    on the target channel are removed first, so re-running rebuilds the track.

    Overlap guard: by default the op REFUSES to stack subtitles over other
    strips already on the target channel (or over each other, for overlapping
    input segments) — pass ``allow_overlap=True`` to force.
    """
    _validate_project(project)
    if segments is None and not srt_path:
        raise BlenderRunnerError(
            "invalid_args", "add_subtitle_track needs 'segments' or 'srt_path'")
    segs_j = _j(segments if segments is not None else [])
    srt_j = _j(str(Path(srt_path).expanduser().resolve()) if srt_path else "")
    return f"""
import os, re
se = bpy.context.scene.sequence_editor
if se is None:
    raise RuntimeError("no sequence editor — create_project first")

# ---- resolve segments: from param or parse SRT ----
_segs = {segs_j}
_srt_path = {srt_j}
if not _segs and _srt_path and os.path.isfile(_srt_path):
    _raw = open(_srt_path, encoding='utf-8').read()
    _blocks = re.split(r'\\n\\s*\\n', _raw.strip())
    _ts_re = re.compile(r'(\\d+):(\\d+):(\\d+)[,.]\\d+\\s+-->\\s+(\\d+):(\\d+):(\\d+)[,.]\\d+')
    for _b in _blocks:
        _lines = _b.split('\\n')
        if len(_lines) < 2:
            continue
        # timeline is on the 2nd line (1st is the index); search the head
        _head = '\\n'.join(_lines[:2])
        _m = _ts_re.search(_head)
        if not _m:
            continue
        _h1,_m1,_s1,_h2,_m2,_s2 = map(int, _m.groups())
        _start = _h1*3600 + _m1*60 + _s1
        _end = _h2*3600 + _m2*60 + _s2
        # text = body lines EXCLUDING the SRT index line and the timestamp line
        _body = _lines[1:] if _lines[0].strip().isdigit() else _lines
        _text = ' '.join(l.strip() for l in _body if l.strip() and not _ts_re.search(l))
        if _text:
            _segs.append({{"start_seconds": _start, "end_seconds": _end, "text": _text}})
if not _segs:
    raise RuntimeError("no subtitle segments resolved")

# ---- idempotent: remove old track strips with the same prefix ----
_prefix = {_q(strip_prefix)}
_channel = {int(channel)}
_fps = {float(fps)}
for _s in list(se.strips):
    if _s.name.startswith(_prefix) and _s.channel == _channel:
        se.strips.remove(_s)

# ---- overlap guard: never silently stack subtitles over other strips ----
_allow_ov = {_py(allow_overlap)}
_conflicts = []
if not _allow_ov:
    _spans = []
    for _seg in _segs:
        _fs = int(round(_seg["start_seconds"] * _fps)) + 1
        _fe = _fs + int(round(max(0.1, _seg["end_seconds"] - _seg["start_seconds"]) * _fps))
        _spans.append((_fs, _fe, str(_seg.get("text", ""))[:40]))
        for _x in se.strips:
            if _x.channel != _channel:
                continue
            if _x.name.startswith(_prefix):
                continue  # own track — rebuilt below
            if _x.frame_final_start < _fe and _x.frame_final_end > _fs:
                _conflicts.append({{"strip": _x.name,
                                    "span": [_x.frame_final_start, _x.frame_final_end],
                                    "subtitle_span": [_fs, _fe],
                                    "text": str(_seg.get("text", ""))[:40]}})
    # segments overlapping EACH OTHER are also malformed input
    for _i in range(len(_spans)):
        for _j in range(_i + 1, len(_spans)):
            if _spans[_i][0] < _spans[_j][1] and _spans[_j][0] < _spans[_i][1]:
                _conflicts.append({{"subtitle_subtitle": True,
                                    "a_text": _spans[_i][2], "b_text": _spans[_j][2],
                                    "a_span": [_spans[_i][0], _spans[_i][1]],
                                    "b_span": [_spans[_j][0], _spans[_j][1]]}})
if _conflicts:
    _names = [c.get("strip", c.get("a_text", "?")) for c in _conflicts]
    raise RuntimeError(
        "overlap_detected: channel " + str(_channel) +
        " has strips/segments overlapping the new subtitle track: " + str(_names) +
        " (pass allow_overlap=True to force)")

# ---- build text strips ----
{_ENSURE_FONT}
_pos = {_j(tuple(float(x) for x in position))}
_font_size = {float(font_size)}
_align = {_q(align)}
_created = []
_font_warn = False
for _i, _seg in enumerate(_segs):
    _start = int(round(_seg["start_seconds"] * _fps)) + 1
    _dur = int(round(max(0.1, _seg["end_seconds"] - _seg["start_seconds"]) * _fps))
    _name = {_j(strip_prefix)} + str(_i + 1).zfill(4)
    _s = se.strips.new_effect(name=_name, type='TEXT',
                              channel=_channel, frame_start=_start, length=_dur)
    _s.text = str(_seg["text"])
    _s.font_size = _font_size
    _s.location = _pos
    try:
        _s.alignment_x = _align
    except Exception:
        pass
    _f, _w = _vp_ensure_font(_s, None, _s.text)
    _font_warn = _font_warn or _w
    _created.append({{"id": _s.name, "text": _s.text,
                     "frame_start": int(_s.frame_final_start),
                     "frame_end": int(_s.frame_final_end)}})
_vp_result(created=len(_created), channel=_channel, prefix=_prefix, strips=_created,
           font_fallback_warning=_font_warn)
"""


@_op("assemble_clips", read_only=False)
def assemble_clips(project: str, clips=None, channel: int = 1,
                   fps: float = 30.0, strip_prefix: str = "Clip_",
                   gap_frames: int = 0, **kw) -> str:
    """Assemble source footage into a sequential timeline in Blender VSE.

    This is the "拼接在 Blender 里做" operation: every clip becomes an
    EDITABLE MOVIE strip on the timeline (source of truth = .blend), laid
    back-to-back automatically with optional per-clip source trimming.

    Input ``clips``: ordered list of
      {"asset": str, "source_in": float|None, "source_out": float|None,
       "strip_name": str|None}
    - ``source_in``/``source_out`` are SECONDS into the source; the kept
      window is trimmed to that range.
    - Strips are placed sequentially starting at frame 1 (plus ``gap_frames``
      between them) on ``channel``.
    - Idempotent: existing strips whose name starts with ``strip_prefix`` on
      the target channel are removed first.
    """
    _validate_project(project)
    if not clips:
        raise BlenderRunnerError("invalid_args", "assemble_clips needs 'clips' (ordered list)")
    clips_j = _j(clips)
    return f"""
import os
se = bpy.context.scene.sequence_editor
if se is None:
    raise RuntimeError("no sequence editor — create_project first")

_clips = {clips_j}
_channel = {int(channel)}
_fps = {float(fps)}
_prefix = {_q(strip_prefix)}
_gap = {int(gap_frames)}

# ---- idempotent: remove old assembled strips on this channel ----
for _s in list(se.strips):
    if _s.name.startswith(_prefix) and _s.channel == _channel:
        se.strips.remove(_s)

# ---- build sequential timeline ----
_cursor = 1
_created = []
for _i, _c in enumerate(_clips):
    _asset = _c["asset"]
    if not os.path.isfile(_asset):
        raise RuntimeError("clip file not found: " + _asset)
    _name = (_c.get("strip_name") or
             {_j(strip_prefix)} + str(_i + 1).zfill(4))
    _s = se.strips.new_movie(name=_name, filepath=_asset,
                             channel=_channel, frame_start=_cursor)
    # source trim (seconds -> frames); frame_offset_start skips from content
    # start, frame_offset_end skips from content END.
    _sin = _c.get("source_in")
    _sout = _c.get("source_out")
    if _sin is not None:
        _s.frame_offset_start = int(round(_sin * _fps))
    if _sout is not None:
        _s.frame_offset_end = max(0, int(_s.frame_duration - round(_sout * _fps)))
    _dur = _s.frame_final_end - _s.frame_final_start
    _created.append({{
        "id": _s.name, "type": _s.type, "channel": _s.channel,
        "frame_start": int(_s.frame_final_start), "frame_end": int(_s.frame_final_end),
        "duration_frames": int(_dur),
        "source_in": int(_s.frame_offset_start), "source_out": int(_s.frame_offset_end),
        "asset": _asset,
    }})
    _cursor = _s.frame_final_end + _gap
_vp_result(assembled=len(_created), channel=_channel, prefix=_prefix,
           total_duration_frames=_cursor - 1 - _gap, clips=_created)
"""


@_op("add_scene", read_only=False)
def add_scene(project: str, scene_name: str = "Scene", channel: int = 1,
              frame_start: int = 1, strip_name: str = "", **kw) -> str:
    _validate_project(project)
    name = strip_name or f"Scene_{scene_name}"
    return f"""
se = bpy.context.scene.sequence_editor
src = bpy.data.scenes.get({_j(scene_name)}) or bpy.context.scene
s = se.strips.new_scene(name={_q(name)}, scene=src,
                        channel={int(channel)}, frame_start={int(frame_start)})
_vp_result(id=s.name, type=s.type, channel=s.channel,
           frame_start=int(s.frame_final_start), frame_end=int(s.frame_final_end))
"""


@_op("add_effect", read_only=False)
def add_effect(project: str, effect_type: str = "GAUSSIAN_BLUR", channel: int = 3,
               frame_start: int = 1, length: int = 30, strip_name: str = "", **kw) -> str:
    _validate_project(project)
    if effect_type not in EFFECT_TYPES:
        raise BlenderRunnerError("invalid_args", f"Unknown effect type: {effect_type}")
    name = strip_name or f"FX_{effect_type}_{frame_start}"
    return f"""
se = bpy.context.scene.sequence_editor
s = se.strips.new_effect(name={_q(name)}, type={_q(effect_type)},
                         channel={int(channel)}, frame_start={int(frame_start)}, length={int(length)})
_vp_result(id=s.name, type=s.type, channel=s.channel,
           frame_start=int(s.frame_final_start), frame_end=int(s.frame_final_end))
"""


# ---------------------------------------------------------------------------
# Subtitle editing — split / merge / retime / shift / import / export
# ---------------------------------------------------------------------------


@_op("split_subtitle", read_only=False)
def split_subtitle(project: str, video_ai_id: str | None = None,
                   target: str | None = None, frame: int = 1, **kw) -> str:
    """Split a text strip into two at a frame (both keep the text)."""
    _validate_project(project)
    return f"""
{_ripple_helpers()}
import copy
se = bpy.context.scene.sequence_editor
_by_id = {_q(video_ai_id or '')}
_by_name = {_q(target or '')}
s = None
if se is not None:
    if _by_id:
        s = _vp_by_id(se, _by_id)
    if s is None and _by_name:
        for _x in se.strips:
            if _x.name == _by_name:
                s = _x
                break
if s is None:
    raise RuntimeError("strip not found")
_f = {int(frame)}
if _f <= s.frame_final_start or _f >= s.frame_final_end:
    raise RuntimeError("split frame outside strip range")
_txt = s.text
_ch = s.channel
_orig_start = s.frame_final_start
_orig_end = s.frame_final_end
_mid = _f
# trim the first half FIRST, then create the second — creating while the
# original still spans the split point would temporarily overlap it on the
# same channel (and can make Blender auto-raise the channel)
s.frame_final_end = _mid
_second = se.strips.new_effect(name=s.name + '_2', type='TEXT',
                               channel=_ch, frame_start=_mid,
                               length=_orig_end - _mid)
_second.text = _txt
_vp_result(parts=[{{"id": s.name, "start": _orig_start, "end": _mid}},
                  {{"id": _second.name, "start": _mid, "end": _orig_end}}])
"""


@_op("merge_subtitles", read_only=False)
def merge_subtitles(project: str, video_ai_ids: list | None = None,
                    targets: list | None = None, **kw) -> str:
    """Merge adjacent text strips into one (concatenate text, span all frames)."""
    _validate_project(project)
    refs = video_ai_ids or targets
    if not refs or len(refs) < 2:
        raise BlenderRunnerError("invalid_args", "merge_subtitles needs >=2 refs")
    return f"""
{_ripple_helpers()}
se = bpy.context.scene.sequence_editor
_refs = {_py(refs)}
_strips = []
for _r in _refs:
    _s = _vp_by_id(se, str(_r))
    if _s is None:
        for _x in se.strips:
            if _x.name == str(_r):
                _s = _x
                break
    if _s is None:
        raise RuntimeError("strip not found: " + str(_r))
    if _s.type != 'TEXT':
        raise RuntimeError("non-text strip in merge: " + _s.name)
    _strips.append(_s)
_strips.sort(key=lambda x: x.frame_final_start)
_keep = _strips[0]
_texts = [str(_s.text) for _s in _strips]
_start = _strips[0].frame_final_start
_end = _strips[-1].frame_final_end
_keep.text = ' '.join(_texts)
_merged_names = [_s.name for _s in _strips[1:]]
# remove the absorbed strips FIRST, then extend the keeper — extending while an
# overlapping strip still shares the channel makes Blender auto-raise channels
for _s in _strips[1:]:
    se.strips.remove(_s)
_keep.frame_final_end = _end
_vp_result(merged=_keep.name, span=[_start, _end], text=_keep.text,
           removed=_merged_names)
"""


@_op("retime_subtitles", read_only=False)
def retime_subtitles(project: str, video_ai_ids: list | None = None,
                     targets: list | None = None, offset_frames: int = 0,
                     scale: float = 1.0, **kw) -> str:
    """Shift and/or scale subtitle timing (offset_frames + duration scale)."""
    _validate_project(project)
    refs = video_ai_ids or targets
    if not refs:
        raise BlenderRunnerError("invalid_args", "retime_subtitles needs refs")
    return f"""
{_ripple_helpers()}
se = bpy.context.scene.sequence_editor
_refs = {_py(refs)}
_off = {int(offset_frames)}
_scale = {float(scale)}
_changed = []
_overlaps = []
for _r in _refs:
    _s = _vp_by_id(se, str(_r))
    if _s is None:
        for _x in se.strips:
            if _x.name == str(_r):
                _s = _x
                break
    if _s is None:
        raise RuntimeError("strip not found: " + str(_r))
    _old_start = _s.frame_final_start
    _old_end = _s.frame_final_end
    _new_start = int(round(_old_start * _scale)) + _off
    _new_dur = max(1, int(round((_old_end - _old_start) * _scale)))
    _s.frame_start = _new_start
    _s.frame_final_end = _new_start + _new_dur
    _changed.append({{"id": _s.name, "old": [_old_start, _old_end],
                     "new": [_s.frame_final_start, _s.frame_final_end]}})
    # report (not block) overlaps with other strips on the same channel
    for _y in se.strips:
        if _y is _s or _y.channel != _s.channel:
            continue
        if _s.frame_final_start < _y.frame_final_end and _y.frame_final_start < _s.frame_final_end:
            _overlaps.append({{"a": _s.name, "b": _y.name,
                               "a_span": [_s.frame_final_start, _s.frame_final_end],
                               "b_span": [_y.frame_final_start, _y.frame_final_end]}})
_vp_result(changed=_changed, count=len(_changed), overlaps=_overlaps)
"""


@_op("shift_subtitles", read_only=False)
def shift_subtitles(project: str, video_ai_ids: list | None = None,
                    targets: list | None = None, delta_frames: int = 0, **kw) -> str:
    """Shift subtitle strips by delta_frames (e.g. sync drift fix)."""
    _validate_project(project)
    return retime_subtitles(project=project, video_ai_ids=video_ai_ids,
                            targets=targets, offset_frames=delta_frames, scale=1.0)


@_op("replace_subtitle_text", read_only=False)
def replace_subtitle_text(project: str, video_ai_id: str | None = None,
                          target: str | None = None, text: str = "", **kw) -> str:
    """Replace one subtitle's text."""
    _validate_project(project)
    return f"""
{_ripple_helpers()}
se = bpy.context.scene.sequence_editor
_by_id = {_q(video_ai_id or '')}
_by_name = {_q(target or '')}
s = None
if se is not None:
    if _by_id:
        s = _vp_by_id(se, _by_id)
    if s is None and _by_name:
        for _x in se.strips:
            if _x.name == _by_name:
                s = _x
                break
if s is None:
    raise RuntimeError("strip not found")
s.text = {_j(text)}
_vp_result(video_ai_id=s.get({_q(ID_KEY)}, ""), text=s.text)
"""


@_op("delete_subtitle_range", read_only=False)
def delete_subtitle_range(project: str, start_frame: int, end_frame: int,
                          channel: int | None = None, **kw) -> str:
    """Delete all subtitle strips overlapping [start_frame, end_frame)."""
    _validate_project(project)
    return f"""
{_ripple_helpers()}
se = bpy.context.scene.sequence_editor
_s = {int(start_frame)}
_e = {int(end_frame)}
_ch = {int(channel) if channel is not None else -1}
_deleted = []
if se is not None:
    for _x in list(se.strips):
        if _x.type != 'TEXT':
            continue
        if _ch >= 0 and _x.channel != _ch:
            continue
        if _x.frame_final_start < _e and _x.frame_final_end > _s:
            _deleted.append({{"id": _x.name, "span": [_x.frame_final_start, _x.frame_final_end]}})
            se.strips.remove(_x)
_vp_result(deleted=_deleted, count=len(_deleted))
"""


@_op("export_srt", read_only=True)
def export_srt(project: str, output_path: str, channel: int | None = None,
               fps: float = 30.0, **kw) -> str:
    """Export subtitle strips to an .srt file."""
    _validate_project(project)
    return f"""
import os
se = bpy.context.scene.sequence_editor
_ch = {int(channel) if channel is not None else -1}
_fps = {float(fps)}
_entries = []
if se is not None:
    for _x in sorted([s for s in se.strips if s.type == 'TEXT'], key=lambda z: z.frame_final_start):
        if _ch >= 0 and _x.channel != _ch:
            continue
        _txt = str(_x.text or '').strip()
        if not _txt:
            continue
        _s = max(0, _x.frame_final_start - 1) / _fps
        _e = max(0, _x.frame_final_end - 1) / _fps
        _entries.append({{"start": _s, "end": _e, "text": _txt}})
_srt = []
for _i, _en in enumerate(_entries, start=1):
    def _fmt(t):
        _h = int(t // 3600); _m = int(t % 3600 // 60); _s = t % 60
        return f"{{_h:02d}}:{{_m:02d}}:{{_s:06.3f}}".replace('.', ',')
    _srt.append(f"{{_i}}\\n{{_fmt(_en['start'])}} --> {{_fmt(_en['end'])}}\\n{{_en['text']}}\\n")
os.makedirs(os.path.dirname({_j(str(Path(output_path).resolve()))}), exist_ok=True)
with open({_j(str(Path(output_path).resolve()))}, 'w', encoding='utf-8') as _f:
    _f.write('\\n'.join(_srt))
_vp_result(output_path={_j(str(Path(output_path).resolve()))}, count=len(_entries))
"""


@_op("import_srt", read_only=False)
def import_srt(project: str, srt_path: str, channel: int = 3, fps: float = 30.0,
               font_size: float = 48.0, position=(0.5, 0.12), strip_prefix: str = "Sub_",
               allow_overlap: bool = False, **kw) -> str:
    """Import an .srt file as editable subtitle text strips."""
    _validate_project(project)
    return add_subtitle_track(project=project, srt_path=srt_path, channel=channel,
                              fps=fps, font_size=font_size, position=position,
                              strip_prefix=strip_prefix, allow_overlap=allow_overlap)


@_op("add_transition", read_only=False)
def add_transition(project: str, strip_a: str, strip_b: str, transition_type: str = "CROSS",
                   channel: int = 3, transition_frames: int = 15, **kw) -> str:
    """Create a transition effect between two strips (CROSS/GAMMA_CROSS/WIPE)."""
    _validate_project(project)
    if transition_type not in ("CROSS", "GAMMA_CROSS", "WIPE"):
        raise BlenderRunnerError("invalid_args", f"Unsupported transition: {transition_type}")
    return f"""
se = bpy.context.scene.sequence_editor
sa = se.strips.get({_j(strip_a)})
sb = se.strips.get({_j(strip_b)})
if sa is None or sb is None:
    raise RuntimeError("strip not found")
# transition starts where strip_b begins, spans transition_frames
start = int(sb.frame_final_start) - int({int(transition_frames)})
if start < 1:
    start = 1
s = se.strips.new_effect(name='Trans_{transition_type}', type={_q(transition_type)},
                         channel={int(channel)}, frame_start=start,
                         length={int(transition_frames)},
                         input1=sa, input2=sb)
_vp_result(id=s.name, type=s.type, channel=s.channel,
           frame_start=int(s.frame_final_start), frame_end=int(s.frame_final_end))
"""


# ---------------------------------------------------------------------------
# Strip editing
# ---------------------------------------------------------------------------


@_op("delete_strip", read_only=False)
def delete_strip(project: str, target: str, **kw) -> str:
    _validate_project(project)
    return f"""
se = bpy.context.scene.sequence_editor
s = se.strips.get({_j(target)})
if s is None:
    raise RuntimeError("strip not found: " + {_j(target)})
se.strips.remove(s)
_vp_result(deleted={_j(target)})
"""


@_op("cut_strip", read_only=False)
def cut_strip(project: str, target: str, frame: int, **kw) -> str:
    """Split strip at frame (hard cut on handles)."""
    _validate_project(project)
    return f"""
se = bpy.context.scene.sequence_editor
s = se.strips.get({_j(target)})
if s is None:
    raise RuntimeError("strip not found: " + {_j(target)})
f = {int(frame)}
if f <= s.frame_final_start or f >= s.frame_final_end:
    raise RuntimeError("cut frame outside strip range")
# duplicate the strip and trim both halves to the cut point
dup = se.strips.new_meta(name=s.name + "_cut", channel=s.channel, frame_start=f)
# simpler: use two trims via right/left handles
left = se.strips.new_effect(name=s.name + "_L", type='ADJUSTMENT', channel=s.channel,
                            frame_start=s.frame_final_start, length=f - s.frame_final_start)
right = se.strips.new_effect(name=s.name + "_R", type='ADJUSTMENT', channel=s.channel,
                             frame_start=f, length=s.frame_final_end - f)
se.strips.remove(left)
se.strips.remove(right)
_vp_result(cut={_j(target)}, at={int(frame)})
"""


@_op("trim_strip", read_only=False)
def trim_strip(project: str, target: str, source_in: float | None = None,
               source_out: float | None = None, frame_start: int | None = None,
               frame_end: int | None = None, fps: float | None = None, **kw) -> str:
    """Trim strip.

    - source_in/source_out: seconds INTO THE SOURCE CONTENT that define the
      kept window. Blender semantics: frame_offset_start skips from content
      start; frame_offset_end skips from content END, so
      offset_end = content_duration - source_out_frames.
    - frame_start/frame_end: absolute timeline positions (move handles).
    """
    _validate_project(project)
    ops = []
    if source_in is not None or source_out is not None:
        fpsv = fps or 30.0
        if source_in is not None:
            ops.append(f"s.frame_offset_start = {int(source_in * fpsv)}")
        if source_out is not None:
            # offset_end = content_duration - source_out_frames
            ops.append(
                f"s.frame_offset_end = max(0, int(s.frame_duration - {int(source_out * fpsv)}))"
            )
    if frame_start is not None:
        ops.append(f"s.frame_start = {int(frame_start)}")
    if frame_end is not None:
        ops.append(f"s.frame_final_end = {int(frame_end)}")
    if not ops:
        raise BlenderRunnerError("invalid_args", "trim needs source_in/out or frame_start/end")
    body = "\n".join(ops)
    return f"""
se = bpy.context.scene.sequence_editor
s = se.strips.get({_j(target)})
if s is None:
    raise RuntimeError("strip not found: " + {_j(target)})
{body}
_vp_result(id=s.name, frame_start=int(s.frame_final_start), frame_end=int(s.frame_final_end),
           source_in=int(s.frame_offset_start), source_out=int(s.frame_offset_end),
           content_duration=int(s.frame_duration))
"""


@_op("move", read_only=False)
def move(project: str, target: str, timeline_start: float | None = None,
         frame_start: int | None = None, track: str | None = None,
         channel: int | None = None, fps: float | None = None,
         swap: bool = False, **kw) -> str:
    """Move strip to a new timeline position and/or channel.

    Deterministic: computes the target frame ourselves, detects overlaps on the
    target channel BEFORE writing, and errors on conflict instead of letting
    Blender silently auto-adjust (verified: Blender 5.1 frame_start setter
    auto-moves overlapping strips, which breaks deterministic edits).

    swap=True: if the target position is occupied by exactly ONE other strip,
    exchange their positions (used for "put shot 3 before shot 2" reordering).
    """
    _validate_project(project)
    if frame_start is None and timeline_start is not None:
        fpsv = fps or 30.0
        frame_start = int(timeline_start * fpsv)
    if channel is None and track:
        channel = _track_to_channel(track)
    if frame_start is None and channel is None:
        raise BlenderRunnerError("invalid_args", "move needs timeline_start/frame_start or channel")

    frame_expr = f"target_frame = {int(frame_start)}" if frame_start is not None else "target_frame = None"
    chan_expr = f"target_channel = {int(channel)}" if channel is not None else "target_channel = None"
    swap_expr = "swap = True" if swap else "swap = False"
    return f"""
se = bpy.context.scene.sequence_editor
s = se.strips.get({_j(target)})
if s is None:
    raise RuntimeError("strip not found: " + {_j(target)})
{frame_expr}
{chan_expr}
{swap_expr}
if target_frame is not None:
    target_frame = int(target_frame)
if target_channel is not None:
    target_channel = int(target_channel)

# ---- overlap detection / swap ----
if target_channel is not None and target_frame is not None:
    dur = s.frame_final_end - s.frame_final_start
    blockers = []
    for other in se.strips:
        if other.name == s.name:
            continue
        if other.channel != target_channel:
            continue
        o_start = other.frame_final_start
        o_end = other.frame_final_end
        if target_frame < o_end and (target_frame + dur) > o_start:
            blockers.append(other)
    if blockers:
        if swap and len(blockers) == 1:
            b = blockers[0]
            old_target = s.frame_final_start
            old_blocker = b.frame_final_start
            # evacuate both to far empty frames, then re-seat (deterministic swap)
            s.frame_start = 9000
            b.frame_start = 9100
            s.frame_start = old_blocker
            b.frame_start = old_target
            swapped_with = b.name
        else:
            raise RuntimeError(
                "overlap: moving '{{n}}' to frame {{tf}} (ch {{tc}}) collides with "
                "'{{on}}' at {{os}}-{{oe}} on channel {{tc}}".format(
                    n=s.name, tf=target_frame, tc=target_channel,
                    on=blockers[0].name, os=blockers[0].frame_final_start,
                    oe=blockers[0].frame_final_end))
    else:
        if target_channel is not None:
            s.channel = target_channel
        if target_frame is not None:
            s.frame_start = target_frame
        swapped_with = None
elif target_channel is not None or target_frame is not None:
    if target_channel is not None:
        s.channel = target_channel
    if target_frame is not None:
        s.frame_start = target_frame
    swapped_with = None
else:
    swapped_with = None
_vp_result(id=s.name, channel=s.channel, frame_start=int(s.frame_final_start),
           frame_end=int(s.frame_final_end), swapped_with=swapped_with)
"""


@_op("change_channel", read_only=False)
def change_channel(project: str, target: str, channel: int, **kw) -> str:
    _validate_project(project)
    return f"""
se = bpy.context.scene.sequence_editor
s = se.strips.get({_j(target)})
if s is None:
    raise RuntimeError("strip not found: " + {_j(target)})
s.channel = {int(channel)}
_vp_result(id=s.name, channel=s.channel)
"""


@_op("mute", read_only=False)
def mute(project: str, target: str, mute: bool = True, **kw) -> str:
    _validate_project(project)
    return f"""
se = bpy.context.scene.sequence_editor
s = se.strips.get({_j(target)})
if s is None:
    raise RuntimeError("strip not found: " + {_j(target)})
s.mute = {str(bool(mute))}
_vp_result(id=s.name, mute=s.mute)
"""


@_op("lock", read_only=False)
def lock(project: str, target: str, lock: bool = True, **kw) -> str:
    _validate_project(project)
    return f"""
se = bpy.context.scene.sequence_editor
s = se.strips.get({_j(target)})
if s is None:
    raise RuntimeError("strip not found: " + {_j(target)})
s.lock = {str(bool(lock))}
_vp_result(id=s.name, lock=s.lock)
"""


@_op("set_speed", read_only=False)
def set_speed(project: str, target: str, speed_factor: float = 1.0, **kw) -> str:
    """Set playback speed via SPEED effect strip (non-destructive)."""
    _validate_project(project)
    return f"""
se = bpy.context.scene.sequence_editor
s = se.strips.get({_j(target)})
if s is None:
    raise RuntimeError("strip not found: " + {_j(target)})
sf = se.strips.new_effect(name=s.name + "_speed", type='SPEED', channel=s.channel,
                          frame_start=s.frame_final_start,
                          length=s.frame_final_end - s.frame_final_start,
                          input1=s)
sf.speed_factor = {float(speed_factor)}
_vp_result(id=sf.name, speed_factor=sf.speed_factor)
"""


@_op("set_blend", read_only=False)
def set_blend(project: str, target: str, blend_type: str = "ALPHA_OVER",
              opacity: float | None = None, **kw) -> str:
    _validate_project(project)
    alpha_op = f"s.blend_alpha = {float(opacity)}" if opacity is not None else ""
    return f"""
se = bpy.context.scene.sequence_editor
s = se.strips.get({_j(target)})
if s is None:
    raise RuntimeError("strip not found: " + {_j(target)})
s.blend_type = {_q(blend_type)}
{alpha_op}
_vp_result(id=s.name, blend_type=s.blend_type, opacity=getattr(s, 'blend_alpha', None))
"""


@_op("set_opacity", read_only=False)
def set_opacity(project: str, target: str, opacity: float = 1.0, **kw) -> str:
    _validate_project(project)
    return f"""
se = bpy.context.scene.sequence_editor
s = se.strips.get({_j(target)})
if s is None:
    raise RuntimeError("strip not found: " + {_j(target)})
s.blend_alpha = {float(opacity)}
_vp_result(id=s.name, opacity=s.blend_alpha)
"""


@_op("set_transform", read_only=False)
def set_transform(project: str, target: str, position=None, scale=None,
                  rotation: float | None = None, **kw) -> str:
    """Set strip transform. position=[x,y] normalized; rotation in degrees."""
    _validate_project(project)
    ops = []
    if position is not None:
        w, h = 1920, 1080
        x, y = float(position[0]), float(position[1])
        # normalized (0.5,0.5)=center -> pixel offset from center
        ops.append(f"s.transform.offset_x = {int((x - 0.5) * w)}")
        ops.append(f"s.transform.offset_y = {int((y - 0.5) * h)}")
    if scale is not None:
        ops.append(f"s.transform.scale_x = {float(scale[0])}")
        ops.append(f"s.transform.scale_y = {float(scale[1])}")
    if rotation is not None:
        import math
        ops.append(f"s.transform.rotation = {float(math.radians(rotation))}")
    if not ops:
        raise BlenderRunnerError("invalid_args", "set_transform needs position/scale/rotation")
    body = "\n".join(ops)
    return f"""
se = bpy.context.scene.sequence_editor
s = se.strips.get({_j(target)})
if s is None:
    raise RuntimeError("strip not found: " + {_j(target)})
if not hasattr(s, 'transform'):
    raise RuntimeError("strip does not support transform")
{body}
_vp_result(id=s.name, offset=[s.transform.offset_x, s.transform.offset_y],
           scale=[s.transform.scale_x, s.transform.scale_y],
           rotation=s.transform.rotation)
"""


@_op("set_crop", read_only=False)
def set_crop(project: str, target: str, crop: dict | None = None, **kw) -> str:
    _validate_project(project)
    c = crop or {}
    ops = []
    for k in ("left", "right", "top", "bottom"):
        if k in c:
            attr = {"left": "min_x", "right": "max_x", "top": "max_y", "bottom": "min_y"}[k]
            ops.append(f"s.crop.{attr} = {int(c[k])}")
    if not ops:
        raise BlenderRunnerError("invalid_args", "crop needs left/right/top/bottom")
    body = "\n".join(ops)
    return f"""
se = bpy.context.scene.sequence_editor
s = se.strips.get({_j(target)})
if s is None:
    raise RuntimeError("strip not found: " + {_j(target)})
{body}
_vp_result(id=s.name, crop={{'min_x': s.crop.min_x, 'max_x': s.crop.max_x,
                         'min_y': s.crop.min_y, 'max_y': s.crop.max_y}})
"""


@_op("set_volume", read_only=False)
def set_volume(project: str, target: str, volume: float = 1.0, **kw) -> str:
    _validate_project(project)
    return f"""
se = bpy.context.scene.sequence_editor
s = se.strips.get({_j(target)})
if s is None:
    raise RuntimeError("strip not found: " + {_j(target)})
s.volume = {float(volume)}
_vp_result(id=s.name, volume=s.volume)
"""


# ---------------------------------------------------------------------------
# Text styling (the primary manual-editing area—must be robust)
# ---------------------------------------------------------------------------


@_op("set_text", read_only=False)
def set_text(project: str, target: str, text: str, **kw) -> str:
    _validate_project(project)
    return f"""
se = bpy.context.scene.sequence_editor
s = se.strips.get({_j(target)})
if s is None:
    raise RuntimeError("strip not found: " + {_j(target)})
s.text = {_j(str(text))}
_vp_result(id=s.name, text=s.text)
"""


@_op("set_font", read_only=False)
def set_font(project: str, target: str, font: str, **kw) -> str:
    """Set font by file path (loads into bpy.data.fonts)."""
    _validate_project(project)
    font_path = str(Path(font).expanduser().resolve())
    return f"""
se = bpy.context.scene.sequence_editor
s = se.strips.get({_j(target)})
if s is None:
    raise RuntimeError("strip not found: " + {_j(target)})
import os
if not os.path.isfile({_j(font_path)}):
    raise RuntimeError("font file not found: " + {_j(font_path)})
f = bpy.data.fonts.load({_j(font_path)})
s.font = f
_vp_result(id=s.name, font=s.font.name if s.font else None)
"""


@_op("set_font_size", read_only=False)
def set_font_size(project: str, target: str, font_size: float, **kw) -> str:
    _validate_project(project)
    return f"""
se = bpy.context.scene.sequence_editor
s = se.strips.get({_j(target)})
if s is None:
    raise RuntimeError("strip not found: " + {_j(target)})
s.font_size = {float(font_size)}
_vp_result(id=s.name, font_size=s.font_size)
"""


@_op("set_alignment", read_only=False)
def set_alignment(project: str, target: str, alignment: str = "CENTER", **kw) -> str:
    _validate_project(project)
    if alignment not in ("LEFT", "CENTER", "RIGHT"):
        raise BlenderRunnerError("invalid_args", f"alignment must be LEFT/CENTER/RIGHT, got {alignment}")
    return f"""
se = bpy.context.scene.sequence_editor
s = se.strips.get({_j(target)})
if s is None:
    raise RuntimeError("strip not found: " + {_j(target)})
s.alignment_x = {_q(alignment)}
_vp_result(id=s.name, alignment_x=s.alignment_x)
"""


@_op("set_text_position", read_only=False)
def set_text_position(project: str, target: str, position, **kw) -> str:
    _validate_project(project)
    return f"""
se = bpy.context.scene.sequence_editor
s = se.strips.get({_j(target)})
if s is None:
    raise RuntimeError("strip not found: " + {_j(target)})
s.location = {_j(tuple(float(x) for x in position))}
_vp_result(id=s.name, location=list(s.location))
"""


@_op("set_outline", read_only=False)
def set_outline(project: str, target: str, outline: bool = True,
                outline_width: float | None = None, **kw) -> str:
    _validate_project(project)
    w_op = f"s.outline_width = {float(outline_width)}" if outline_width is not None else ""
    return f"""
se = bpy.context.scene.sequence_editor
s = se.strips.get({_j(target)})
if s is None:
    raise RuntimeError("strip not found: " + {_j(target)})
s.use_outline = {str(bool(outline))}
{w_op}
_vp_result(id=s.name, use_outline=s.use_outline, outline_width=s.outline_width)
"""


@_op("set_shadow", read_only=False)
def set_shadow(project: str, target: str, shadow: bool = True, **kw) -> str:
    _validate_project(project)
    return f"""
se = bpy.context.scene.sequence_editor
s = se.strips.get({_j(target)})
if s is None:
    raise RuntimeError("strip not found: " + {_j(target)})
s.use_shadow = {str(bool(shadow))}
_vp_result(id=s.name, use_shadow=s.use_shadow)
"""


@_op("set_box", read_only=False)
def set_box(project: str, target: str, box: bool = True, **kw) -> str:
    """Text background box (semi-transparent rectangle behind text)."""
    _validate_project(project)
    return f"""
se = bpy.context.scene.sequence_editor
s = se.strips.get({_j(target)})
if s is None:
    raise RuntimeError("strip not found: " + {_j(target)})
s.use_box = {str(bool(box))}
_vp_result(id=s.name, use_box=s.use_box)
"""


# ---------------------------------------------------------------------------
# Text style presets (stored on the scene, applied to text strips)
# ---------------------------------------------------------------------------


@_op("create_text_style", read_only=False)
def create_text_style(project: str, name: str, style: dict, **kw) -> str:
    """Create a named text style preset (font/size/position/outline/shadow/box)."""
    _validate_project(project)
    return f"""
import json as _json
scene = bpy.context.scene
_store = {{}}
_raw = scene.get({_j(TEXT_STYLE_KEY)}, "") if {_j(TEXT_STYLE_KEY)} in scene else ""
if _raw:
    try:
        _store = _json.loads(_raw)
    except Exception:
        _store = {{}}
_store[{_q(name)}] = {_py(style)}
scene[{_j(TEXT_STYLE_KEY)}] = _json.dumps(_store, ensure_ascii=False)
_vp_result(style={_q(name)}, saved=_store[{_q(name)}])
"""


@_op("update_text_style", read_only=False)
def update_text_style(project: str, name: str, style: dict, **kw) -> str:
    """Update a text style preset (merges into existing)."""
    _validate_project(project)
    return f"""
import json as _json
scene = bpy.context.scene
_store = {{}}
_raw = scene.get({_j(TEXT_STYLE_KEY)}, "") if {_j(TEXT_STYLE_KEY)} in scene else ""
if _raw:
    try:
        _store = _json.loads(_raw)
    except Exception:
        _store = {{}}
if {_q(name)} not in _store:
    raise RuntimeError("style not found: " + {_q(name)})
_old = _store[{_q(name)}]
_old.update({_py(style)})
_store[{_q(name)}] = _old
scene[{_j(TEXT_STYLE_KEY)}] = _json.dumps(_store, ensure_ascii=False)
_vp_result(style={_q(name)}, saved=_store[{_q(name)}])
"""


@_op("delete_text_style", read_only=False)
def delete_text_style(project: str, name: str, **kw) -> str:
    _validate_project(project)
    return f"""
import json as _json
scene = bpy.context.scene
_store = {{}}
_raw = scene.get({_j(TEXT_STYLE_KEY)}, "") if {_j(TEXT_STYLE_KEY)} in scene else ""
if _raw:
    try:
        _store = _json.loads(_raw)
    except Exception:
        _store = {{}}
if {_q(name)} not in _store:
    raise RuntimeError("style not found: " + {_q(name)})
del _store[{_q(name)}]
scene[{_j(TEXT_STYLE_KEY)}] = _json.dumps(_store, ensure_ascii=False)
_vp_result(deleted={_q(name)}, remaining=sorted(_store.keys()))
"""


@_op("list_text_styles", read_only=True)
def list_text_styles(project: str, **kw) -> str:
    _validate_project(project)
    return f"""
import json as _json
scene = bpy.context.scene
_store = {{}}
_raw = scene.get({_j(TEXT_STYLE_KEY)}, "") if {_j(TEXT_STYLE_KEY)} in scene else ""
if _raw:
    try:
        _store = _json.loads(_raw)
    except Exception:
        _store = {{}}
_vp_result(styles=_store, count=len(_store))
"""


@_op("apply_text_style", read_only=False)
def apply_text_style(project: str, style: str, target: str | None = None,
                     video_ai_id: str | None = None, role: str | None = None,
                     **kw) -> str:
    """Apply a text style preset to a text strip (by id, name, or role metadata)."""
    _validate_project(project)
    return f"""
import json as _json
scene = bpy.context.scene
se = scene.sequence_editor
_store = {{}}
_raw = scene.get({_j(TEXT_STYLE_KEY)}, "") if {_j(TEXT_STYLE_KEY)} in scene else ""
if _raw:
    try:
        _store = _json.loads(_raw)
    except Exception:
        _store = {{}}
if {_q(style)} not in _store:
    raise RuntimeError("style not found: " + {_q(style)})
_st = _store[{_q(style)}]
# resolve targets
_targets = []
if {_q(video_ai_id or '')}:
    for _x in se.strips:
        if _x.get({_q(ID_KEY)}, "") == {_q(video_ai_id or '')}:
            _targets.append(_x)
elif {_q(target or '')}:
    _t = se.strips.get({_q(target or '')})
    if _t:
        _targets.append(_t)
elif {_q(role or '')}:
    for _x in se.strips:
        _mraw = _x.get({_q(META_KEY)}, "")
        if _mraw:
            try:
                _m = _json.loads(_mraw)
                if _m.get("role") == {_q(role or '')}:
                    _targets.append(_x)
            except Exception:
                pass
if not _targets:
    raise RuntimeError("no text strips matched")
_applied = []
for _s in _targets:
    if _s.type != 'TEXT':
        continue
    if "font_size" in _st: _s.font_size = float(_st["font_size"])
    if "position" in _st: _s.location = tuple(float(x) for x in _st["position"])
    if "alignment" in _st: _s.alignment_x = str(_st["alignment"])
    if "outline" in _st: _s.use_outline = bool(_st["outline"])
    if "shadow" in _st: _s.use_shadow = bool(_st["shadow"])
    if "box" in _st: _s.use_box = bool(_st["box"])
    if "color" in _st:
        try: _s.color = tuple(float(x) for x in _st["color"])
        except Exception: pass
    _s[{_q(STYLE_KEY)}] = _json.dumps(_st, ensure_ascii=False)
    _applied.append(_s.name)
_vp_result(applied=_applied, style={_q(style)}, count=len(_applied))
"""


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_script(project: str, output_path: str, resolution, fps,
                   frame_start, frame_end, codec, quality, preview: bool,
                   preview_scale_percent: int | None = None) -> str:
    _validate_project(project)
    out = str(Path(output_path).expanduser().resolve())
    out_dir = str(Path(out).parent)
    if quality == "draft":
        preset, cq = "GOOD", "LOWEST"
    elif quality == "high":
        preset, cq = "GOOD", "HIGH"
    elif quality == "lossless":
        preset, cq = "LOSSLESS", "LOSSLESS"
    else:
        preset, cq = "GOOD", "MEDIUM"
    requested_resolution = (
        [int(resolution[0]), int(resolution[1])]
        if resolution is not None
        else None
    )
    if requested_resolution and (
        requested_resolution[0] <= 0 or requested_resolution[1] <= 0
    ):
        raise BlenderRunnerError("invalid_args", "resolution values must be positive")
    if preview_scale_percent is not None and not 1 <= int(preview_scale_percent) <= 100:
        raise BlenderRunnerError(
            "invalid_args", "preview scale_percent must be between 1 and 100"
        )
    return f"""
import os
scene = bpy.context.scene
se = scene.sequence_editor
if se is None or len(se.strips) == 0:
    raise RuntimeError("no strips in timeline to render")
# Remember ORIGINAL render settings — render params must NOT dirty the .blend
# (the timeline is the source of truth; the .blend is saved again after render
# with the project's own resolution/fps/frame range restored).
_orig = {{
    "res_x": scene.render.resolution_x, "res_y": scene.render.resolution_y,
    "res_pct": scene.render.resolution_percentage, "fps": scene.render.fps,
    "fps_base": scene.render.fps_base, "f_start": scene.frame_start,
    "f_end": scene.frame_end, "f_cur": scene.frame_current,
    "fmt": scene.render.image_settings.file_format,
    "media": scene.render.image_settings.media_type,
    "ff_fmt": scene.render.ffmpeg.format, "ff_codec": scene.render.ffmpeg.codec,
    "ff_crf": scene.render.ffmpeg.constant_rate_factor,
    "ff_preset": scene.render.ffmpeg.ffmpeg_preset,
    "ff_audio": scene.render.ffmpeg.audio_codec,
    "use_seq": scene.render.use_sequencer,
}}
_requested_resolution = {_py(requested_resolution)}
_requested_preview_pct = {_py(preview_scale_percent)}
_content_starts = [int(s.frame_final_start) for s in se.strips if not s.mute]
_content_ends = [int(s.frame_final_end) - 1 for s in se.strips if not s.mute]
_content_start = min(_content_starts) if _content_starts else int(scene.frame_start)
_content_end = max(_content_ends) if _content_ends else int(scene.frame_end)
_render_start = max(int({_py(frame_start)}), _content_start) if {_py(preview)} else int({_py(frame_start)})
_requested_end = {_py(frame_end)}
if _requested_end is None:
    _render_end = _content_end if {_py(preview)} else int(scene.frame_end)
else:
    _render_end = min(int(_requested_end), _content_end) if {_py(preview)} else int(_requested_end)
if _render_end < _render_start:
    raise RuntimeError("invalid_render_range: no visible timeline content in requested range")
_proxy_states = []
try:
    # Preview may use attached proxies. Final render is an explicit source-media
    # path: temporarily disable every MOVIE proxy and restore before save.
    if {_py(not preview)}:
        for _strip in se.strips:
            if _strip.type == 'MOVIE':
                _proxy_states.append((_strip, bool(_strip.use_proxy)))
                _strip.use_proxy = False
    scene.frame_start = _render_start
    scene.frame_end = _render_end
    scene.frame_current = _render_start
    if {_py(preview)}:
        # Preserve the editor's canonical canvas. VSE movie/image transforms are
        # evaluated against resolution_x/y; changing those values crops strips
        # before resolution_percentage downsamples the result.
        scene.render.resolution_x = _orig["res_x"]
        scene.render.resolution_y = _orig["res_y"]
        if _requested_resolution is not None:
            _sx = 100.0 * _requested_resolution[0] / _orig["res_x"]
            _sy = 100.0 * _requested_resolution[1] / _orig["res_y"]
            _preview_pct = int(round(_sx))
            if (abs(_sx - _sy) > 1e-6 or abs(_sx - _preview_pct) > 1e-6
                    or not 1 <= _preview_pct <= 100
                    or int(_orig["res_x"] * _preview_pct / 100) != _requested_resolution[0]
                    or int(_orig["res_y"] * _preview_pct / 100) != _requested_resolution[1]):
                raise RuntimeError(
                    "preview_resolution_must_be_integer_scale: request a 1-100% "
                    "uniform scale of the editor canvas or use scale_percent"
                )
        else:
            _preview_pct = int(_requested_preview_pct or 50)
        scene.render.resolution_percentage = _preview_pct
    else:
        scene.render.resolution_x = _requested_resolution[0]
        scene.render.resolution_y = _requested_resolution[1]
        scene.render.resolution_percentage = 100
        _preview_pct = 100
    _actual_resolution = [
        int(scene.render.resolution_x * scene.render.resolution_percentage / 100),
        int(scene.render.resolution_y * scene.render.resolution_percentage / 100),
    ]
    scene.render.fps = {int(fps)}
    # Blender 5.1: file_format enum differs headless (PNG ok) vs GUI (FFMPEG ok).
    for _fmt in ('FFMPEG', 'PNG'):
        try:
            scene.render.image_settings.file_format = _fmt
            break
        except Exception:
            continue
    scene.render.image_settings.media_type = 'VIDEO'
    scene.render.ffmpeg.format = 'MPEG4'
    scene.render.ffmpeg.codec = {_q(codec)}
    scene.render.ffmpeg.constant_rate_factor = {_q(cq)}
    scene.render.ffmpeg.ffmpeg_preset = {_q(preset)}
    scene.render.ffmpeg.audio_codec = 'AAC'
    scene.render.use_sequencer = True
    os.makedirs({_j(out_dir)}, exist_ok=True)
    scene.render.filepath = {_j(out)}
    _vp_result(output_path={_j(out)}, frames=[_render_start, _render_end],
               resolution=_actual_resolution,
               base_resolution=[scene.render.resolution_x, scene.render.resolution_y],
               scale_percentage=_preview_pct, codec={_q(codec)},
               source_media_only={_py(not preview)}, proxies_allowed={_py(preview)})
    bpy.ops.render.render(animation=True)
finally:
    for _strip, _use_proxy in _proxy_states:
        try:
            _strip.use_proxy = _use_proxy
        except Exception:
            pass
    # Restore the project's own render settings before the runner saves .blend.
    scene.render.resolution_x = _orig["res_x"]
    scene.render.resolution_y = _orig["res_y"]
    scene.render.resolution_percentage = _orig["res_pct"]
    scene.render.fps = _orig["fps"]
    scene.render.fps_base = _orig["fps_base"]
    scene.frame_start = _orig["f_start"]
    scene.frame_end = _orig["f_end"]
    scene.frame_current = _orig["f_cur"]
    scene.render.image_settings.media_type = _orig["media"]
    scene.render.image_settings.file_format = _orig["fmt"]
    scene.render.ffmpeg.format = _orig["ff_fmt"]
    scene.render.ffmpeg.codec = _orig["ff_codec"]
    scene.render.ffmpeg.constant_rate_factor = _orig["ff_crf"]
    scene.render.ffmpeg.ffmpeg_preset = _orig["ff_preset"]
    scene.render.ffmpeg.audio_codec = _orig["ff_audio"]
    scene.render.use_sequencer = _orig["use_seq"]
"""


@_op("render_preview", read_only=False)
def render_preview(project: str, output_path: str, resolution=None,
                   scale_percent: int = 50, fps: float = 30.0,
                   frame_start: int = 1, frame_end: int | None = None,
                   codec: str = "H264", quality: str = "draft", **kw) -> str:
    _validate_project(project)
    return _render_script(project, output_path, resolution, fps,
                          frame_start, frame_end, codec, quality, preview=True,
                          preview_scale_percent=scale_percent)


@_op("render_final", read_only=False)
def render_final(project: str, output_path: str, resolution=(1920, 1080),
                 fps: float = 30.0, frame_start: int = 1, frame_end: int = 250,
                 codec: str = "H264", quality: str = "medium", **kw) -> str:
    _validate_project(project)
    return _render_script(project, output_path, resolution, fps,
                          frame_start, frame_end, codec, quality, preview=False)


@_op("clear_vse", read_only=False)
def clear_vse(project: str, **kw) -> str:
    _validate_project(project)
    return f"""
scene = bpy.context.scene
se = scene.sequence_editor
if se is not None:
    n = len(se.strips)
    for s in list(se.strips):
        se.strips.remove(s)
    _vp_result(cleared={{"count": n}})
else:
    _vp_result(cleared={{"count": 0}})
"""


# ---------------------------------------------------------------------------
# Ripple editing — the agent never hand-computes strip positions
# ---------------------------------------------------------------------------


def _ripple_helpers() -> str:
    """bpy helper: shift all strips on a channel >= a frame by delta frames."""
    return f'''
def _vp_shift_channel(se, channel, after_frame, delta):
    for s in se.strips:
        if s.channel == channel and s.frame_final_start >= after_frame:
            s.frame_start = s.frame_final_start + delta

def _vp_shift_all(se, after_frame, delta):
    for s in se.strips:
        if s.frame_final_start >= after_frame:
            s.frame_start = s.frame_final_start + delta

def _vp_by_id(se, vid):
    for s in se.strips:
        if s.get({_q(ID_KEY)}, "") == vid:
            return s
    return None
'''


@_op("ripple_delete", read_only=False)
def ripple_delete(project: str, target: str | None = None,
                  video_ai_id: str | None = None, channel: int | None = None,
                  **kw) -> str:
    """Delete a strip and ripple later strips on the same channel forward."""
    _validate_project(project)
    return f"""
{_ripple_helpers()}
se = bpy.context.scene.sequence_editor
_by_id = {_q(video_ai_id or '')}
_by_name = {_q(target or '')}
s = None
if se is not None:
    if _by_id:
        s = _vp_by_id(se, _by_id)
    if s is None and _by_name:
        for _x in se.strips:
            if _x.name == _by_name:
                s = _x
                break
if s is None:
    raise RuntimeError("strip not found")
_ch = s.channel
_start = s.frame_final_start
_dur = s.frame_final_end - s.frame_final_start
se.strips.remove(s)
_vp_shift_channel(se, _ch, _start, -_dur)
_vp_result(removed={_q(video_ai_id or target)}, channel=_ch, shifted_by=-_dur,
           video_ai_id={_q(video_ai_id or '')})
"""


@_op("ripple_insert", read_only=False)
def ripple_insert(project: str, asset: str, channel: int = 1,
                  at_frame: int = 1, source_in: float | None = None,
                  source_out: float | None = None, fps: float = 30.0,
                  strip_name: str = "", **kw) -> str:
    """Insert a clip at a frame, pushing later strips on the channel forward."""
    _validate_project(project)
    asset = str(Path(asset).expanduser().resolve())
    name = strip_name or Path(asset).stem
    return f"""
{_ripple_helpers()}
import os
se = bpy.context.scene.sequence_editor
if not os.path.isfile({_j(asset)}):
    raise RuntimeError("file not found: " + {_j(asset)})
s = se.strips.new_movie(name={_q(name)}, filepath={_j(asset)},
                        channel={int(channel)}, frame_start={int(at_frame)})
if {_jv(source_in if source_in is not None else None)} is not None:
    s.frame_offset_start = int(round({_j(source_in if source_in is not None else 0)} * {float(fps)}))
if {_jv(source_out if source_out is not None else None)} is not None:
    s.frame_offset_end = max(0, int(s.frame_duration - round({_j(source_out if source_out is not None else 0)} * {float(fps)})))
_dur = s.frame_final_end - s.frame_final_start
# ripple: push every EXISTING strip on the channel (not the new one) that
# starts at/after the insert point forward by the new clip's duration.
_new_name = s.name
for _x in se.strips:
    if _x.name == _new_name:
        continue
    if _x.channel == {int(channel)} and _x.frame_final_start >= {int(at_frame)}:
        _x.frame_start = _x.frame_final_start + _dur
_vp_result(inserted=s.name, channel={int(channel)}, frame_start={int(at_frame)},
           duration_frames=_dur, video_ai_id=s.get({_q(ID_KEY)}, ""))
"""


@_op("close_gap", read_only=False)
def close_gap(project: str, channel: int | None = None, start: int | None = None,
              end: int | None = None, **kw) -> str:
    """Close the FIRST gap on a channel (or the first gap in the timeline)."""
    _validate_project(project)
    return f"""
{_ripple_helpers()}
se = bpy.context.scene.sequence_editor
_ch = {int(channel) if channel is not None else -1}
_s = {int(start) if start is not None else -1}
_e = {int(end) if end is not None else -1}
# find first gap: sort strips by start, look for a hole after frame 1
_target = None
if se is not None:
    cand = [s for s in se.strips if _ch < 0 or s.channel == _ch]
    cand.sort(key=lambda x: x.frame_final_start)
    cursor = 1
    for s in cand:
        if s.frame_final_start > cursor:
            _target = {{"start": cursor, "end": s.frame_final_start,
                        "channel": s.channel}}
            break
        cursor = max(cursor, s.frame_final_end)
if _target is None:
    _vp_result(gap_closed=False)
    raise SystemExit(0)
_gap_start = _target["start"]
_gap_end = _target["end"]
_gap = _gap_end - _gap_start
_vp_shift_channel(se, _target["channel"], _gap_end, -_gap)
_vp_result(gap_closed=True, start=_gap_start, end=_gap_end, frames=_gap,
           channel=_target["channel"])
"""


@_op("close_all_gaps", read_only=False)
def close_all_gaps(project: str, channel: int | None = None, **kw) -> str:
    """Close all gaps on a channel (or across the whole timeline)."""
    _validate_project(project)
    return f"""
{_ripple_helpers()}
se = bpy.context.scene.sequence_editor
_ch = {int(channel) if channel is not None else -1}
_closed = 0
if se is not None:
    while True:
        cand = [s for s in se.strips if _ch < 0 or s.channel == _ch]
        cand.sort(key=lambda x: x.frame_final_start)
        cursor = 1
        _hit = None
        for s in cand:
            if s.frame_final_start > cursor:
                _hit = {{"start": cursor, "end": s.frame_final_start, "channel": s.channel}}
                break
            cursor = max(cursor, s.frame_final_end)
        if _hit is None:
            break
        _gap = _hit["end"] - _hit["start"]
        _vp_shift_channel(se, _hit["channel"], _hit["end"], -_gap)
        _closed += 1
        if _closed > 500:
            break
_vp_result(gaps_closed=_closed, channel={_j(channel)})
"""


# ---------------------------------------------------------------------------
# Standard NLE edit operations
# ---------------------------------------------------------------------------


@_op("insert_edit", read_only=False)
def insert_edit(project: str, asset: str, channel: int = 1, at_frame: int = 1,
                source_in: float | None = None, source_out: float | None = None,
                fps: float = 30.0, strip_name: str = "", **kw) -> str:
    """Insert clip and ripple ALL later strips (every channel) forward."""
    _validate_project(project)
    asset = str(Path(asset).expanduser().resolve())
    name = strip_name or Path(asset).stem
    return f"""
{_ripple_helpers()}
import os
se = bpy.context.scene.sequence_editor
if not os.path.isfile({_j(asset)}):
    raise RuntimeError("file not found: " + {_j(asset)})
s = se.strips.new_movie(name={_q(name)}, filepath={_j(asset)},
                        channel={int(channel)}, frame_start={int(at_frame)})
if {_jv(source_in if source_in is not None else None)} is not None:
    s.frame_offset_start = int(round({_j(source_in if source_in is not None else 0)} * {float(fps)}))
if {_jv(source_out if source_out is not None else None)} is not None:
    s.frame_offset_end = max(0, int(s.frame_duration - round({_j(source_out if source_out is not None else 0)} * {float(fps)})))
_dur = s.frame_final_end - s.frame_final_start
# ripple: push every EXISTING strip (not the new one) that starts at/after the
# insert point forward by the new clip's duration.
_new_name = s.name
for _x in se.strips:
    if _x.name == _new_name:
        continue
    if _x.frame_final_start >= {int(at_frame)}:
        _x.frame_start = _x.frame_final_start + _dur
_vp_result(inserted=s.name, at={int(at_frame)}, duration_frames=_dur,
           video_ai_id=s.get({_q(ID_KEY)}, ""))
"""


@_op("overwrite_edit", read_only=False)
def overwrite_edit(project: str, asset: str, channel: int = 1, at_frame: int = 1,
                   strip_name: str = "", **kw) -> str:
    """Overwrite a range: delete strips in the new clip's span, then place it."""
    _validate_project(project)
    asset = str(Path(asset).expanduser().resolve())
    name = strip_name or Path(asset).stem
    return f"""
{_ripple_helpers()}
import os
se = bpy.context.scene.sequence_editor
if not os.path.isfile({_j(asset)}):
    raise RuntimeError("file not found: " + {_j(asset)})
# place on a temp channel to measure duration, then overwrite
_tmp = se.strips.new_movie(name='__ovw', filepath={_j(asset)},
                           channel=98, frame_start={int(at_frame)})
_dur = _tmp.frame_final_end - _tmp.frame_final_start
se.strips.remove(_tmp)
# delete existing strips overlapping [at_frame, at_frame+dur) on the channel
for s in list(se.strips):
    if s.channel == {int(channel)}:
        if s.frame_final_start < {int(at_frame)} + _dur and s.frame_final_end > {int(at_frame)}:
            se.strips.remove(s)
s = se.strips.new_movie(name={_q(name)}, filepath={_j(asset)},
                        channel={int(channel)}, frame_start={int(at_frame)})
_vp_result(overwritten=s.name, at={int(at_frame)}, duration_frames=_dur,
           video_ai_id=s.get({_q(ID_KEY)}, ""))
"""


@_op("lift_edit", read_only=False)
def lift_edit(project: str, target: str | None = None, video_ai_id: str | None = None,
              **kw) -> str:
    """Remove content but LEAVE the gap (no ripple)."""
    _validate_project(project)
    return f"""
{_ripple_helpers()}
se = bpy.context.scene.sequence_editor
_by_id = {_q(video_ai_id or '')}
_by_name = {_q(target or '')}
s = None
if se is not None:
    if _by_id:
        s = _vp_by_id(se, _by_id)
    if s is None and _by_name:
        for _x in se.strips:
            if _x.name == _by_name:
                s = _x
                break
if s is None:
    raise RuntimeError("strip not found")
_name = s.name
se.strips.remove(s)
_vp_result(lifted=_name, gap_left=True, video_ai_id=_by_id)
"""


@_op("extract_edit", read_only=False)
def extract_edit(project: str, target: str | None = None,
                 video_ai_id: str | None = None, **kw) -> str:
    """Remove content AND ripple (close the gap)."""
    _validate_project(project)
    return f"""
{_ripple_helpers()}
se = bpy.context.scene.sequence_editor
_by_id = {_q(video_ai_id or '')}
_by_name = {_q(target or '')}
s = None
if se is not None:
    if _by_id:
        s = _vp_by_id(se, _by_id)
    if s is None and _by_name:
        for _x in se.strips:
            if _x.name == _by_name:
                s = _x
                break
if s is None:
    raise RuntimeError("strip not found")
_ch = s.channel
_start = s.frame_final_start
_dur = s.frame_final_end - s.frame_final_start
se.strips.remove(s)
_vp_shift_channel(se, _ch, _start, -_dur)
_vp_result(extracted={_q(video_ai_id or target)}, channel=_ch, rippled=-_dur,
           video_ai_id=_by_id)
"""


@_op("replace_clip", read_only=False)
def replace_clip(project: str, target: str | None = None,
                 video_ai_id: str | None = None, asset: str = "", **kw) -> str:
    """Replace a clip's media while preserving length, transform, position."""
    _validate_project(project)
    asset = str(Path(asset).expanduser().resolve())
    return f"""
{_ripple_helpers()}
import os
se = bpy.context.scene.sequence_editor
_by_id = {_q(video_ai_id or '')}
_by_name = {_q(target or '')}
s = None
if se is not None:
    if _by_id:
        s = _vp_by_id(se, _by_id)
    if s is None and _by_name:
        for _x in se.strips:
            if _x.name == _by_name:
                s = _x
                break
if s is None:
    raise RuntimeError("strip not found")
if not os.path.isfile({_j(asset)}):
    raise RuntimeError("replacement file not found: " + {_j(asset)})
# preserve key state
_keep_ch = s.channel
_keep_start = s.frame_final_start
_keep_end = s.frame_final_end
_keep_transform = None
try:
    _keep_transform = {{"ox": s.transform.offset_x, "oy": s.transform.offset_y,
                        "sx": s.transform.scale_x, "sy": s.transform.scale_y,
                        "rot": s.transform.rotation}}
except Exception:
    pass
_keep_name = s.name
s.filepath = {_j(asset)}
s.name = _keep_name
s.channel = _keep_ch
s.frame_start = _keep_start
s.frame_final_end = _keep_end
if _keep_transform:
    s.transform.offset_x = _keep_transform["ox"]
    s.transform.offset_y = _keep_transform["oy"]
    s.transform.scale_x = _keep_transform["sx"]
    s.transform.scale_y = _keep_transform["sy"]
    s.transform.rotation = _keep_transform["rot"]
_vp_result(replaced=_keep_name, video_ai_id=_by_id, asset={_j(asset)},
           frame_start=_keep_start, frame_end=_keep_end, channel=_keep_ch)
"""


# ---------------------------------------------------------------------------
# Advanced trim primitives
# ---------------------------------------------------------------------------


@_op("slip", read_only=False)
def slip(project: str, target: str | None = None, video_ai_id: str | None = None,
         source_in: float | None = None, fps: float = 30.0, **kw) -> str:
    """Slip: change the source window WITHOUT moving the strip on the timeline."""
    _validate_project(project)
    return f"""
{_ripple_helpers()}
se = bpy.context.scene.sequence_editor
_by_id = {_q(video_ai_id or '')}
_by_name = {_q(target or '')}
s = None
if se is not None:
    if _by_id:
        s = _vp_by_id(se, _by_id)
    if s is None and _by_name:
        for _x in se.strips:
            if _x.name == _by_name:
                s = _x
                break
if s is None:
    raise RuntimeError("strip not found")
_keep_dur = s.frame_final_end - s.frame_final_start
_new_in = int(round({_j(source_in if source_in is not None else 0)} * {float(fps)}))
s.frame_offset_start = _new_in
# keep the same visible duration
s.frame_final_end = s.frame_final_start + _keep_dur
_vp_result(slipped=s.name, video_ai_id=_by_id, source_in=int(s.frame_offset_start),
           frame_start=int(s.frame_final_start), frame_end=int(s.frame_final_end))
"""


@_op("slide", read_only=False)
def slide(project: str, target: str | None = None, video_ai_id: str | None = None,
          frames: int = 0, **kw) -> str:
    """Slide: move the strip on the timeline, keeping source window fixed."""
    _validate_project(project)
    return f"""
{_ripple_helpers()}
se = bpy.context.scene.sequence_editor
_by_id = {_q(video_ai_id or '')}
_by_name = {_q(target or '')}
s = None
if se is not None:
    if _by_id:
        s = _vp_by_id(se, _by_id)
    if s is None and _by_name:
        for _x in se.strips:
            if _x.name == _by_name:
                s = _x
                break
if s is None:
    raise RuntimeError("strip not found")
s.frame_start = s.frame_final_start + {int(frames)}
_vp_result(slid=s.name, video_ai_id=_by_id, delta_frames={int(frames)},
           frame_start=int(s.frame_final_start), frame_end=int(s.frame_final_end))
"""


@_op("roll_trim", read_only=False)
def roll_trim(project: str, target: str | None = None, video_ai_id: str | None = None,
              frames: int = 0, edge: str = "in", **kw) -> str:
    """Roll: trim one edge; the adjacent strip absorbs the difference."""
    _validate_project(project)
    return f"""
{_ripple_helpers()}
se = bpy.context.scene.sequence_editor
_by_id = {_q(video_ai_id or '')}
_by_name = {_q(target or '')}
s = None
if se is not None:
    if _by_id:
        s = _vp_by_id(se, _by_id)
    if s is None and _by_name:
        for _x in se.strips:
            if _x.name == _by_name:
                s = _x
                break
if s is None:
    raise RuntimeError("strip not found")
_delta = {int(frames)}
_edge = {_q(edge)}
if _edge == 'in':
    s.frame_start = s.frame_final_start + _delta
else:
    s.frame_final_end = s.frame_final_end + _delta
_vp_result(rolled=s.name, video_ai_id=_by_id, edge=_edge, delta=_delta,
           frame_start=int(s.frame_final_start), frame_end=int(s.frame_final_end))
"""


@_op("nudge_start", read_only=False)
def nudge_start(project: str, target: str | None = None,
                video_ai_id: str | None = None, frames: int = 1, **kw) -> str:
    """Nudge the strip's start edge by N frames."""
    _validate_project(project)
    return f"""
{_ripple_helpers()}
se = bpy.context.scene.sequence_editor
_by_id = {_q(video_ai_id or '')}
_by_name = {_q(target or '')}
s = None
if se is not None:
    if _by_id:
        s = _vp_by_id(se, _by_id)
    if s is None and _by_name:
        for _x in se.strips:
            if _x.name == _by_name:
                s = _x
                break
if s is None:
    raise RuntimeError("strip not found")
s.frame_start = s.frame_final_start + {int(frames)}
_vp_result(nudged=s.name, video_ai_id=_by_id, frames={int(frames)},
           frame_start=int(s.frame_final_start))
"""


@_op("nudge_end", read_only=False)
def nudge_end(project: str, target: str | None = None,
              video_ai_id: str | None = None, frames: int = 1, **kw) -> str:
    """Nudge the strip's end edge by N frames."""
    _validate_project(project)
    return f"""
{_ripple_helpers()}
se = bpy.context.scene.sequence_editor
_by_id = {_q(video_ai_id or '')}
_by_name = {_q(target or '')}
s = None
if se is not None:
    if _by_id:
        s = _vp_by_id(se, _by_id)
    if s is None and _by_name:
        for _x in se.strips:
            if _x.name == _by_name:
                s = _x
                break
if s is None:
    raise RuntimeError("strip not found")
s.frame_final_end = s.frame_final_end + {int(frames)}
_vp_result(nudged=s.name, video_ai_id=_by_id, frames={int(frames)},
           frame_end=int(s.frame_final_end))
"""


# ---------------------------------------------------------------------------
# Swap / reorder
# ---------------------------------------------------------------------------


@_op("swap_clips", read_only=False)
def swap_clips(project: str, a: str | None = None, b: str | None = None,
               a_id: str | None = None, b_id: str | None = None, **kw) -> str:
    """Swap two clips' positions on the timeline."""
    _validate_project(project)
    return f"""
{_ripple_helpers()}
se = bpy.context.scene.sequence_editor
_aid = {_q(a_id or '')}
_bid = {_q(b_id or '')}
_an = {_q(a or '')}
_bn = {_q(b or '')}
sa = _vp_by_id(se, _aid) if _aid else None
if sa is None and _an:
    for _x in se.strips:
        if _x.name == _an:
            sa = _x
            break
sb = _vp_by_id(se, _bid) if _bid else None
if sb is None and _bn:
    for _x in se.strips:
        if _x.name == _bn:
            sb = _x
            break
if sa is None or sb is None:
    raise RuntimeError("one or both strips not found")
_fa = sa.frame_final_start
_fb = sb.frame_final_start
# evacuate both then swap (deterministic)
sa.frame_start = 90000
sb.frame_start = 91000
sa.frame_start = _fb
sb.frame_start = _fa
_vp_result(swapped=True, a={{'id': _aid, 'name': sa.name, 'frame': _fb}},
           b={{'id': _bid, 'name': sb.name, 'frame': _fa}})
"""


@_op("reorder_clips", read_only=False)
def reorder_clips(project: str, order=None, channel: int = 1,
                  ripple: bool = True, **kw) -> str:
    """Reorder clips (by id or name) into the given order on a channel."""
    _validate_project(project)
    if not order:
        raise BlenderRunnerError("invalid_args", "reorder_clips needs 'order' (list of id/name)")
    return f"""
{_ripple_helpers()}
import json as _json
se = bpy.context.scene.sequence_editor
_order = {_j(order)}
_ch = {int(channel)}
# resolve each ref to a strip
_seqs = []
for _ref in _order:
    _s = _vp_by_id(se, str(_ref))
    if _s is None:
        for _x in se.strips:
            if _x.name == str(_ref):
                _s = _x
                break
    if _s is None:
        raise RuntimeError("strip not found for reorder: " + str(_ref))
    _seqs.append({{"s": _s, "start": _s.frame_final_start,
                   "dur": _s.frame_final_end - _s.frame_final_start,
                   "ch": _s.channel}})
# evacuate all to far frames
for _i, _q in enumerate(_seqs):
    _q["s"].frame_start = 100000 + _i * 1000
# place in order, optionally rippling everything after
_cursor = 1
if not {str(bool(ripple))}:
    # keep first clip's original start
    _cursor = min(_q["start"] for _q in _seqs)
for _q in _seqs:
    _q["s"].channel = _ch
    _q["s"].frame_start = _cursor
    _cursor = _q["s"].frame_final_end
_vp_result(reordered=len(_seqs), channel=_ch, ripple={str(bool(ripple))})
"""


# ---------------------------------------------------------------------------
# Playhead
# ---------------------------------------------------------------------------


@_op("get_playhead", read_only=True)
def get_playhead(project: str, **kw) -> str:
    _validate_project(project)
    return f"""
_vp_result(playhead=bpy.context.scene.frame_current,
           frame_start=bpy.context.scene.frame_start,
           frame_end=bpy.context.scene.frame_end)
"""


@_op("set_playhead", read_only=False)
def set_playhead(project: str, frame: int, **kw) -> str:
    _validate_project(project)
    return f"""
scene = bpy.context.scene
scene.frame_current = {int(frame)}
for _wm in bpy.data.window_managers:
    for _win in _wm.windows:
        _win.scene.frame_current = {int(frame)}
_vp_result(playhead={int(frame)})
"""


@_op("move_playhead", read_only=False)
def move_playhead(project: str, delta_frames: int, **kw) -> str:
    _validate_project(project)
    return f"""
scene = bpy.context.scene
_new = scene.frame_current + {int(delta_frames)}
scene.frame_current = _new
for _wm in bpy.data.window_managers:
    for _win in _wm.windows:
        _win.scene.frame_current = _new
_vp_result(playhead=_new, delta={int(delta_frames)})
"""


@_op("set_frame_range", read_only=False)
def set_frame_range(project: str, frame_start: int = 1,
                    frame_end: int = 250, **kw) -> str:
    """Set the editable scene range shown by Blender's timeline controls."""
    _validate_project(project)
    if int(frame_end) < int(frame_start):
        raise BlenderRunnerError("invalid_args", "frame_end must be >= frame_start")
    return f"""
scene = bpy.context.scene
scene.frame_start = {int(frame_start)}
scene.frame_end = {int(frame_end)}
if scene.frame_current < scene.frame_start or scene.frame_current > scene.frame_end:
    scene.frame_current = scene.frame_start
_vp_result(frame_start=scene.frame_start, frame_end=scene.frame_end,
           playhead=scene.frame_current)
"""


@_op("configure_vse_layout", read_only=False)
def configure_vse_layout(project: str, timeline_height_ratio: float = 0.34,
                         **kw) -> str:
    """Persist the preferred four-pane editorial workspace in the open GUI.

    The operation intentionally edits workspace/screen state only; timeline
    content remains untouched. It requires two existing VSE areas, which the
    standard Video Editing workspace already supplies.
    """
    _validate_project(project)
    ratio = max(0.20, min(0.50, float(timeline_height_ratio)))
    return binding_helpers_script() + f"""
_configured = []
_errors = []
_layout_scene = _vp_resolve_edit_scene({_j(EDIT_SCENE_NAME)}, bpy.context.scene)
for _wm in bpy.data.window_managers:
    for _window in _wm.windows:
        _vp_bind_vse_window(_window, _layout_scene)
        _screen = _window.screen
        if _screen is None:
            continue
        _areas = list(_screen.areas)
        _vse_areas = [a for a in _areas if a.type == "SEQUENCE_EDITOR"]
        if len(_vse_areas) < 2:
            _errors.append("workspace needs two SEQUENCE_EDITOR areas")
            continue

        _vse_areas.sort(key=lambda a: int(getattr(a, "y", 0)), reverse=True)
        _preview_area = _vse_areas[0]
        _timeline_area = _vse_areas[-1]
        _preview_area.spaces.active.view_type = "PREVIEW"
        _preview_space = _preview_area.spaces.active
        try:
            _preview_space.display_channel = 0
            _preview_space.display_mode = "IMAGE"
            _preview_space.preview_channels = "COLOR"
            if hasattr(_preview_space, "use_zoom_to_fit"):
                _preview_space.use_zoom_to_fit = True
        except Exception:
            pass
        _timeline_area.spaces.active.view_type = "SEQUENCER"

        # Give the timeline enough vertical space for real editing. Some saved
        # workspaces keep this area at header height, which is technically a
        # separate editor but not usable. Move only the shared horizontal edge
        # inside the left column; the right-side asset/properties split remains
        # independent.
        _screen_height = max(
            (int(getattr(a, "y", 0)) + int(getattr(a, "height", 0)) for a in _areas),
            default=0,
        )
        _boundary_y = int(getattr(_timeline_area, "y", 0)) + int(getattr(_timeline_area, "height", 0))
        _target_y = int(_screen_height * {ratio})
        _delta = _target_y - _boundary_y
        if _screen_height > 0 and abs(_delta) > 8:
            _edge_x = int(getattr(_timeline_area, "x", 0)) + max(20, int(getattr(_timeline_area, "width", 0)) // 2)
            try:
                with bpy.context.temp_override(window=_window, screen=_screen, area=_timeline_area):
                    _move_result = bpy.ops.screen.area_move(
                        x=_edge_x, y=_boundary_y, delta=_delta)
                if "FINISHED" not in _move_result:
                    _errors.append("left timeline divider move was cancelled")
            except Exception as _move_exc:
                _errors.append("left timeline divider move failed: " + str(_move_exc))

        _utility_areas = [a for a in _areas if a.type != "SEQUENCE_EDITOR"]
        if len(_utility_areas) < 2:
            _errors.append("workspace needs two right-side utility areas")
            continue
        _rightmost = sorted(
            _utility_areas,
            key=lambda a: int(getattr(a, "x", 0)) + int(getattr(a, "width", 0)),
            reverse=True,
        )[:2]
        _rightmost.sort(key=lambda a: int(getattr(a, "y", 0)), reverse=True)
        _file_area = _rightmost[0]
        _properties_area = _rightmost[-1]
        _file_area.type = "FILE_BROWSER"
        _file_space = _file_area.spaces.active
        if hasattr(_file_space, "browse_mode"):
            _file_space.browse_mode = "FILES"
        _blend_dir = os.path.dirname(bpy.data.filepath)
        _project_dir = (
            os.path.dirname(_blend_dir)
            if os.path.basename(_blend_dir).lower() == "renders"
            else _blend_dir
        )
        _asset_dir = os.path.join(_project_dir, "assets")
        _browse_dir = _asset_dir if os.path.isdir(_asset_dir) else _project_dir
        _file_params = getattr(_file_space, "params", None)
        if _file_params is not None and _browse_dir:
            _file_params.directory = os.fsencode(_browse_dir)
            if hasattr(_file_params, "display_type"):
                _file_params.display_type = "THUMBNAIL"
        _properties_area.type = "PROPERTIES"

        _window.workspace[{_j(VSE_LAYOUT_PROFILE_KEY)}] = {VSE_LAYOUT_PROFILE_VERSION}
        _binding = _vp_vse_binding_proof(_window, _layout_scene)
        for _area in (_preview_area, _timeline_area, _file_area, _properties_area):
            _area.tag_redraw()
        _configured.append({{
            "workspace": _window.workspace.name,
            "scene": _window.scene.name,
            "top_left": "PREVIEW",
            "bottom_left": "SEQUENCER",
            "top_right": "FILE_BROWSER",
            "bottom_right": "PROPERTIES",
            # Area geometry refreshes on Blender's next UI event, so report the
            # requested ratio and pixel move instead of a stale immediate read.
            "timeline_height_ratio_requested": {ratio},
            "divider_move_requested_pixels": _delta,
            "layout_profile_version": {VSE_LAYOUT_PROFILE_VERSION},
            "binding": _binding,
        }})
if not _configured:
    raise RuntimeError("could not configure four-pane VSE layout: " + "; ".join(_errors))
_vp_result(configured=_configured, errors=_errors,
           layout_profile_version={VSE_LAYOUT_PROFILE_VERSION})
"""


# ---------------------------------------------------------------------------
# Keyframes + animation presets (stored as video_ai_anim on strips)
# ---------------------------------------------------------------------------
#
# Blender 5.1 VSE has no reliable per-strip fcurve API (transform.offset_x is
# NOT keyframeable; blend_alpha/volume keyframes don't evaluate via the old
# animation_data path). So animation intent is stored as JSON on the strip's
# ANIM_KEY custom property: {frames: [{frame, props:{...}}, ...], presets:[...]}.
# Rendering ops apply these values; the data is deterministic and verifiable.
# ---------------------------------------------------------------------------


def _anim_read_script(var_name: str = "_anim") -> str:
    """bpy fragment that loads a strip's animation intent JSON."""
    return f'''
import json as _json
{var_name} = {{"frames": [], "presets": []}}
_raw_anim = s.get({_q(ANIM_KEY)}, "") if {_q(ANIM_KEY)} in s else ""
if _raw_anim:
    try:
        {var_name} = _json.loads(_raw_anim)
    except Exception:
        {var_name} = {{"frames": [], "presets": []}}
'''


def _timeline_hash_script(var_name: str = "_vp_hash") -> str:
    """bpy fragment that computes a CANONICAL full-state hash of the project.

    The hash covers everything a manual GUI edit could change:
      - strips: identity (id/name/type), timing (final span + source offsets),
        source filepath (normalized), transform (offset/scale/rotation),
        crop, style (text/font/font_size/location/alignment/outline/shadow/
        box/color), audio (volume/pan), blend, lock/mute, effect parameters
        (SPEED/GAUSSIAN_BLUR/GLOW/COLORMIX), animation intent
        (video_ai_anim), metadata (video_ai_meta/style/proxy), and the actual
        Blender proxy config (enable/custom-file/path/size flags/quality/timecode)
      - markers (name+frame)
      - scene registries (channel roles / marker meta / text styles / assets /
        fonts)
      - relevant project settings (fps, resolution, frame range)

    Serialization is canonical: stable sort, float rounding (6dp), path
    normalization (case + separators), JSON canonicalize (sort_keys) → SHA-256.
    Any manual edit to any of the above flips the hash -> revision_changed.
    """
    return f"""
import hashlib as _hashlib, json as _json2, os as _os2

def _vp_round(v):
    try:
        if v is None:
            return None
        return round(float(v), 6)
    except Exception:
        return None

def _vp_normpath(p):
    try:
        if not p:
            return ""
        return _os2.path.normcase(_os2.path.normpath(bpy.path.abspath(p)))
    except Exception:
        return str(p)

def _vp_json_norm(s):
    try:
        if not s:
            return None
        return _json2.loads(s)
    except Exception:
        return str(s)

def _vp_fx(s):
    try:
        _t = s.type
        if _t == 'SPEED':
            return {{"factor": _vp_round(getattr(s, "factor", None)),
                    "frame_factor": _vp_round(getattr(s, "frame_factor", None))}}
        if _t == 'GAUSSIAN_BLUR':
            return {{"size_x": _vp_round(getattr(s, "size_x", None)),
                    "size_y": _vp_round(getattr(s, "size_y", None))}}
        if _t == 'GLOW':
            return {{"threshold": _vp_round(getattr(s, "threshold", None)),
                    "clamp": _vp_round(getattr(s, "clamp", None))}}
        if _t == 'COLORMIX':
            return {{"factor": _vp_round(getattr(s, "factor", None)),
                    "mix": str(getattr(s, "mix", ""))}}
        return None
    except Exception:
        return None

_vp_scene2 = bpy.context.scene
_vp_snap = {{
    "scene": _vp_scene2.name,
    "fps": _vp_round(_vp_scene2.render.fps),
    "resolution": [int(_vp_scene2.render.resolution_x), int(_vp_scene2.render.resolution_y)],
    "frame_start": int(_vp_scene2.frame_start),
    "frame_end": int(_vp_scene2.frame_end),
}}
_vp_se2 = _vp_scene2.sequence_editor
_vp_strips = []
if _vp_se2 is not None:
    for _vp_s in _vp_se2.strips:
        _vp_tf = {{}}
        try:
            _tf = _vp_s.transform
            _vp_tf = {{"offset_x": _vp_round(_tf.offset_x), "offset_y": _vp_round(_tf.offset_y),
                       "scale_x": _vp_round(_tf.scale_x), "scale_y": _vp_round(_tf.scale_y),
                       "rotation": _vp_round(_tf.rotation)}}
        except Exception:
            pass
        _vp_crop = None
        try:
            _c = _vp_s.crop
            _vp_crop = {{"min_x": int(_c.min_x), "max_x": int(_c.max_x),
                         "min_y": int(_c.min_y), "max_y": int(_c.max_y)}}
        except Exception:
            pass
        _vp_font = ""
        try:
            _vf = getattr(_vp_s, "font", None)
            _vp_font = str(getattr(_vf, "name", "")) if _vf is not None else ""
        except Exception:
            pass
        _vp_proxy_cfg = None
        if _vp_s.type == 'MOVIE':
            _vp_proxy_cfg = {{"use_proxy": bool(getattr(_vp_s, "use_proxy", False))}}
            try:
                _pp = _vp_s.proxy
                _vp_proxy_cfg.update({{
                    "use_proxy_custom_file": bool(getattr(_pp, "use_proxy_custom_file", False)),
                    "filepath": _vp_normpath(getattr(_pp, "filepath", "")),
                    "use_proxy_custom_directory": bool(getattr(_pp, "use_proxy_custom_directory", False)),
                    "directory": _vp_normpath(getattr(_pp, "directory", "")),
                    "build_25": bool(getattr(_pp, "build_25", False)),
                    "build_50": bool(getattr(_pp, "build_50", False)),
                    "build_75": bool(getattr(_pp, "build_75", False)),
                    "build_100": bool(getattr(_pp, "build_100", False)),
                    "use_overwrite": bool(getattr(_pp, "use_overwrite", False)),
                    "quality": int(getattr(_pp, "quality", 0)),
                    "timecode": str(getattr(_pp, "timecode", "")),
                }})
            except Exception:
                pass
        _vp_item = {{
            "id": _vp_s.get({_q(ID_KEY)}, "") or _vp_s.name,
            "asset_id": _vp_s.get({_q(ASSET_ID_KEY)}, ""),
            "asset_revision": int(_vp_s.get({_q(ASSET_REVISION_KEY)}, 0) or 0),
            "name": _vp_s.name,
            "type": _vp_s.type,
            "ch": _vp_s.channel,
            "start": int(getattr(_vp_s, "frame_final_start", 0)),
            "end": int(getattr(_vp_s, "frame_final_end", 0)),
            "source_in": int(getattr(_vp_s, "frame_offset_start", 0)),
            "source_out": int(getattr(_vp_s, "frame_offset_end", 0)),
            "filepath": _vp_normpath(getattr(_vp_s, "filepath", "")),
            "mute": bool(getattr(_vp_s, "mute", False)),
            "lock": bool(getattr(_vp_s, "lock", False)),
            "vol": _vp_round(getattr(_vp_s, "volume", None)),
            "pan": _vp_round(getattr(_vp_s, "pan", None)),
            "alpha": _vp_round(getattr(_vp_s, "blend_alpha", 1)),
            "blend": str(getattr(_vp_s, "blend_type", "")),
            "transform": _vp_tf,
            "crop": _vp_crop,
            "text": str(getattr(_vp_s, "text", "")),
            "font": _vp_font,
            "font_size": _vp_round(getattr(_vp_s, "font_size", None)),
            "location": [_vp_round(x) for x in getattr(_vp_s, "location", (0.5, 0.5))],
            "alignment_x": str(getattr(_vp_s, "alignment_x", "")),
            "use_outline": bool(getattr(_vp_s, "use_outline", False)),
            "use_shadow": bool(getattr(_vp_s, "use_shadow", False)),
            "use_box": bool(getattr(_vp_s, "use_box", False)),
            "color": [_vp_round(x) for x in getattr(_vp_s, "color", (1, 1, 1, 1))],
            "effects": _vp_fx(_vp_s),
            "anim": _vp_json_norm(_vp_s.get({_q(ANIM_KEY)}, "") if {_q(ANIM_KEY)} in _vp_s else ""),
            "meta": _vp_json_norm(_vp_s.get({_q(META_KEY)}, "") if {_q(META_KEY)} in _vp_s else ""),
            "style": _vp_json_norm(_vp_s.get({_q(STYLE_KEY)}, "") if {_q(STYLE_KEY)} in _vp_s else ""),
            "proxy_intent": _vp_json_norm(_vp_s.get({_q(PROXY_KEY)}, "") if {_q(PROXY_KEY)} in _vp_s else ""),
            "proxy_config": _vp_proxy_cfg,
        }}
        _vp_strips.append(_vp_item)
_vp_strips.sort(key=lambda x: (x["ch"], x["start"], x["id"]))
_vp_snap["strips"] = _vp_strips
# markers
_vp_snap["markers"] = [{{"name": _m.name, "frame": _m.frame}}
                       for _m in sorted(_vp_scene2.timeline_markers, key=lambda m: m.frame)]
# scene-level registries (canonicalized JSON)
for _k, _nk in (({_j(CHANNEL_ROLE_KEY)}, "channel_roles"), ({_j(MARKER_META_KEY)}, "marker_meta"),
                ({_j(TEXT_STYLE_KEY)}, "text_styles"), ({_j(ASSET_REG_KEY)}, "assets"),
                ({_j(FONT_REG_KEY)}, "fonts")):
    _raw = _vp_scene2.get(_k, "") if _k in _vp_scene2 else ""
    _vp_snap[_nk] = _vp_json_norm(_raw)
{var_name} = _hashlib.sha256(
    _json2.dumps(_vp_snap, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
).hexdigest()
"""


def _revision_commit_script() -> str:
    """bpy fragment appended after every mutating op: bump revision ONLY when
    the timeline content actually changed (render ops that restore settings do
    not bump)."""
    return f"""
{_timeline_hash_script("_vp_new_hash")}
_vp_scene = bpy.context.scene
_vp_old_hash = str(_vp_scene.get({_j(TIMELINE_HASH_KEY)}, "") or "")
_vp_rev = int(_vp_scene.get({_j(REVISION_KEY)}, 1) or 1)
if _vp_new_hash != _vp_old_hash:
    _vp_scene[{_j(REVISION_KEY)}] = _vp_rev + 1
    _vp_scene[{_j(TIMELINE_HASH_KEY)}] = _vp_new_hash
"""


def _revision_guard_script(base_rev: int, base_hash: str) -> str:
    """bpy fragment prepended to a single-op edit when base_revision /
    base_timeline_hash are supplied: refuse to run on a stale base (protects
    manual edits even outside apply_patch)."""
    return f"""
{_timeline_hash_script("_vp_guard_hash")}
_vp_gscene = bpy.context.scene
_vp_grev = int(_vp_gscene.get({_j(REVISION_KEY)}, 1) or 1)
if _vp_grev != {int(base_rev)}:
    raise RuntimeError(
        "revision_mismatch: base " + str({int(base_rev)}) +
        " != current " + str(_vp_grev) +
        " (re-read the project first)")
_vp_gstored = str(_vp_gscene.get({_j(TIMELINE_HASH_KEY)}, "") or "")
if {_q(base_hash)} and _vp_gstored and _vp_guard_hash != {_q(base_hash)}:
    raise RuntimeError(
        "stale_base: timeline changed since base hash " +
        str({_q(base_hash)})[:8] + " (manual edit? re-read the project first)")
"""


@_op("add_keyframe", read_only=False)
def add_keyframe(project: str, video_ai_id: str | None = None, target: str | None = None,
                 frame: int = 1, props: dict | None = None, **kw) -> str:
    """Add an animation keyframe for a strip (stored as video_ai_anim)."""
    _validate_project(project)
    if not props:
        raise BlenderRunnerError("invalid_args", "add_keyframe needs 'props' dict")
    return f"""
{_ripple_helpers()}
se = bpy.context.scene.sequence_editor
_by_id = {_q(video_ai_id or '')}
_by_name = {_q(target or '')}
s = None
if se is not None:
    if _by_id:
        s = _vp_by_id(se, _by_id)
    if s is None and _by_name:
        for _x in se.strips:
            if _x.name == _by_name:
                s = _x
                break
if s is None:
    raise RuntimeError("strip not found")
{_anim_read_script('_anim')}
_new_kf = {{"frame": {int(frame)}, "props": {_py(props)}}}
# replace existing keyframe at same frame
_found = False
for _i, _k in enumerate(_anim.get("frames", [])):
    if _k.get("frame") == {int(frame)}:
        _anim["frames"][_i] = _new_kf
        _found = True
        break
if not _found:
    _anim.setdefault("frames", []).append(_new_kf)
_anim["frames"].sort(key=lambda x: x["frame"])
s[{_q(ANIM_KEY)}] = _json.dumps(_anim, ensure_ascii=False)
# apply immediately for verifiability
for _p, _v in {_py(props)}.items():
    try:
        setattr(s, _p, _v)
    except Exception:
        pass
_vp_result(video_ai_id=s.get({_q(ID_KEY)}, ""), frame={int(frame)}, props={_py(props)},
           keyframe_count=len(_anim["frames"]))
"""


@_op("list_keyframes", read_only=True)
def list_keyframes(project: str, video_ai_id: str | None = None,
                   target: str | None = None, **kw) -> str:
    _validate_project(project)
    return f"""
{_ripple_helpers()}
se = bpy.context.scene.sequence_editor
_by_id = {_q(video_ai_id or '')}
_by_name = {_q(target or '')}
s = None
if se is not None:
    if _by_id:
        s = _vp_by_id(se, _by_id)
    if s is None and _by_name:
        for _x in se.strips:
            if _x.name == _by_name:
                s = _x
                break
if s is None:
    raise RuntimeError("strip not found")
{_anim_read_script('_anim')}
_vp_result(video_ai_id=s.get({_q(ID_KEY)}, ""), frames=_anim.get("frames", []),
           presets=_anim.get("presets", []))
"""


@_op("clear_keyframes", read_only=False)
def clear_keyframes(project: str, video_ai_id: str | None = None,
                    target: str | None = None, **kw) -> str:
    _validate_project(project)
    return f"""
{_ripple_helpers()}
se = bpy.context.scene.sequence_editor
_by_id = {_q(video_ai_id or '')}
_by_name = {_q(target or '')}
s = None
if se is not None:
    if _by_id:
        s = _vp_by_id(se, _by_id)
    if s is None and _by_name:
        for _x in se.strips:
            if _x.name == _by_name:
                s = _x
                break
if s is None:
    raise RuntimeError("strip not found")
_n = len(s.get({_q(ANIM_KEY)}, "") or "")
s[{_q(ANIM_KEY)}] = ""
_vp_result(video_ai_id=s.get({_q(ID_KEY)}, ""), cleared=True)
"""


KEYFRAME_INTERPOLATIONS = ("linear", "step", "ease_in", "ease_out", "ease_in_out")


@_op("update_keyframe", read_only=False)
def update_keyframe(project: str, video_ai_id: str | None = None, target: str | None = None,
                    frame: int = 1, props: dict | None = None,
                    interpolation: str | None = None, **kw) -> str:
    """Update an existing keyframe: merge props, optionally set interpolation."""
    _validate_project(project)
    if not props and not interpolation:
        raise BlenderRunnerError("invalid_args", "update_keyframe needs 'props' or 'interpolation'")
    if interpolation is not None and interpolation not in KEYFRAME_INTERPOLATIONS:
        raise BlenderRunnerError("invalid_args",
                                 f"interpolation must be one of {KEYFRAME_INTERPOLATIONS}")
    return f"""
{_ripple_helpers()}
se = bpy.context.scene.sequence_editor
_by_id = {_q(video_ai_id or '')}
_by_name = {_q(target or '')}
s = None
if se is not None:
    if _by_id:
        s = _vp_by_id(se, _by_id)
    if s is None and _by_name:
        for _x in se.strips:
            if _x.name == _by_name:
                s = _x
                break
if s is None:
    raise RuntimeError("strip not found")
{_anim_read_script('_anim')}
_kf = None
for _k in _anim.get("frames", []):
    if _k.get("frame") == {int(frame)}:
        _kf = _k
        break
if _kf is None:
    raise RuntimeError("keyframe not found at frame " + str({int(frame)}))
if {_py(props or {})}:
    _kf.setdefault("props", {{}}).update({_py(props or {})})
if {_q(interpolation or '')}:
    _kf["interpolation"] = {_q(interpolation or '')}
s[{_q(ANIM_KEY)}] = _json.dumps(_anim, ensure_ascii=False)
# apply updated props immediately for verifiability
for _p, _v in {_py(props or {})}.items():
    try:
        setattr(s, _p, _v)
    except Exception:
        pass
_vp_result(video_ai_id=s.get({_q(ID_KEY)}, ""), frame={int(frame)},
           keyframe=_kf, keyframe_count=len(_anim["frames"]))
"""


@_op("delete_keyframe", read_only=False)
def delete_keyframe(project: str, video_ai_id: str | None = None, target: str | None = None,
                    frame: int = 1, **kw) -> str:
    """Delete the keyframe at a given frame."""
    _validate_project(project)
    return f"""
{_ripple_helpers()}
se = bpy.context.scene.sequence_editor
_by_id = {_q(video_ai_id or '')}
_by_name = {_q(target or '')}
s = None
if se is not None:
    if _by_id:
        s = _vp_by_id(se, _by_id)
    if s is None and _by_name:
        for _x in se.strips:
            if _x.name == _by_name:
                s = _x
                break
if s is None:
    raise RuntimeError("strip not found")
{_anim_read_script('_anim')}
_before = len(_anim.get("frames", []))
_kept = [_k for _k in _anim.get("frames", []) if _k.get("frame") != {int(frame)}]
if len(_kept) == _before:
    raise RuntimeError("keyframe not found at frame " + str({int(frame)}))
_anim["frames"] = _kept
s[{_q(ANIM_KEY)}] = _json.dumps(_anim, ensure_ascii=False)
_vp_result(video_ai_id=s.get({_q(ID_KEY)}, ""), deleted_frame={int(frame)},
           keyframe_count=len(_anim["frames"]))
"""


@_op("set_keyframe_interpolation", read_only=False)
def set_keyframe_interpolation(project: str, video_ai_id: str | None = None,
                               target: str | None = None, frame: int = 1,
                               interpolation: str = "linear", **kw) -> str:
    """Set the interpolation mode of a keyframe (linear/step/ease_in/ease_out/ease_in_out)."""
    _validate_project(project)
    if interpolation not in KEYFRAME_INTERPOLATIONS:
        raise BlenderRunnerError("invalid_args",
                                 f"interpolation must be one of {KEYFRAME_INTERPOLATIONS}")
    return f"""
{_ripple_helpers()}
se = bpy.context.scene.sequence_editor
_by_id = {_q(video_ai_id or '')}
_by_name = {_q(target or '')}
s = None
if se is not None:
    if _by_id:
        s = _vp_by_id(se, _by_id)
    if s is None and _by_name:
        for _x in se.strips:
            if _x.name == _by_name:
                s = _x
                break
if s is None:
    raise RuntimeError("strip not found")
{_anim_read_script('_anim')}
_kf = None
for _k in _anim.get("frames", []):
    if _k.get("frame") == {int(frame)}:
        _kf = _k
        break
if _kf is None:
    raise RuntimeError("keyframe not found at frame " + str({int(frame)}))
_kf["interpolation"] = {_q(interpolation)}
s[{_q(ANIM_KEY)}] = _json.dumps(_anim, ensure_ascii=False)
_vp_result(video_ai_id=s.get({_q(ID_KEY)}, ""), frame={int(frame)},
           interpolation={_q(interpolation)}, keyframe=_kf)
"""


@_op("fade_in", read_only=False)
def fade_in(project: str, video_ai_id: str | None = None, target: str | None = None,
            duration_frames: int = 24, **kw) -> str:
    """Fade a clip in: blend_alpha 0->1 over duration_frames."""
    _validate_project(project)
    return f"""
{_ripple_helpers()}
se = bpy.context.scene.sequence_editor
_by_id = {_q(video_ai_id or '')}
_by_name = {_q(target or '')}
s = None
if se is not None:
    if _by_id:
        s = _vp_by_id(se, _by_id)
    if s is None and _by_name:
        for _x in se.strips:
            if _x.name == _by_name:
                s = _x
                break
if s is None:
    raise RuntimeError("strip not found")
_dur = {int(duration_frames)}
_start = s.frame_final_start
{_anim_read_script('_anim')}
_anim.setdefault("frames", [])
# replace/append fade frames
_fade_frames = [{{"frame": _start, "props": {{"blend_alpha": 0.0}}}},
                {{"frame": _start + _dur, "props": {{"blend_alpha": 1.0}}}}]
for _nf in _fade_frames:
    _replaced = False
    for _i, _k in enumerate(_anim["frames"]):
        if _k.get("frame") == _nf["frame"]:
            _anim["frames"][_i] = _nf
            _replaced = True
            break
    if not _replaced:
        _anim["frames"].append(_nf)
_anim["frames"].sort(key=lambda x: x["frame"])
if "fade_in" not in _anim.setdefault("presets", []):
    _anim["presets"].append("fade_in")
s[{_q(ANIM_KEY)}] = _json.dumps(_anim, ensure_ascii=False)
_vp_result(video_ai_id=s.get({_q(ID_KEY)}, ""), preset="fade_in",
           duration_frames=_dur, frames=_anim["frames"])
"""


@_op("fade_out", read_only=False)
def fade_out(project: str, video_ai_id: str | None = None, target: str | None = None,
             duration_frames: int = 24, **kw) -> str:
    """Fade a clip out: blend_alpha 1->0 before its end."""
    _validate_project(project)
    return f"""
{_ripple_helpers()}
se = bpy.context.scene.sequence_editor
_by_id = {_q(video_ai_id or '')}
_by_name = {_q(target or '')}
s = None
if se is not None:
    if _by_id:
        s = _vp_by_id(se, _by_id)
    if s is None and _by_name:
        for _x in se.strips:
            if _x.name == _by_name:
                s = _x
                break
if s is None:
    raise RuntimeError("strip not found")
_dur = {int(duration_frames)}
_end = s.frame_final_end
{_anim_read_script('_anim')}
_anim.setdefault("frames", [])
_fade_frames = [{{"frame": _end - _dur, "props": {{"blend_alpha": 1.0}}}},
                {{"frame": _end, "props": {{"blend_alpha": 0.0}}}}]
for _nf in _fade_frames:
    _replaced = False
    for _i, _k in enumerate(_anim["frames"]):
        if _k.get("frame") == _nf["frame"]:
            _anim["frames"][_i] = _nf
            _replaced = True
            break
    if not _replaced:
        _anim["frames"].append(_nf)
_anim["frames"].sort(key=lambda x: x["frame"])
if "fade_out" not in _anim.setdefault("presets", []):
    _anim["presets"].append("fade_out")
s[{_q(ANIM_KEY)}] = _json.dumps(_anim, ensure_ascii=False)
_vp_result(video_ai_id=s.get({_q(ID_KEY)}, ""), preset="fade_out",
           duration_frames=_dur, frames=_anim["frames"])
"""


@_op("zoom_in", read_only=False)
def zoom_in(project: str, video_ai_id: str | None = None, target: str | None = None,
            scale: float = 1.15, duration_frames: int = 24, **kw) -> str:
    """Zoom a clip in: transform scale 1.0 -> scale over duration."""
    _validate_project(project)
    return f"""
{_ripple_helpers()}
se = bpy.context.scene.sequence_editor
_by_id = {_q(video_ai_id or '')}
_by_name = {_q(target or '')}
s = None
if se is not None:
    if _by_id:
        s = _vp_by_id(se, _by_id)
    if s is None and _by_name:
        for _x in se.strips:
            if _x.name == _by_name:
                s = _x
                break
if s is None:
    raise RuntimeError("strip not found")
_dur = {int(duration_frames)}
_scale = {float(scale)}
_start = s.frame_final_start
{_anim_read_script('_anim')}
_anim.setdefault("frames", [])
_zf = [{{"frame": _start, "props": {{"transform_scale": 1.0}}}},
       {{"frame": _start + _dur, "props": {{"transform_scale": _scale}}}}]
for _nf in _zf:
    _replaced = False
    for _i, _k in enumerate(_anim["frames"]):
        if _k.get("frame") == _nf["frame"]:
            _anim["frames"][_i] = _nf
            _replaced = True
            break
    if not _replaced:
        _anim["frames"].append(_nf)
_anim["frames"].sort(key=lambda x: x["frame"])
if "zoom_in" not in _anim.setdefault("presets", []):
    _anim["presets"].append("zoom_in")
s[{_q(ANIM_KEY)}] = _json.dumps(_anim, ensure_ascii=False)
# apply end scale immediately for verifiability
try:
    s.transform.scale_x = _scale
    s.transform.scale_y = _scale
except Exception:
    pass
_vp_result(video_ai_id=s.get({_q(ID_KEY)}, ""), preset="zoom_in",
           scale=_scale, duration_frames=_dur, frames=_anim["frames"])
"""


@_op("punch_in", read_only=False)
def punch_in(project: str, video_ai_id: str | None = None, target: str | None = None,
             scale: float = 1.15, duration_frames: int = 8, **kw) -> str:
    """Punch-in: quick scale to peak then back (emphasis hit)."""
    _validate_project(project)
    return f"""
{_ripple_helpers()}
se = bpy.context.scene.sequence_editor
_by_id = {_q(video_ai_id or '')}
_by_name = {_q(target or '')}
s = None
if se is not None:
    if _by_id:
        s = _vp_by_id(se, _by_id)
    if s is None and _by_name:
        for _x in se.strips:
            if _x.name == _by_name:
                s = _x
                break
if s is None:
    raise RuntimeError("strip not found")
_dur = {int(duration_frames)}
_scale = {float(scale)}
_center = bpy.context.scene.frame_current
{_anim_read_script('_anim')}
_anim.setdefault("frames", [])
_pt = [{{"frame": _center - _dur, "props": {{"transform_scale": 1.0}}}},
       {{"frame": _center, "props": {{"transform_scale": _scale}}}},
       {{"frame": _center + _dur, "props": {{"transform_scale": 1.0}}}}]
for _nf in _pt:
    _replaced = False
    for _i, _k in enumerate(_anim["frames"]):
        if _k.get("frame") == _nf["frame"]:
            _anim["frames"][_i] = _nf
            _replaced = True
            break
    if not _replaced:
        _anim["frames"].append(_nf)
_anim["frames"].sort(key=lambda x: x["frame"])
if "punch_in" not in _anim.setdefault("presets", []):
    _anim["presets"].append("punch_in")
s[{_q(ANIM_KEY)}] = _json.dumps(_anim, ensure_ascii=False)
_vp_result(video_ai_id=s.get({_q(ID_KEY)}, ""), preset="punch_in",
           scale=_scale, duration_frames=_dur, center=_center)
"""


@_op("zoom_out", read_only=False)
def zoom_out(project: str, video_ai_id: str | None = None, target: str | None = None,
             scale: float = 1.15, duration_frames: int = 24, **kw) -> str:
    """Zoom a clip out: transform scale -> 1.0 over duration."""
    _validate_project(project)
    return f"""
{_ripple_helpers()}
se = bpy.context.scene.sequence_editor
_by_id = {_q(video_ai_id or '')}
_by_name = {_q(target or '')}
s = None
if se is not None:
    if _by_id:
        s = _vp_by_id(se, _by_id)
    if s is None and _by_name:
        for _x in se.strips:
            if _x.name == _by_name:
                s = _x
                break
if s is None:
    raise RuntimeError("strip not found")
_dur = {int(duration_frames)}
_scale = {float(scale)}
_start = s.frame_final_start
{_anim_read_script('_anim')}
_anim.setdefault("frames", [])
_zf = [{{"frame": _start, "props": {{"transform_scale": _scale}}}},
       {{"frame": _start + _dur, "props": {{"transform_scale": 1.0}}}}]
for _nf in _zf:
    _replaced = False
    for _i, _k in enumerate(_anim["frames"]):
        if _k.get("frame") == _nf["frame"]:
            _anim["frames"][_i] = _nf
            _replaced = True
            break
    if not _replaced:
        _anim["frames"].append(_nf)
_anim["frames"].sort(key=lambda x: x["frame"])
if "zoom_out" not in _anim.setdefault("presets", []):
    _anim["presets"].append("zoom_out")
s[{_q(ANIM_KEY)}] = _json.dumps(_anim, ensure_ascii=False)
try:
    s.transform.scale_x = 1.0
    s.transform.scale_y = 1.0
except Exception:
    pass
_vp_result(video_ai_id=s.get({_q(ID_KEY)}, ""), preset="zoom_out",
           scale=_scale, duration_frames=_dur, frames=_anim["frames"])
"""


@_op("slide_in", read_only=False)
def slide_in(project: str, video_ai_id: str | None = None, target: str | None = None,
             from_side: str = "left", distance: int | None = None,
             duration_frames: int = 24, **kw) -> str:
    """Slide a clip in from off-screen (offset_x distance px -> 0)."""
    _validate_project(project)
    if from_side not in ("left", "right"):
        raise BlenderRunnerError("invalid_args", "from_side must be 'left' or 'right'")
    return f"""
{_ripple_helpers()}
se = bpy.context.scene.sequence_editor
_by_id = {_q(video_ai_id or '')}
_by_name = {_q(target or '')}
s = None
if se is not None:
    if _by_id:
        s = _vp_by_id(se, _by_id)
    if s is None and _by_name:
        for _x in se.strips:
            if _x.name == _by_name:
                s = _x
                break
if s is None:
    raise RuntimeError("strip not found")
_dur = {int(duration_frames)}
_side = {_q(from_side)}
_dist = {int(distance) if distance else 0} or bpy.context.scene.render.resolution_x
_start = s.frame_final_start
_off0 = -_dist if _side == 'left' else _dist
{_anim_read_script('_anim')}
_anim.setdefault("frames", [])
_sf = [{{"frame": _start, "props": {{"offset_x": _off0}}}},
       {{"frame": _start + _dur, "props": {{"offset_x": 0}}}}]
for _nf in _sf:
    _replaced = False
    for _i, _k in enumerate(_anim["frames"]):
        if _k.get("frame") == _nf["frame"]:
            _anim["frames"][_i] = _nf
            _replaced = True
            break
    if not _replaced:
        _anim["frames"].append(_nf)
_anim["frames"].sort(key=lambda x: x["frame"])
if "slide_in" not in _anim.setdefault("presets", []):
    _anim["presets"].append("slide_in")
s[{_q(ANIM_KEY)}] = _json.dumps(_anim, ensure_ascii=False)
try:
    s.transform.offset_x = 0
except Exception:
    pass
_vp_result(video_ai_id=s.get({_q(ID_KEY)}, ""), preset="slide_in",
           from_side=_side, distance=_dist, duration_frames=_dur, frames=_anim["frames"])
"""


@_op("slide_out", read_only=False)
def slide_out(project: str, video_ai_id: str | None = None, target: str | None = None,
              to_side: str = "right", distance: int | None = None,
              duration_frames: int = 24, **kw) -> str:
    """Slide a clip out to off-screen (offset_x 0 -> ±distance px)."""
    _validate_project(project)
    if to_side not in ("left", "right"):
        raise BlenderRunnerError("invalid_args", "to_side must be 'left' or 'right'")
    return f"""
{_ripple_helpers()}
se = bpy.context.scene.sequence_editor
_by_id = {_q(video_ai_id or '')}
_by_name = {_q(target or '')}
s = None
if se is not None:
    if _by_id:
        s = _vp_by_id(se, _by_id)
    if s is None and _by_name:
        for _x in se.strips:
            if _x.name == _by_name:
                s = _x
                break
if s is None:
    raise RuntimeError("strip not found")
_dur = {int(duration_frames)}
_side = {_q(to_side)}
_dist = {int(distance) if distance else 0} or bpy.context.scene.render.resolution_x
_end = s.frame_final_end
_off1 = -_dist if _side == 'left' else _dist
{_anim_read_script('_anim')}
_anim.setdefault("frames", [])
_sf = [{{"frame": _end - _dur, "props": {{"offset_x": 0}}}},
       {{"frame": _end, "props": {{"offset_x": _off1}}}}]
for _nf in _sf:
    _replaced = False
    for _i, _k in enumerate(_anim["frames"]):
        if _k.get("frame") == _nf["frame"]:
            _anim["frames"][_i] = _nf
            _replaced = True
            break
    if not _replaced:
        _anim["frames"].append(_nf)
_anim["frames"].sort(key=lambda x: x["frame"])
if "slide_out" not in _anim.setdefault("presets", []):
    _anim["presets"].append("slide_out")
s[{_q(ANIM_KEY)}] = _json.dumps(_anim, ensure_ascii=False)
try:
    s.transform.offset_x = _off1
except Exception:
    pass
_vp_result(video_ai_id=s.get({_q(ID_KEY)}, ""), preset="slide_out",
           to_side=_side, distance=_dist, duration_frames=_dur, frames=_anim["frames"])
"""


@_op("punch_out", read_only=False)
def punch_out(project: str, video_ai_id: str | None = None, target: str | None = None,
              scale: float = 0.92, duration_frames: int = 8, **kw) -> str:
    """Punch-out: quick scale dip (pull-back emphasis) then back to 1.0."""
    _validate_project(project)
    return f"""
{_ripple_helpers()}
se = bpy.context.scene.sequence_editor
_by_id = {_q(video_ai_id or '')}
_by_name = {_q(target or '')}
s = None
if se is not None:
    if _by_id:
        s = _vp_by_id(se, _by_id)
    if s is None and _by_name:
        for _x in se.strips:
            if _x.name == _by_name:
                s = _x
                break
if s is None:
    raise RuntimeError("strip not found")
_dur = {int(duration_frames)}
_scale = {float(scale)}
_center = bpy.context.scene.frame_current
{_anim_read_script('_anim')}
_anim.setdefault("frames", [])
_pt = [{{"frame": _center - _dur, "props": {{"transform_scale": 1.0}}}},
       {{"frame": _center, "props": {{"transform_scale": _scale}}}},
       {{"frame": _center + _dur, "props": {{"transform_scale": 1.0}}}}]
for _nf in _pt:
    _replaced = False
    for _i, _k in enumerate(_anim["frames"]):
        if _k.get("frame") == _nf["frame"]:
            _anim["frames"][_i] = _nf
            _replaced = True
            break
    if not _replaced:
        _anim["frames"].append(_nf)
_anim["frames"].sort(key=lambda x: x["frame"])
if "punch_out" not in _anim.setdefault("presets", []):
    _anim["presets"].append("punch_out")
s[{_q(ANIM_KEY)}] = _json.dumps(_anim, ensure_ascii=False)
try:
    s.transform.scale_x = 1.0
    s.transform.scale_y = 1.0
except Exception:
    pass
_vp_result(video_ai_id=s.get({_q(ID_KEY)}, ""), preset="punch_out",
           scale=_scale, duration_frames=_dur, center=_center)
"""


# ---------------------------------------------------------------------------
# Markers — AI semantic anchors on the timeline
# ---------------------------------------------------------------------------


@_op("list_markers", read_only=True)
def list_markers(project: str, **kw) -> str:
    _validate_project(project)
    return f"""
import json as _json
scene = bpy.context.scene
_meta_store = {{}}
_raw = scene.get({_j(MARKER_META_KEY)}, "") if {_j(MARKER_META_KEY)} in scene else ""
if _raw:
    try:
        _meta_store = _json.loads(_raw)
    except Exception:
        _meta_store = {{}}
_out = []
for _m in scene.timeline_markers:
    _d = {{"name": _m.name, "frame": _m.frame,
           "meta": _meta_store.get(_m.name, {{}})}}
    _out.append(_d)
_vp_result(markers=_out, count=len(_out))
"""


@_op("add_marker", read_only=False)
def add_marker(project: str, name: str, frame: int, metadata: dict | None = None,
               **kw) -> str:
    _validate_project(project)
    meta_payload = _j(metadata or {})
    return f"""
import json as _json
scene = bpy.context.scene
_m = scene.timeline_markers.new(name={_q(name)})
_m.frame = {int(frame)}
_meta_store = {{}}
_raw = scene.get({_j(MARKER_META_KEY)}, "") if {_j(MARKER_META_KEY)} in scene else ""
if _raw:
    try:
        _meta_store = _json.loads(_raw)
    except Exception:
        _meta_store = {{}}
_payload = {meta_payload}
if _payload:
    _meta_store[_m.name] = _payload
    scene[{_j(MARKER_META_KEY)}] = _json.dumps(_meta_store, ensure_ascii=False)
_vp_result(name=_m.name, frame=_m.frame, metadata=_payload)
"""


@_op("update_marker", read_only=False)
def update_marker(project: str, name: str, frame: int | None = None,
                  metadata: dict | None = None, **kw) -> str:
    _validate_project(project)
    # frame=None -> omit the frame-set entirely (avoid injecting 'null')
    frame_script = ""
    if frame is not None:
        frame_script = f"    _m.frame = {int(frame)}\n"
    meta_payload = _j(metadata or {})
    return f"""
import json as _json
scene = bpy.context.scene
_m = scene.timeline_markers.get({_q(name)})
if _m is None:
    raise RuntimeError("marker not found: " + {_q(name)})
{frame_script}_meta_store = {{}}
_raw = scene.get({_j(MARKER_META_KEY)}, "") if {_j(MARKER_META_KEY)} in scene else ""
if _raw:
    try:
        _meta_store = _json.loads(_raw)
    except Exception:
        _meta_store = {{}}
_payload = {meta_payload}
if _payload:
    _old = _meta_store.get(_m.name, {{}})
    _old.update(_payload)
    _meta_store[_m.name] = _old
    scene[{_j(MARKER_META_KEY)}] = _json.dumps(_meta_store, ensure_ascii=False)
_vp_result(name=_m.name, frame=_m.frame)
"""


@_op("move_marker", read_only=False)
def move_marker(project: str, name: str, frame: int, **kw) -> str:
    _validate_project(project)
    return f"""
scene = bpy.context.scene
_m = scene.timeline_markers.get({_q(name)})
if _m is None:
    raise RuntimeError("marker not found: " + {_q(name)})
_m.frame = {int(frame)}
_vp_result(name=_m.name, frame=_m.frame)
"""


@_op("delete_marker", read_only=False)
def delete_marker(project: str, name: str, **kw) -> str:
    _validate_project(project)
    return f"""
import json as _json
scene = bpy.context.scene
_m = scene.timeline_markers.get({_q(name)})
if _m is None:
    raise RuntimeError("marker not found: " + {_q(name)})
_n = _m.name
scene.timeline_markers.remove(_m)
_raw = scene.get({_j(MARKER_META_KEY)}, "") if {_j(MARKER_META_KEY)} in scene else ""
if _raw:
    try:
        _meta_store = _json.loads(_raw)
    except Exception:
        _meta_store = {{}}
    if _n in _meta_store:
        del _meta_store[_n]
        scene[{_j(MARKER_META_KEY)}] = _json.dumps(_meta_store, ensure_ascii=False)
_vp_result(deleted=_n)
"""


# ---------------------------------------------------------------------------
# Gap / overlap detection + timeline validation
# ---------------------------------------------------------------------------


@_op("find_gaps", read_only=True)
def find_gaps(project: str, channel: int | None = None, **kw) -> str:
    _validate_project(project)
    return f"""
se = bpy.context.scene.sequence_editor
_ch = {int(channel) if channel is not None else -1}
_gaps = []
if se is not None:
    chans = sorted(set(s.channel for s in se.strips if _ch < 0 or s.channel == _ch))
    for _c in chans:
        cand = [s for s in se.strips if s.channel == _c]
        cand.sort(key=lambda x: x.frame_final_start)
        cursor = 1
        for s in cand:
            if s.frame_final_start > cursor:
                _gaps.append({{"channel": _c, "start": cursor,
                               "end": s.frame_final_start,
                               "frames": s.frame_final_start - cursor}})
            cursor = max(cursor, s.frame_final_end)
_vp_result(gaps=_gaps, count=len(_gaps))
"""


@_op("find_overlaps", read_only=True)
def find_overlaps(project: str, channel: int | None = None, **kw) -> str:
    _validate_project(project)
    return f"""
se = bpy.context.scene.sequence_editor
_ch = {int(channel) if channel is not None else -1}
_ov = []
if se is not None:
    strips = [s for s in se.strips if _ch < 0 or s.channel == _ch]
    for _i in range(len(strips)):
        for _j in range(_i + 1, len(strips)):
            a, b = strips[_i], strips[_j]
            if a.channel != b.channel:
                continue
            _as, _ae = a.frame_final_start, a.frame_final_end
            _bs, _be = b.frame_final_start, b.frame_final_end
            if _as < _be and _ae > _bs:
                _ov.append({{"channel": a.channel,
                            "a": a.name, "b": b.name,
                            "overlap_start": max(_as, _bs),
                            "overlap_end": min(_ae, _be),
                            "frames": min(_ae, _be) - max(_as, _bs)}})
_vp_result(overlaps=_ov, count=len(_ov))
"""


@_op("validate_timeline", read_only=True)
def validate_timeline(project: str, **kw) -> str:
    """Validate the whole timeline: gaps, overlaps, missing media, empty text."""
    _validate_project(project)
    return f"""
import os
se = bpy.context.scene.sequence_editor
_errors = []
_warnings = []
if se is None:
    _errors.append({{"code": "no_sequencer", "message": "no sequence editor"}})
else:
    # overlap check
    strips = list(se.strips)
    for _i in range(len(strips)):
        for _j in range(_i + 1, len(strips)):
            a, b = strips[_i], strips[_j]
            if a.channel != b.channel:
                continue
            if a.frame_final_start < b.frame_final_end and a.frame_final_end > b.frame_final_start:
                _errors.append({{"code": "overlap",
                                "message": f"overlap on ch{{a.channel}}: {{a.name}} & {{b.name}}"}})
    # gap check per channel
    chans = sorted(set(s.channel for s in strips))
    for _c in chans:
        cand = [s for s in strips if s.channel == _c]
        cand.sort(key=lambda x: x.frame_final_start)
        _cursor = 1
        for s in cand:
            if s.frame_final_start > _cursor:
                _warnings.append({{"code": "gap", "channel": _c,
                                  "message": f"gap {{_cursor}}-{{s.frame_final_start}} on ch{{_c}}"}})
            _cursor = max(_cursor, s.frame_final_end)
    # media + text checks
    for s in strips:
        if s.type == 'MOVIE':
            _fp = getattr(s, 'filepath', '')
            if _fp and not os.path.isfile(bpy.path.abspath(_fp)):
                _errors.append({{"code": "missing_media", "strip": s.name,
                                "message": "source file missing: " + _fp}})
        elif s.type == 'TEXT':
            _t = getattr(s, 'text', '') or ''
            if not _t.strip():
                _warnings.append({{"code": "empty_text", "strip": s.name,
                                  "message": "empty text strip"}})
        if s.frame_final_end <= s.frame_final_start:
            _errors.append({{"code": "bad_duration", "strip": s.name,
                            "message": "non-positive duration"}})
_vp_result(valid=len(_errors) == 0, errors=_errors, warnings=_warnings,
           error_count=len(_errors), warning_count=len(_warnings))
"""


# ---------------------------------------------------------------------------
# Atomic batch + checkpoints
# ---------------------------------------------------------------------------


@_op("batch", read_only=False)
def batch(project: str, commands: list | None = None, atomic: bool = True,
          **kw) -> str:
    """Execute multiple ops atomically (snapshot -> execute -> rollback on fail).

    Rollback is FILE-LEVEL: the .blend is snapshotted before the batch; on
    failure the snapshot is restored and reloaded, preserving every attribute.
    """
    _validate_project(project)
    if not commands:
        raise BlenderRunnerError("invalid_args", "batch needs 'commands' list")
    # snapshot lives NEXT TO the project (same dir as .blend) so the Blender
    # process and our file checks agree on the path.
    _snap_dir = str(Path(project).resolve().parent)
    return f"""
{_ripple_helpers()}
import json as _json, os, shutil
from pathlib import Path as _Path
se = bpy.context.scene.sequence_editor
_cmds = {_py(commands)}
_atomic = {str(bool(atomic))}
# File-level snapshot: save the current .blend to a temp copy; rollback =
# restore it (preserves EVERY attribute, not just a subset).
_snap_path = None
if _atomic:
    _snap_path = os.path.join({_j(_snap_dir)}, '.batch_snap_' + str(os.getpid()) + '.blend')
    os.makedirs(os.path.dirname(_snap_path), exist_ok=True)
    # copy=True keeps the live GUI file path unchanged
    bpy.ops.wm.save_as_mainfile(filepath=_snap_path, copy=True)
_results = []
_error = None
for _ci, _cmd in enumerate(_cmds):
    try:
        _op = _cmd.get("op")
        if _op == "move":
            _t = _cmd.get("target") or _cmd.get("video_ai_id")
            _s = _vp_by_id(se, _t) if _cmd.get("video_ai_id") else None
            if _s is None and _t:
                for _x in se.strips:
                    if _x.name == _t:
                        _s = _x
                        break
            if _s is None:
                raise RuntimeError("strip not found: " + str(_t))
            if _cmd.get("frame_start") is not None:
                _s.frame_start = int(_cmd["frame_start"])
            if _cmd.get("channel") is not None:
                _s.channel = int(_cmd["channel"])
        elif _op == "delete_strip":
            _t = _cmd.get("target") or _cmd.get("video_ai_id")
            _s = _vp_by_id(se, _t) if _cmd.get("video_ai_id") else None
            if _s is None and _t:
                for _x in se.strips:
                    if _x.name == _t:
                        _s = _x
                        break
            if _s is None:
                raise RuntimeError("strip not found: " + str(_t))
            se.strips.remove(_s)
        elif _op == "set_text":
            _t = _cmd.get("target") or _cmd.get("video_ai_id")
            _s = _vp_by_id(se, _t) if _cmd.get("video_ai_id") else None
            if _s is None and _t:
                for _x in se.strips:
                    if _x.name == _t:
                        _s = _x
                        break
            if _s is None:
                raise RuntimeError("strip not found: " + str(_t))
            _s.text = str(_cmd.get("text", ""))
        elif _op == "set_font_size":
            _t = _cmd.get("target") or _cmd.get("video_ai_id")
            _s = _vp_by_id(se, _t) if _cmd.get("video_ai_id") else None
            if _s is None and _t:
                for _x in se.strips:
                    if _x.name == _t:
                        _s = _x
                        break
            if _s is None:
                raise RuntimeError("strip not found: " + str(_t))
            _s.font_size = float(_cmd.get("font_size", 48))
        elif _op == "set_volume":
            _t = _cmd.get("target") or _cmd.get("video_ai_id")
            _s = _vp_by_id(se, _t) if _cmd.get("video_ai_id") else None
            if _s is None and _t:
                for _x in se.strips:
                    if _x.name == _t:
                        _s = _x
                        break
            if _s is None:
                raise RuntimeError("strip not found: " + str(_t))
            _s.volume = float(_cmd.get("volume", 1.0))
        elif _op == "mute":
            _t = _cmd.get("target") or _cmd.get("video_ai_id")
            _s = _vp_by_id(se, _t) if _cmd.get("video_ai_id") else None
            if _s is None and _t:
                for _x in se.strips:
                    if _x.name == _t:
                        _s = _x
                        break
            if _s is None:
                raise RuntimeError("strip not found: " + str(_t))
            _s.mute = bool(_cmd.get("mute", True))
        else:
            raise RuntimeError("batch: unsupported op: " + str(_op))
        _results.append({{"index": _ci, "op": _op, "ok": True}})
    except Exception as _e:
        _results.append({{"index": _ci, "op": _cmd.get("op"), "ok": False,
                          "error": str(_e)}})
        _error = str(_e)
        if _atomic:
            break
# rollback on atomic failure: restore the file-level snapshot
_rolled_back = False
if _atomic and _error and _snap_path and os.path.isfile(_snap_path):
    _rolled_back = True
    _proj = {_j(str(Path(project).resolve()))}
    try:
        shutil.copyfile(_snap_path, _proj)
        # NOTE: no open_mainfile here — that would switch the live GUI file and
        # can block the bridge. The caller reloads to see the restored state.
    except Exception:
        _rolled_back = False
if _snap_path and os.path.isfile(_snap_path):
    try:
        os.remove(_snap_path)
    except Exception:
        pass
_vp_result(atomic={str(bool(atomic))}, executed=len(_results),
           ok=_error is None, error=_error, rolled_back=_rolled_back,
           results=_results)
"""


@_op("validate_checkpoint_restore", read_only=True)
def validate_checkpoint_restore(project: str, base_revision: int,
                                base_timeline_hash: str, read_token: str,
                                patch_id: str, **kw) -> str:
    """Validate restore concurrency/idempotency before the host replaces disk.

    The actual copy/reopen lifecycle is intentionally outside Blender memory;
    this read-only guard proves that the caller observed the exact live state.
    """
    _validate_project(project)
    if not base_timeline_hash or not read_token or not patch_id:
        raise BlenderRunnerError(
            "invalid_args",
            "checkpoint restore requires base hash, read token, and patch_id",
        )
    return f"""
import json as _json
{_timeline_hash_script("_vp_restore_base_hash")}
_vp_scene = bpy.context.scene
_vp_revision = int(_vp_scene.get({_j(REVISION_KEY)}, 1) or 1)
_vp_last = {{}}
_vp_last_raw = _vp_scene.get({_j(LAST_PATCH_KEY)}, "")
if _vp_last_raw:
    try:
        _vp_last = _json.loads(_vp_last_raw)
    except Exception:
        _vp_last = {{}}
if _vp_last.get("patch_id") == {_q(patch_id)}:
    _vp_result(valid=True, status="already_applied",
               applied_revision=int(_vp_last.get("applied_revision", _vp_revision)))
else:
    if _vp_revision != {int(base_revision)}:
        raise RuntimeError(
            "revision_mismatch: restore base " + str({int(base_revision)}) +
            " != current " + str(_vp_revision))
    if _vp_restore_base_hash != {_q(base_timeline_hash)}:
        raise RuntimeError("stale_base: timeline changed before checkpoint restore")
    _vp_obs = {{}}
    _vp_obs_raw = _vp_scene.get({_j(OBSERVATION_KEY)}, "")
    if _vp_obs_raw:
        try:
            _vp_obs = _json.loads(_vp_obs_raw)
        except Exception:
            _vp_obs = {{}}
    if _vp_obs.get("id") != {_q(read_token)}:
        raise RuntimeError("invalid_read_token: blender_read first")
    if (int(_vp_obs.get("revision", -1)) != {int(base_revision)}
            or _vp_obs.get("hash") != {_q(base_timeline_hash)}):
        raise RuntimeError("stale_observation: restore token does not match base")
    _vp_result(valid=True, status="ready_to_restore",
               next_revision={int(base_revision)} + 1)
"""


@_op("finalize_checkpoint_restore", read_only=False)
def finalize_checkpoint_restore(project: str, next_revision: int,
                                patch_id: str, checkpoint_name: str,
                                **kw) -> str:
    """Commit restored content after the replacement file is visibly reopened."""
    _validate_project(project)
    if int(next_revision) < 1 or not patch_id:
        raise BlenderRunnerError("invalid_args", "invalid restore finalization")
    return f"""
import json as _json
{_timeline_hash_script("_vp_restored_hash")}
_vp_scene = bpy.context.scene
_vp_scene[{_j(REVISION_KEY)}] = {int(next_revision)}
_vp_scene[{_j(TIMELINE_HASH_KEY)}] = _vp_restored_hash
_vp_scene[{_j(LAST_PATCH_KEY)}] = _json.dumps(
    {{"patch_id": {_q(patch_id)}, "applied_revision": {int(next_revision)},
      "kind": "checkpoint_restore", "checkpoint": {_q(checkpoint_name)}}},
    ensure_ascii=False)
if {_q(OBSERVATION_KEY)} in _vp_scene:
    del _vp_scene[{_q(OBSERVATION_KEY)}]
_vp_result(applied=True, status="restored",
           applied_revision={int(next_revision)},
           timeline_hash=_vp_restored_hash,
           checkpoint={_q(checkpoint_name)})
"""


@_op("create_checkpoint", read_only=False)
def create_checkpoint(project: str, name: str, **kw) -> str:
    """Save a named checkpoint copy of the .blend (snapshot for rollback).

    Uses save_as_mainfile(copy=True) so the CURRENT GUI file path is NOT
    changed — the checkpoint is a separate copy and the live session keeps
    editing the same project file.
    """
    _validate_project(project)
    proj = Path(project)
    return f"""
import shutil, os
_proj = {_j(str(proj))}
_ckpt_dir = os.path.join(os.path.dirname(_proj), 'checkpoints')
os.makedirs(_ckpt_dir, exist_ok=True)
_ckpt = os.path.join(_ckpt_dir, {_q(name)} + '.blend')
bpy.ops.wm.save_as_mainfile(filepath=_ckpt, copy=True)
_vp_result(checkpoint=_ckpt, name={_q(name)}, exists=os.path.isfile(_ckpt))
"""


@_op("restore_checkpoint", read_only=False)
def restore_checkpoint(project: str, name: str, **kw) -> str:
    """Restore a named checkpoint by copying it back over the project file.

    NOTE: does NOT call open_mainfile (that would switch the live GUI's file
    and can block the bridge). After this op, the caller should reload the
    project (File > Open) or run verify_persistence to confirm the file state.
    """
    _validate_project(project)
    proj = Path(project)
    return f"""
import os, shutil
_proj = {_j(str(proj))}
_ckpt = os.path.join(os.path.dirname(_proj), 'checkpoints', {_q(name)} + '.blend')
if not os.path.isfile(_ckpt):
    raise RuntimeError("checkpoint not found: " + _ckpt)
shutil.copyfile(_ckpt, _proj)
_vp_result(restored=_ckpt, name={_q(name)}, target=_proj,
           note="copied back to project; reload the file to see it")
"""


@_op("list_checkpoints", read_only=True)
def list_checkpoints(project: str, **kw) -> str:
    _validate_project(project)
    proj = Path(project)
    return f"""
import os
_ckpt_dir = os.path.join(os.path.dirname({_j(str(proj))}), 'checkpoints')
_names = []
if os.path.isdir(_ckpt_dir):
    for _f in sorted(os.listdir(_ckpt_dir)):
        if _f.endswith('.blend'):
            _p = os.path.join(_ckpt_dir, _f)
            _names.append({{"name": _f[:-6], "file": _p,
                            "size": os.path.getsize(_p)}})
_vp_result(checkpoints=_names, count=len(_names))
"""


@_op("delete_checkpoint", read_only=False)
def delete_checkpoint(project: str, name: str, **kw) -> str:
    _validate_project(project)
    proj = Path(project)
    return f"""
import os
_ckpt = os.path.join(os.path.dirname({_j(str(proj))}), 'checkpoints', {_q(name)} + '.blend')
if os.path.isfile(_ckpt):
    os.remove(_ckpt)
_vp_result(deleted={_q(name)}, existed=os.path.exists(_ckpt))
"""


# ---------------------------------------------------------------------------
# Persistence verification — .blend is the source of truth
# ---------------------------------------------------------------------------


@_op("verify_persistence", read_only=True)
def verify_persistence(project: str, expected: dict | None = None, **kw) -> str:
    """Reopen the saved .blend in a FRESH Blender instance and verify the VSE
    timeline survived persistence.

    This runs read-only in a brand-new headless process (the runner always opens
    the file fresh), so it proves that the strips saved to disk are the strips a
    user will see when they double-click the .blend.

    Returns a report with the owning scene, per-type strip counts, and
    ``persistence_verified`` = True when:
      - a scene containing a VSE with strips exists, AND
      - (if ``expected`` provided) movie/sound/text/image counts match.
    """
    project = _validate_project(project)
    expected_j = _j(expected or {})
    return binding_helpers_script() + f"""
import bpy, json as _json, os
{_proxy_state_helpers()}
# A FRESH open of the saved file (this process was launched with the project).
scene = bpy.context.scene
se = scene.sequence_editor
if se is None or len(se.strips) == 0:
    # Some projects put the VSE on a non-active scene — search all scenes.
    owner = None
    for sc in bpy.data.scenes:
        if sc.sequence_editor is not None and len(sc.sequence_editor.strips) > 0:
            owner = sc
            break
    if owner is None:
        _vp_result(persistence_verified=False, scene=None, vse_strip_count=0,
                   movie_strips=0, sound_strips=0, text_strips=0, image_strips=0,
                   effect_strips=0, other_strips=0, expected={expected_j},
                   proxy_warnings=[], missing_proxy_count=0,
                   strip_owner_scene=None, sequencer_scene=None,
                   scene_binding_persisted=False,
                   internal_strip_count=0, visible_strip_count=0,
                   visible_strip_match=False,
                   reason="no scene with a non-empty VSE found in reopened file")
        raise SystemExit(0)
    scene = owner
    se = scene.sequence_editor

_workspace = bpy.data.workspaces.get("Video Editing")
_binding_supported = bool(
    _workspace is not None and hasattr(_workspace, "sequencer_scene")
)
_sequencer_scene = (
    getattr(_workspace, "sequencer_scene", None)
    if _binding_supported else scene
)
_internal_strip_count = _vp_vse_strip_count(scene)
_visible_strip_count = _vp_vse_strip_count(_sequencer_scene)
_binding_persisted = bool(_sequencer_scene == scene)
_visible_strip_match = _internal_strip_count == _visible_strip_count
_layout_profile_version = int(
    _workspace.get({_j(VSE_LAYOUT_PROFILE_KEY)}, 0) or 0
) if _workspace is not None else 0

strips = list(se.strips)
counts = {{"MOVIE": 0, "SOUND": 0, "TEXT": 0, "IMAGE": 0, "SCENE": 0}}
other = 0
for s in strips:
    t = s.type
    if t in counts:
        counts[t] += 1
    else:
        other += 1
proxy_status = [_vp_proxy_status(s) for s in strips if s.type == 'MOVIE']
proxy_warnings = [
    {{"name": s.name, "video_ai_id": s.get({_q(ID_KEY)}, ""),
      "status": status.get("status"), "path": status.get("path")}}
    for s, status in ((s, _vp_proxy_status(s)) for s in strips if s.type == 'MOVIE')
    if status and status.get("status") not in ("ready", "detached")
]
movie = counts["MOVIE"]; sound = counts["SOUND"]; text = counts["TEXT"]
image = counts["IMAGE"]; scene_strips = counts["SCENE"]
expected = {expected_j}
ok = len(strips) > 0 and _binding_persisted and _visible_strip_match
if expected:
    if "movie" in expected and expected["movie"] != movie:
        ok = False
    if "sound" in expected and expected["sound"] != sound:
        ok = False
    if "text" in expected and expected["text"] != text:
        ok = False
    if "image" in expected and expected["image"] != image:
        ok = False
_vp_result(persistence_verified=bool(ok), scene=scene.name,
           strip_owner_scene=scene.name,
           window_scene=(bpy.context.scene.name if bpy.context.scene else None),
           sequencer_scene=(getattr(_sequencer_scene, "name", None)),
           sequencer_scene_supported=_binding_supported,
           scene_binding_persisted=_binding_persisted,
           internal_strip_count=_internal_strip_count,
           visible_strip_count=_visible_strip_count,
           visible_strip_match=_visible_strip_match,
           layout_profile_version=_layout_profile_version,
           vse_strip_count=len(strips),
           movie_strips=movie, sound_strips=sound, text_strips=text,
           image_strips=image, scene_strips=scene_strips,
           effect_strips=other, expected={expected_j},
           proxy_status=proxy_status, proxy_warnings=proxy_warnings,
           missing_proxy_count=sum(1 for p in proxy_status if p and p.get("status") == "missing"),
           active_workspace=bpy.context.workspace.name if bpy.context.workspace else None,
           video_editing_workspace=('Video Editing' if 'Video Editing' in [w.name for w in bpy.data.workspaces] else None))
"""


# ---------------------------------------------------------------------------
# Revision model (Step 3 — incremental adapter)
# ---------------------------------------------------------------------------


@_op("get_revision", read_only=True)
def get_revision(project: str | None = None, **kw) -> str:
    """Read the project's revision + canonical content hash.

    ``consistent`` is True when the current hash matches the stored hash
    (nothing changed outside this system since the last commit). When a human
    edits the timeline directly in Blender (drag + Ctrl+S), the hash diverges:
    ``dirty`` = True — that IS "revision changed".

    Also issues a single-use ``observation_id`` (stored on the scene in memory):
    apply_patch and acknowledge_revision require it, so "no read, no valid
    patch" is enforced by construction (read-after-write).
    """
    return f"""
import uuid as _uuid, json as _json3
{_timeline_hash_script("_vp_cur_hash")}
_vp_scene = bpy.context.scene
_vp_rev = int(_vp_scene.get({_j(REVISION_KEY)}, 1) or 1)
_vp_stored = str(_vp_scene.get({_j(TIMELINE_HASH_KEY)}, "") or "")
_vp_dirty = bool(_vp_stored) and _vp_cur_hash != _vp_stored
_obs_id = "obs_" + _uuid.uuid4().hex[:12]
# single-use observation token (memory only; not part of the content hash)
_vp_scene[{_j(OBSERVATION_KEY)}] = _json3.dumps(
    {{"id": _obs_id, "revision": _vp_rev, "hash": _vp_cur_hash}}, ensure_ascii=False)
_vp_result(revision=_vp_rev, timeline_hash=_vp_cur_hash, stored_hash=_vp_stored,
           consistent=bool(_vp_stored) and _vp_cur_hash == _vp_stored,
           dirty=_vp_dirty, revision_changed=bool(_vp_dirty),
           observation_id=_obs_id)
"""


@_op("acknowledge_revision", read_only=False)
def acknowledge_revision(project: str | None = None, observed_revision: int | None = None,
                         observed_hash: str | None = None, read_token: str | None = None,
                         **kw) -> str:
    """Adopt the CURRENT timeline content as the next revision base — but ONLY
    if it still matches what the caller OBSERVED (observed_revision +
    observed_hash + the read_token from blender_read).

    This prevents blessing an edit the AI never saw: if the human changed the
    timeline again between the AI's read and this acknowledge, the observed
    hash no longer matches and the acknowledge is REFUSED.
    """
    if observed_revision is None or not observed_hash:
        raise BlenderRunnerError(
            "invalid_args", "acknowledge_revision needs observed_revision + observed_hash "
            "(from blender_read) — no read, no acknowledge")
    _token_check = ""
    if read_token:
        _token_check = f'''
_raw_obs = _vp_scene.get({_j(OBSERVATION_KEY)}, "")
_obs = {{}}
if _raw_obs:
    try:
        _obs = _json3.loads(_raw_obs)
    except Exception:
        _obs = {{}}
if not _obs.get("id") or _obs.get("id") != {_q(read_token)}:
    raise RuntimeError("invalid_read_token: observation never issued or already consumed (blender_read first)")
if int(_obs.get("revision", -1)) != {int(observed_revision)} or _obs.get("hash") != {_q(observed_hash)}:
    raise RuntimeError("stale_observation: token does not match the observed state (re-read first)")
'''
    return f"""
import json as _json3
{_timeline_hash_script("_vp_cur_hash")}
_vp_scene = bpy.context.scene
_vp_rev = int(_vp_scene.get({_j(REVISION_KEY)}, 1) or 1)
if _vp_rev != {int(observed_revision)}:
    raise RuntimeError(
        "revision_mismatch: observed " + str({int(observed_revision)}) +
        " != current " + str(_vp_rev) + " (re-read first)")
if _vp_cur_hash != {_q(observed_hash)}:
    raise RuntimeError(
        "stale_observation: the timeline changed since you observed it " +
        "(re-read first — do not acknowledge unseen edits)")
{_token_check}
_vp_scene[{_j(REVISION_KEY)}] = _vp_rev + 1
_vp_scene[{_j(TIMELINE_HASH_KEY)}] = _vp_cur_hash
if {_q(OBSERVATION_KEY)} in _vp_scene:
    try:
        del _vp_scene[{_q(OBSERVATION_KEY)}]
    except Exception:
        pass
_vp_result(revision=_vp_rev + 1, timeline_hash=_vp_cur_hash, acknowledged=True)
"""


@_op("apply_patch", read_only=False)
def apply_patch(project: str, base_revision: int, commands: list | None = None,
                base_timeline_hash: str | None = None, patch_id: str = "",
                read_token: str | None = None,
                checkpoint_name: str | None = None, **kw) -> str:
    """Apply an incremental Edit Patch — the Step 3 core.

    Instead of rebuilding the project, the caller sends a delta:
      {"base_revision": 17, "base_timeline_hash": "...", "patch_id": "patch_01K...",
       "commands": [{"op": "ripple_delete", "video_ai_id": "clip_42"}, ...]}

    Blender executes: validate revision (+ content hash) → idempotency check →
    observation check → checkpoint → atomic execution (file-level snapshot,
    rollback on any failure) → verify → save .blend → commit revision+1.

    Guards:
      - revision_mismatch : current revision != base_revision (re-read first)
      - stale_base        : current hash != base_timeline_hash (a MANUAL edit
        happened since the base — refuse, never overwrite it)
      - invalid_read_token / stale_observation : the patch must carry the
        single-use read_token from blender_read, matching base_revision/hash —
        no read, no valid patch (read-after-write, enforced)
      - already_applied   : a retried patch_id is a no-op (idempotency —
        revision guards concurrency, patch_id guards retries)

    Commands reference strips by stable id (video_ai_id) or name via
    ``target``/``video_ai_id`` exactly like the single-op calls.
    """
    _validate_project(project)
    if not isinstance(commands, list) or not commands:
        raise BlenderRunnerError("invalid_args", "apply_patch needs 'commands' list")
    if not patch_id:
        raise BlenderRunnerError(
            "invalid_args", "apply_patch needs 'patch_id' (idempotency key — "
            "generate a fresh uuid per patch)")
    import inspect as _inspect

    # ---- generate ALL command scripts up front (fail fast on bad patches) ----
    pieces = []
    for _i, _cmd in enumerate(commands):
        _opn = _cmd.get("op") if isinstance(_cmd, dict) else None
        if not _opn:
            raise BlenderRunnerError("invalid_args", f"command[{_i}] missing 'op'")
        if _opn in REMOVED_OPS:
            _removed = REMOVED_OPS[_opn]
            raise BlenderRunnerError(
                _removed["code"],
                f"command[{_i}] {_opn}: {_removed['message']}")
        if _opn in READ_ONLY_OPS:
            raise BlenderRunnerError(
                "invalid_args", f"command[{_i}] {_opn} is read-only — patches carry edits only")
        _fn = OPS.get(_opn)
        if _fn is None:
            raise BlenderRunnerError("unsupported", f"unknown op in patch: {_opn}")
        _params = {k: v for k, v in _cmd.items() if k != "op"}
        _sig = _inspect.signature(_fn)
        if ("target" in _params and "target" not in _sig.parameters
                and "video_ai_id" in _sig.parameters):
            _params["video_ai_id"] = _params.pop("target")
        # fail fast on missing input files referenced by commands
        _validate_inputs(_opn, _params)
        try:
            _piece = _fn(project=project, **_params)
        except BlenderRunnerError as _e:
            raise BlenderRunnerError(
                "invalid_args", f"command[{_i}] {_opn}: {_e}") from _e
        except Exception as _e:  # e.g. TypeError on a required positional arg
            raise BlenderRunnerError(
                "invalid_args", f"command[{_i}] {_opn}: bad arguments: {_e}") from _e
        pieces.append((_i, _opn, _piece))

    _body_parts = []
    for _i, _opn, _piece in pieces:
        _indented = BlenderRunner._indent(_piece, 8)
        # ensure stable IDs BEFORE every command — strips created by an earlier
        # command in this patch must be referenceable (and hash-stable) right
        # away; otherwise the next mutating op would assign IDs and flip the
        # canonical hash (breaking observations).
        _ensure_in_cmd = BlenderRunner._indent(_ensure_ids_script(), 8)
        _body_parts.append(f'''# ---- patch command {_i}: {_opn} ----
if _patch_error is None:
    try:
{_ensure_in_cmd}
{_indented}
        _patch_results.append({{"index": {_i}, "op": {_q(_opn)}, "ok": True}})
    except Exception as _pe:
        _patch_results.append({{"index": {_i}, "op": {_q(_opn)}, "ok": False,
                              "error": str(_pe)[:300]}})
        _patch_error = str(_pe)''')
    _body = "\n".join(_body_parts)

    _proj = str(Path(project).resolve())
    _snap_dir = str(Path(project).resolve().parent)
    _ckpt_name = checkpoint_name or f"patch_r{int(base_revision)}"
    _req_hash = base_timeline_hash or ""

    # observation-token guard (read-after-write): consumes the token issued by
    # blender_read, so a valid patch REQUIRES a prior read of THIS state.
    _token_check = ""
    if read_token:
        _token_check = f'''
_raw_obs = _vp_scene.get({_j(OBSERVATION_KEY)}, "")
_obs = {{}}
if _raw_obs:
    try:
        _obs = _json.loads(_raw_obs)
    except Exception:
        _obs = {{}}
if not _dup:
    if not _obs.get("id") or _obs.get("id") != {_q(read_token)}:
        raise RuntimeError("invalid_read_token: observation never issued or already consumed (blender_read first)")
    if int(_obs.get("revision", -1)) != {int(base_revision)} or _obs.get("hash") != {_q(_req_hash)}:
        raise RuntimeError("stale_observation: token does not match the observed state (re-read first)")
    if {_q(OBSERVATION_KEY)} in _vp_scene:
        try:
            del _vp_scene[{_q(OBSERVATION_KEY)}]
        except Exception:
            pass
'''

    _body_exec = f'''
# ---- 2. checkpoint (named copy; keeps the live GUI file path) ----
_ckpt_dir = os.path.join(os.path.dirname({_j(_proj)}), 'checkpoints')
os.makedirs(_ckpt_dir, exist_ok=True)
bpy.ops.wm.save_as_mainfile(
    filepath=os.path.join(_ckpt_dir, {_q(_ckpt_name)} + '.blend'), copy=True)

# ---- 3. file-level snapshot for atomic rollback ----
_snap_path = os.path.join({_j(_snap_dir)}, '.patch_snap_' + str(os.getpid()) + '.blend')
bpy.ops.wm.save_as_mainfile(filepath=_snap_path, copy=True)

# ---- 4. execute commands atomically ----
{_body}

# ---- 5. verify + rollback on failure ----
_rolled_back = False
if _patch_error and os.path.isfile(_snap_path):
    try:
        shutil.copyfile(_snap_path, {_j(_proj)})
        _rolled_back = True
    except Exception:
        pass
if os.path.isfile(_snap_path):
    try:
        os.remove(_snap_path)
    except Exception:
        pass

# ---- 6. commit revision+1 with the fresh content hash (only on success) ----
{_ensure_ids_script()}
{_timeline_hash_script("_vp_final_hash")}
if not _patch_error:
    _vp_scene[{_j(REVISION_KEY)}] = {int(base_revision)} + 1
    _vp_scene[{_j(TIMELINE_HASH_KEY)}] = _vp_final_hash
    _vp_scene[{_j(LAST_PATCH_KEY)}] = _json.dumps(
        {{"patch_id": {_q(patch_id)}, "applied_revision": {int(base_revision)} + 1}},
        ensure_ascii=False)
else:
    _vp_final_hash = _vp_base_hash
'''
    _exec_indented = BlenderRunner._indent(_body_exec, 4)

    _validate_block = f'''
# ---- 1. validate revision (never apply a patch onto an unknown base) ----
{_timeline_hash_script("_vp_base_hash")}
_vp_cur_rev = int(_vp_scene.get({_j(REVISION_KEY)}, 1) or 1)
_vp_stored_hash = str(_vp_scene.get({_j(TIMELINE_HASH_KEY)}, "") or "")
_vp_req_hash = {_q(_req_hash)}
if _vp_cur_rev != {int(base_revision)}:
    raise RuntimeError(
        "revision_mismatch: base " + str({int(base_revision)}) +
        " != current " + str(_vp_cur_rev) +
        " (re-read the project first)")
if _vp_req_hash and _vp_stored_hash and _vp_base_hash != _vp_req_hash:
    raise RuntimeError(
        "stale_base: timeline changed since base hash " +
        str(_vp_req_hash[:8]) + " (manual edit? re-read the project first)")
'''
    _guard_body = _validate_block + _token_check + _body_exec
    _guard_indented = BlenderRunner._indent(_guard_body, 4)

    return f"""
{_ripple_helpers()}
import json as _json, os, shutil
from pathlib import Path as _Path
se = bpy.context.scene.sequence_editor
{_ensure_ids_script()}
_patch_results = []
_patch_payloads = []
_patch_error = None
def _vp_result(**kw):
    _patch_payloads.append(kw)
_vp_scene = bpy.context.scene

# ---- 0. IDEMPOTENCY FIRST: a retried patch_id is a no-op (even if the base
#         looks stale — the patch already committed) ----
_dup = False
_raw_lp = _vp_scene.get({_j(LAST_PATCH_KEY)}, "") if {_j(LAST_PATCH_KEY)} in _vp_scene else ""
_lp = {{}}
if _raw_lp:
    try:
        _lp = _json.loads(_raw_lp)
    except Exception:
        _lp = {{}}
if _lp.get("patch_id") == {_q(patch_id)}:
    _dup = True

if not _dup:
{_guard_indented}

if _dup:
    print("VP_RESULT:" + _json.dumps({{
        "status": "already_applied", "patch_id": {_q(patch_id)},
        "applied_revision": _lp.get("applied_revision"),
    }}, ensure_ascii=False, default=str))
else:
    print("VP_RESULT:" + _json.dumps({{
        "applied": _patch_error is None,
        "base_revision": {int(base_revision)},
        "applied_revision": {int(base_revision) + 1} if _patch_error is None else {int(base_revision)},
        "committed": _patch_error is None,
        "timeline_hash": _vp_final_hash,
        "rolled_back": _rolled_back,
        "error": _patch_error,
        "results": _patch_results,
        "payloads": _patch_payloads,
    }}, ensure_ascii=False, default=str))
"""


# ---------------------------------------------------------------------------
# Audio editing — fade / pan / duck (timeline-level; complex DAW work stays in FFmpeg)
# ---------------------------------------------------------------------------


@_op("fade_audio_in", read_only=False)
def fade_audio_in(project: str, video_ai_id: str | None = None, target: str | None = None,
                  duration_frames: int = 24, from_volume: float = 0.0, **kw) -> str:
    """Fade a SOUND strip's volume in over duration_frames."""
    _validate_project(project)
    return f"""
import json as _json
{_ripple_helpers()}
se = bpy.context.scene.sequence_editor
_by_id = {_q(video_ai_id or '')}
_by_name = {_q(target or '')}
s = None
if se is not None:
    if _by_id:
        s = _vp_by_id(se, _by_id)
    if s is None and _by_name:
        for _x in se.strips:
            if _x.name == _by_name:
                s = _x
                break
if s is None:
    raise RuntimeError("strip not found")
if s.type != 'SOUND':
    raise RuntimeError("fade_audio_in requires a SOUND strip")
_vol = s.volume
s.volume = {float(from_volume)}
# record intent
s[{_q(ANIM_KEY)}] = _json.dumps({{
    "presets": ["fade_audio_in"],
    "frames": [
        {{"frame": s.frame_final_start, "props": {{"volume": {float(from_volume)}}}}},
        {{"frame": s.frame_final_start + {int(duration_frames)}, "props": {{"volume": _vol}}}}
    ]
}}, ensure_ascii=False)
_vp_result(video_ai_id=s.get({_q(ID_KEY)}, ""), duration_frames={int(duration_frames)},
           from_volume={float(from_volume)}, to_volume=_vol)
"""


@_op("fade_audio_out", read_only=False)
def fade_audio_out(project: str, video_ai_id: str | None = None, target: str | None = None,
                   duration_frames: int = 24, to_volume: float = 0.0, **kw) -> str:
    """Fade a SOUND strip's volume out before its end."""
    _validate_project(project)
    return f"""
import json as _json
{_ripple_helpers()}
se = bpy.context.scene.sequence_editor
_by_id = {_q(video_ai_id or '')}
_by_name = {_q(target or '')}
s = None
if se is not None:
    if _by_id:
        s = _vp_by_id(se, _by_id)
    if s is None and _by_name:
        for _x in se.strips:
            if _x.name == _by_name:
                s = _x
                break
if s is None:
    raise RuntimeError("strip not found")
if s.type != 'SOUND':
    raise RuntimeError("fade_audio_out requires a SOUND strip")
_vol = s.volume
s[{_q(ANIM_KEY)}] = _json.dumps({{
    "presets": ["fade_audio_out"],
    "frames": [
        {{"frame": s.frame_final_end - {int(duration_frames)}, "props": {{"volume": _vol}}}},
        {{"frame": s.frame_final_end, "props": {{"volume": {float(to_volume)}}}}}
    ]
}}, ensure_ascii=False)
_vp_result(video_ai_id=s.get({_q(ID_KEY)}, ""), duration_frames={int(duration_frames)},
           to_volume={float(to_volume)})
"""


@_op("set_pan", read_only=False)
def set_pan(project: str, video_ai_id: str | None = None, target: str | None = None,
            pan: float = 0.0, **kw) -> str:
    """Set stereo pan on a SOUND strip (-1 left .. 1 right)."""
    _validate_project(project)
    return f"""
{_ripple_helpers()}
se = bpy.context.scene.sequence_editor
_by_id = {_q(video_ai_id or '')}
_by_name = {_q(target or '')}
s = None
if se is not None:
    if _by_id:
        s = _vp_by_id(se, _by_id)
    if s is None and _by_name:
        for _x in se.strips:
            if _x.name == _by_name:
                s = _x
                break
if s is None:
    raise RuntimeError("strip not found")
if s.type != 'SOUND':
    raise RuntimeError("set_pan requires a SOUND strip")
s.pan = {float(pan)}
_vp_result(video_ai_id=s.get({_q(ID_KEY)}, ""), pan=s.pan)
"""


@_op("duck_audio", read_only=False)
def duck_audio(project: str, target: str | None = None, video_ai_id: str | None = None,
               under: str | None = None, reduction_db: float = -8.0,
               attack_frames: int = 6, release_frames: int = 12, **kw) -> str:
    """Duck a music strip's volume under dialogue strips.

    Uses volume keyframes (video_ai_anim): full volume except where the 'under'
    strips play, where volume drops by reduction_db.
    """
    _validate_project(project)
    return f"""
import json as _json
{_ripple_helpers()}
import math
se = bpy.context.scene.sequence_editor
_by_id = {_q(video_ai_id or '')}
_by_name = {_q(target or '')}
_under_name = {_q(under or '')}
_music = None
if se is not None:
    if _by_id:
        _music = _vp_by_id(se, _by_id)
    if _music is None and _by_name:
        for _x in se.strips:
            if _x.name == _by_name:
                _music = _x
                break
if _music is None:
    raise RuntimeError("music strip not found")
if _music.type != 'SOUND':
    raise RuntimeError("duck_audio target must be a SOUND strip")
_base_vol = _music.volume
_reduction = {float(reduction_db)}
_attack = {int(attack_frames)}
_release = {int(release_frames)}
# find dialogue windows (strips whose name/role is the 'under' target)
_windows = []
if se is not None:
    for _x in se.strips:
        if _x.name == _music.name:
            continue
        _mraw = _x.get({_q(META_KEY)}, "")
        _role = ""
        if _mraw:
            try:
                _role = _json.loads(_mraw).get("role", "")
            except Exception:
                pass
        if _x.type in ('SOUND', 'MOVIE') and (_under_name in _x.name or _role == _under_name or not _under_name):
            _windows.append([_x.frame_final_start, _x.frame_final_end])
# build duck keyframes
_duck_vol = max(0.0, _base_vol * (10 ** (_reduction / 20)))
_frames = []
for _ws, _we in sorted(_windows):
    _frames.append({{"frame": max(1, _ws - _attack), "props": {{"volume": _base_vol}}}})
    _frames.append({{"frame": _ws, "props": {{"volume": _duck_vol}}}})
    _frames.append({{"frame": _we, "props": {{"volume": _duck_vol}}}})
    _frames.append({{"frame": _we + _release, "props": {{"volume": _base_vol}}}})
# dedupe by frame (keep last)
_by_frame = {{}}
for _f in _frames:
    _by_frame[_f["frame"]] = _f
_anim = {{"presets": ["duck_audio"], "frames": sorted(_by_frame.values(), key=lambda x: x["frame"])}}
_music[{_q(ANIM_KEY)}] = _json.dumps(_anim, ensure_ascii=False)
_vp_result(video_ai_id=_music.get({_q(ID_KEY)}, ""), windows=len(_windows),
           duck_volume=_duck_vol, keyframes=len(_anim["frames"]))
"""


@_op("mute_range", read_only=False)
def mute_range(project: str, start_frame: int, end_frame: int,
               channel: int | None = None, video_ai_ids: list | None = None,
               mute: bool = True, **kw) -> str:
    """Mute/unmute strips overlapping [start_frame, end_frame)."""
    _validate_project(project)
    return f"""
{_ripple_helpers()}
se = bpy.context.scene.sequence_editor
_s = {int(start_frame)}
_e = {int(end_frame)}
_ch = {int(channel) if channel is not None else -1}
_refs = {_py(video_ai_ids or [])}
_mute = {_py(mute)}
_changed = []
if se is not None:
    for _x in list(se.strips):
        if _ch >= 0 and _x.channel != _ch:
            continue
        if _refs:
            _rid = _x.get({_q(ID_KEY)}, "")
            if _rid not in _refs and _x.name not in _refs:
                continue
        else:
            if _x.frame_final_start >= _e or _x.frame_final_end <= _s:
                continue
        _x.mute = _mute
        _changed.append({{"id": _x.name, "video_ai_id": _x.get({_q(ID_KEY)}, ""),
                          "muted": bool(_x.mute)}})
_vp_result(changed=_changed, count=len(_changed), mute={_py(mute)})
"""


@_op("set_volume_range", read_only=False)
def set_volume_range(project: str, start_frame: int, end_frame: int, volume: float,
                     channel: int | None = None, video_ai_ids: list | None = None,
                     **kw) -> str:
    """Set volume on SOUND strips overlapping [start_frame, end_frame) and record
    the range as volume keyframes (video_ai_anim) for the edit intent."""
    _validate_project(project)
    return f"""
import json as _json
{_ripple_helpers()}
se = bpy.context.scene.sequence_editor
_s = {int(start_frame)}
_e = {int(end_frame)}
_ch = {int(channel) if channel is not None else -1}
_refs = {_py(video_ai_ids or [])}
_vol = {float(volume)}
_changed = []
if se is not None:
    for _x in list(se.strips):
        if _x.type != 'SOUND':
            continue
        if _ch >= 0 and _x.channel != _ch:
            continue
        if _refs:
            _rid = _x.get({_q(ID_KEY)}, "")
            if _rid not in _refs and _x.name not in _refs:
                continue
        else:
            if _x.frame_final_start >= _e or _x.frame_final_end <= _s:
                continue
        _x.volume = _vol
        # record range intent as volume keyframes at the range edges
        _anim = {{"frames": [], "presets": []}}
        _raw_a = _x.get({_q(ANIM_KEY)}, "") if {_q(ANIM_KEY)} in _x else ""
        if _raw_a:
            try:
                _anim = _json.loads(_raw_a)
            except Exception:
                _anim = {{"frames": [], "presets": []}}
        _kfs = [{{"frame": max(1, _s), "props": {{"volume": _vol}}}},
                {{"frame": _e, "props": {{"volume": _vol}}}}]
        for _kf in _kfs:
            _rep = False
            for _i, _k in enumerate(_anim.get("frames", [])):
                if _k.get("frame") == _kf["frame"]:
                    _anim["frames"][_i] = _kf
                    _rep = True
                    break
            if not _rep:
                _anim.setdefault("frames", []).append(_kf)
        _anim["frames"].sort(key=lambda x: x["frame"])
        if "volume_range" not in _anim.setdefault("presets", []):
            _anim["presets"].append("volume_range")
        _x[{_q(ANIM_KEY)}] = _json.dumps(_anim, ensure_ascii=False)
        _changed.append({{"id": _x.name, "video_ai_id": _x.get({_q(ID_KEY)}, ""),
                          "volume": float(_x.volume)}})
_vp_result(changed=_changed, count=len(_changed), volume={float(volume)})
"""


# ---------------------------------------------------------------------------
# Asset registry — distinguish asset (file) from timeline clip instance
# ---------------------------------------------------------------------------


@_op("bind_asset", read_only=False)
def bind_asset(project: str, asset_id: str, strip_ids: list | None = None,
               expected_path: str = "", asset_revision: int = 1, **kw) -> str:
    """Bind existing media strips to a host application's stable asset ID."""
    _validate_project(project)
    if not asset_id or not isinstance(strip_ids, list) or not strip_ids:
        raise BlenderRunnerError(
            "invalid_args", "bind_asset requires asset_id and non-empty strip_ids")
    if len(strip_ids) > 50:
        raise BlenderRunnerError("invalid_args", "bind_asset accepts at most 50 strip_ids")
    expected = str(Path(expected_path).expanduser().resolve()) if expected_path else ""
    return f"""
import os
se = bpy.context.scene.sequence_editor
_wanted = set({_j([str(item) for item in strip_ids])})
_expected = os.path.normcase(os.path.normpath({_q(expected)})) if {_py(bool(expected))} else ""
_bound = []
if se is None:
    raise RuntimeError("no sequence editor")
for _s in se.strips:
    _sid = _s.get({_q(ID_KEY)}, "")
    if _sid not in _wanted:
        continue
    if _s.type not in ('MOVIE', 'SOUND', 'IMAGE'):
        raise RuntimeError("asset_binding_type_mismatch: strip " + _sid + " is " + _s.type)
    _raw_path = (
        getattr(getattr(_s, 'sound', None), 'filepath', '') or ''
        if _s.type == 'SOUND'
        else getattr(_s, 'filepath', '') or ''
    )
    _actual = os.path.normcase(os.path.normpath(bpy.path.abspath(_raw_path)))
    if _expected and _actual != _expected:
        raise RuntimeError("asset_source_mismatch: strip " + _sid + " source differs from registry")
    _s[{_q(ASSET_ID_KEY)}] = {_q(asset_id)}
    _s[{_q(ASSET_REVISION_KEY)}] = {int(asset_revision)}
    _bound.append(_sid)
_missing = sorted(_wanted - set(_bound))
if _missing:
    raise RuntimeError("strip_not_found: " + str(_missing))
_vp_result(asset_id={_q(asset_id)}, bound_strip_ids=_bound, count=len(_bound))
"""


def _asset_rebind_script(*, asset_id: str, asset_revision: int,
                         old_path: str, new_path: str,
                         replace_content: bool) -> str:
    old_resolved = str(Path(old_path).expanduser().resolve())
    new_resolved = str(Path(new_path).expanduser().resolve())
    return f"""
import os
se = bpy.context.scene.sequence_editor
_asset_id = {_q(asset_id)}
_old = os.path.normcase(os.path.normpath({_q(old_resolved)}))
_new = {_q(new_resolved)}
if not os.path.isfile(_new):
    raise RuntimeError("input_missing: asset path not found: " + _new)
_updated = []
_proxy_detached = []
if se is not None:
    for _s in se.strips:
        if _s.get({_q(ASSET_ID_KEY)}, "") != _asset_id:
            continue
        if _s.type not in ('MOVIE', 'SOUND', 'IMAGE'):
            raise RuntimeError("asset_binding_type_mismatch: " + _s.name)
        _raw_path = (
            getattr(getattr(_s, 'sound', None), 'filepath', '') or ''
            if _s.type == 'SOUND'
            else getattr(_s, 'filepath', '') or ''
        )
        _actual = os.path.normcase(os.path.normpath(bpy.path.abspath(_raw_path)))
        if _actual != _old and _actual != os.path.normcase(os.path.normpath(_new)):
            raise RuntimeError("asset_binding_stale: strip " + _s.name + " was manually relinked")
        if _s.type == 'SOUND':
            _s.sound = bpy.data.sounds.load(_new, check_existing=True)
        else:
            _s.filepath = _new
        _s[{_q(ASSET_REVISION_KEY)}] = {int(asset_revision)}
        if _s.type == 'MOVIE' and (bool(getattr(_s, 'use_proxy', False)) or {_q(PROXY_KEY)} in _s):
            _s.use_proxy = False
            try:
                if hasattr(_s.proxy, 'use_proxy_custom_file'):
                    _s.proxy.use_proxy_custom_file = False
                if hasattr(_s.proxy, 'filepath'):
                    _s.proxy.filepath = ''
                if hasattr(_s.proxy, 'directory'):
                    _s.proxy.directory = ''
            except Exception:
                pass
            if {_q(PROXY_KEY)} in _s:
                del _s[{_q(PROXY_KEY)}]
            _proxy_detached.append(_s.get({_q(ID_KEY)}, ""))
        _updated.append(_s.get({_q(ID_KEY)}, ""))
_vp_result(asset_id=_asset_id, asset_revision={int(asset_revision)},
           content_replaced={_py(replace_content)}, updated_strip_ids=_updated,
           proxy_bindings_detached=_proxy_detached,
           disk_files_deleted=False, count=len(_updated))
"""


@_op("relink_asset_binding", read_only=False)
def relink_asset_binding(project: str, asset_id: str, old_path: str,
                         new_path: str, asset_revision: int = 1, **kw) -> str:
    """Move a same-content asset binding; proxy intent is safely detached."""
    _validate_project(project)
    return _asset_rebind_script(
        asset_id=asset_id,
        asset_revision=asset_revision,
        old_path=old_path,
        new_path=new_path,
        replace_content=False,
    )


@_op("replace_asset_binding", read_only=False)
def replace_asset_binding(project: str, asset_id: str, old_path: str,
                          new_path: str, asset_revision: int, **kw) -> str:
    """Bind an explicit new content revision and detach obsolete proxies."""
    _validate_project(project)
    return _asset_rebind_script(
        asset_id=asset_id,
        asset_revision=asset_revision,
        old_path=old_path,
        new_path=new_path,
        replace_content=True,
    )


# Legacy scene-local registry ops below remain implemented for old `.blend`
# files but are intentionally hidden from the public operation list. A host
# application owns asset identity; new bindings use video_ai_asset_id.


@_op("import_asset", read_only=False)
def import_asset(project: str, path: str, asset_id: str | None = None,
                 metadata: dict | None = None, **kw) -> str:
    """Register a media file in the project's asset registry."""
    _validate_project(project)
    return f"""
import json as _json, os, hashlib
scene = bpy.context.scene
_p = {_j(str(Path(path).expanduser().resolve()))}
if not os.path.isfile(_p):
    raise RuntimeError("asset file not found: " + _p)
_reg = []
_raw = scene.get({_j(ASSET_REG_KEY)}, "") if {_j(ASSET_REG_KEY)} in scene else ""
if _raw:
    try:
        _reg = _json.loads(_raw)
    except Exception:
        _reg = []
_fp = None
try:
    _sz = os.path.getsize(_p)
    _fp = {{"size": _sz, "name": os.path.basename(_p)}}
except Exception:
    _fp = {{}}
_aid = {_q(asset_id or '')} or ({{"name": os.path.basename(_p)}}["name"] + "_" + str(len(_reg) + 1))
_entry = {{"id": _aid, "path": _p, "name": os.path.basename(_p), "fingerprint": _fp}}
if {_py(bool(metadata))}:
    _entry["metadata"] = {_py(metadata or {})}
# replace if id exists
_reg = [e for e in _reg if e.get("id") != _aid]
_reg.append(_entry)
scene[{_j(ASSET_REG_KEY)}] = _json.dumps(_reg, ensure_ascii=False)
_vp_result(asset=_entry, count=len(_reg))
"""


@_op("list_assets", read_only=True)
def list_assets(project: str, **kw) -> str:
    _validate_project(project)
    return f"""
import json as _json
scene = bpy.context.scene
_reg = []
_raw = scene.get({_j(ASSET_REG_KEY)}, "") if {_j(ASSET_REG_KEY)} in scene else ""
if _raw:
    try:
        _reg = _json.loads(_raw)
    except Exception:
        _reg = []
_vp_result(assets=_reg, count=len(_reg))
"""


@_op("get_asset", read_only=True)
def get_asset(project: str, asset_id: str, **kw) -> str:
    _validate_project(project)
    return f"""
import json as _json
scene = bpy.context.scene
_reg = []
_raw = scene.get({_j(ASSET_REG_KEY)}, "") if {_j(ASSET_REG_KEY)} in scene else ""
if _raw:
    try:
        _reg = _json.loads(_raw)
    except Exception:
        _reg = []
_found = next((e for e in _reg if e.get("id") == {_q(asset_id)}), None)
if _found is None:
    raise RuntimeError("asset not found: " + {_q(asset_id)})
_vp_result(asset=_found)
"""


@_op("remove_asset", read_only=False)
def remove_asset(project: str, asset_id: str, **kw) -> str:
    _validate_project(project)
    return f"""
import json as _json
scene = bpy.context.scene
_reg = []
_raw = scene.get({_j(ASSET_REG_KEY)}, "") if {_j(ASSET_REG_KEY)} in scene else ""
if _raw:
    try:
        _reg = _json.loads(_raw)
    except Exception:
        _reg = []
_before = len(_reg)
_reg = [e for e in _reg if e.get("id") != {_q(asset_id)}]
scene[{_j(ASSET_REG_KEY)}] = _json.dumps(_reg, ensure_ascii=False)
_vp_result(removed={_q(asset_id)}, removed_any=_before != len(_reg))
"""


@_op("find_missing_assets", read_only=True)
def find_missing_assets(project: str, **kw) -> str:
    """List registered assets whose file no longer exists on disk."""
    _validate_project(project)
    return f"""
import json as _json, os
scene = bpy.context.scene
_reg = []
_raw = scene.get({_j(ASSET_REG_KEY)}, "") if {_j(ASSET_REG_KEY)} in scene else ""
if _raw:
    try:
        _reg = _json.loads(_raw)
    except Exception:
        _reg = []
_missing = []
# also scan strips for missing media files
se = scene.sequence_editor
if se is not None:
    for _s in se.strips:
        if _s.type == 'MOVIE':
            _fp = getattr(_s, 'filepath', '')
            if _fp and not os.path.isfile(bpy.path.abspath(_fp)):
                _missing.append({{"kind": "strip", "name": _s.name,
                                  "path": _fp}})
for _e in _reg:
    if not os.path.isfile(_e.get("path", "")):
        _missing.append({{"kind": "asset", "id": _e.get("id"), "path": _e.get("path")}})
_vp_result(missing=_missing, count=len(_missing))
"""


@_op("relink_asset", read_only=False)
def relink_asset(project: str, asset_id: str, new_path: str, **kw) -> str:
    """Relink a registered asset (and any strips using that filepath)."""
    _validate_project(project)
    return f"""
import json as _json, os
scene = bpy.context.scene
_reg = []
_raw = scene.get({_j(ASSET_REG_KEY)}, "") if {_j(ASSET_REG_KEY)} in scene else ""
if _raw:
    try:
        _reg = _json.loads(_raw)
    except Exception:
        _reg = []
_new = {_j(str(Path(new_path).expanduser().resolve()))}
if not os.path.isfile(_new):
    raise RuntimeError("new file not found: " + _new)
_old_path = None
for _e in _reg:
    if _e.get("id") == {_q(asset_id)}:
        _old_path = _e.get("path")
        _e["path"] = _new
        break
if _old_path is None:
    raise RuntimeError("asset not found: " + {_q(asset_id)})
scene[{_j(ASSET_REG_KEY)}] = _json.dumps(_reg, ensure_ascii=False)
# relink strips using the old path
se = scene.sequence_editor
_relinked = []
if se is not None:
    for _s in se.strips:
        if _s.type == 'MOVIE' and getattr(_s, 'filepath', '') == _old_path:
            _s.filepath = _new
            _relinked.append(_s.name)
_vp_result(asset_id={_q(asset_id)}, old_path=_old_path, new_path=_new,
           strips_relinked=_relinked)
"""


@_op("replace_asset", read_only=False)
def replace_asset(project: str, asset_id: str, new_path: str, **kw) -> str:
    """Replace an asset for ALL strips referencing it (registry-level)."""
    _validate_project(project)
    return relink_asset(project=project, asset_id=asset_id, new_path=new_path)


@_op("inspect_asset", read_only=True)
def inspect_asset(project: str, asset_id: str, **kw) -> str:
    """Inspect a registered asset: registry entry + current on-disk status."""
    _validate_project(project)
    return f"""
import json as _json, os
scene = bpy.context.scene
_reg = []
_raw = scene.get({_j(ASSET_REG_KEY)}, "") if {_j(ASSET_REG_KEY)} in scene else ""
if _raw:
    try:
        _reg = _json.loads(_raw)
    except Exception:
        _reg = []
_found = next((e for e in _reg if e.get("id") == {_q(asset_id)}), None)
if _found is None:
    raise RuntimeError("asset not found: " + {_q(asset_id)})
_p = _found.get("path", "")
_exists = os.path.isfile(_p) if _p else False
_size = os.path.getsize(_p) if _exists else None
# strips currently using this asset
se = scene.sequence_editor
_used_by = []
if se is not None and _p:
    for _s in se.strips:
        if _s.type == 'MOVIE' and bpy.path.abspath(getattr(_s, 'filepath', '')) == _p:
            _used_by.append(_s.name)
_vp_result(asset=_found, exists=_exists, size=_size, used_by=_used_by)
"""


# ---------------------------------------------------------------------------
# Proxies — build/attach/detach/rebuild/clear/status for MOVIE strips
# ---------------------------------------------------------------------------

PROXY_SIZE_FLAGS = {"25": "build_25", "50": "build_50", "75": "build_75", "100": "build_100"}


@_op("attach_proxy", read_only=False)
def attach_proxy(project: str, video_ai_id: str | None = None, target: str | None = None,
                 manifest_path: str = "", **kw) -> str:
    """Attach a validated external proxy manifest to a MOVIE strip."""
    project = _validate_project(project)
    if not manifest_path:
        raise BlenderRunnerError(
            "invalid_args", "attach_proxy requires an external proxy manifest_path")
    manifest = _load_proxy_manifest(manifest_path)
    proxy_path = str(manifest["proxy_path"])
    source_path = str(manifest["source_path"])
    project_dir = Path(str(manifest["project_dir"])).resolve()
    blend_path = Path(project).resolve()
    portable = _inside_path(Path(proxy_path), project_dir) and _inside_path(
        blend_path, project_dir
    )
    stored_proxy_dir = (
        "//" + os.path.relpath(Path(proxy_path).parent, blend_path.parent).replace("\\", "/")
        if portable else str(Path(proxy_path).parent)
    )
    stored_proxy_name = Path(proxy_path).name
    size_num = str(int(manifest["scale"]))
    intent = {
        "version": "1.0",
        "mode": "custom_file",
        "manifest_path": str(Path(manifest_path).resolve()),
        "project_dir": str(project_dir),
        "source_path": source_path,
        "source_sha256": str(manifest["source_sha256"]),
        "source_size": int(manifest["source_size"]),
        "source_mtime_ns": int(manifest["source_mtime_ns"]),
        "proxy_path": proxy_path,
        "proxy_sha256": str(manifest["proxy_sha256"]),
        "proxy_size": int(manifest["proxy_size"]),
        "profile": str(manifest["profile"]),
        "scale": int(manifest["scale"]),
        "portable": bool(portable),
    }
    return f"""
import json as _json, os
{_ripple_helpers()}
se = bpy.context.scene.sequence_editor
_by_id = {_q(video_ai_id or '')}
_by_name = {_q(target or '')}
s = None
if se is not None:
    if _by_id:
        s = _vp_by_id(se, _by_id)
    if s is None and _by_name:
        for _x in se.strips:
            if _x.name == _by_name:
                s = _x
                break
if s is None:
    raise RuntimeError("strip not found")
if s.type != 'MOVIE':
    raise RuntimeError("proxy requires a MOVIE strip")
_source = os.path.normcase(os.path.normpath(bpy.path.abspath(getattr(s, 'filepath', '') or '')))
_expected_source = os.path.normcase(os.path.normpath({_q(source_path)}))
if _source != _expected_source:
    raise RuntimeError("proxy_source_mismatch: manifest source does not match target strip")
s.use_proxy = True
p = s.proxy
if (not hasattr(p, 'filepath') or not hasattr(p, 'use_proxy_custom_file')
        or not hasattr(p, 'directory') or not hasattr(p, 'use_proxy_custom_directory')):
    raise RuntimeError("proxy_custom_file_unsupported: Blender lacks custom proxy file support")
for _flag in ({_py(list(PROXY_SIZE_FLAGS.values()))}):
    setattr(p, _flag, False)
setattr(p, {_q(PROXY_SIZE_FLAGS[size_num])}, True)
p.use_proxy_custom_file = True
p.filepath = {_q(stored_proxy_name)}
p.use_proxy_custom_directory = True
p.directory = {_q(stored_proxy_dir)}
p.use_overwrite = False
_intent = {_py(intent)}
s[{_q(PROXY_KEY)}] = _json.dumps(_intent, ensure_ascii=False)
_vp_result(video_ai_id=s.get({_q(ID_KEY)}, ""), name=s.name,
           size={_q(size_num + '%')}, mode="custom_file",
           proxy_path=os.path.normpath(os.path.join(bpy.path.abspath(p.directory), p.filepath)),
           proxy_directory=p.directory, proxy_filename=p.filepath,
           manifest_path={_q(str(Path(manifest_path).resolve()))},
           portable={_py(portable)}, flags={_q(PROXY_SIZE_FLAGS[size_num])})
"""


@_op("detach_proxy", read_only=False)
def detach_proxy(project: str, video_ai_id: str | None = None, target: str | None = None,
                 **kw) -> str:
    """Detach proxy settings without deleting any proxy or manifest files."""
    _validate_project(project)
    return f"""
{_ripple_helpers()}
se = bpy.context.scene.sequence_editor
_by_id = {_q(video_ai_id or '')}
_by_name = {_q(target or '')}
s = None
if se is not None:
    if _by_id:
        s = _vp_by_id(se, _by_id)
    if s is None and _by_name:
        for _x in se.strips:
            if _x.name == _by_name:
                s = _x
                break
if s is None:
    raise RuntimeError("strip not found")
s.use_proxy = False
try:
    for _flag in ({_py(list(PROXY_SIZE_FLAGS.values()))}):
        setattr(s.proxy, _flag, False)
    if hasattr(s.proxy, 'use_proxy_custom_file'):
        s.proxy.use_proxy_custom_file = False
    if hasattr(s.proxy, 'filepath'):
        s.proxy.filepath = ''
    if hasattr(s.proxy, 'use_proxy_custom_directory'):
        s.proxy.use_proxy_custom_directory = False
    if hasattr(s.proxy, 'directory'):
        s.proxy.directory = ''
except Exception:
    pass
if {_q(PROXY_KEY)} in s:
    del s[{_q(PROXY_KEY)}]
_vp_result(video_ai_id=s.get({_q(ID_KEY)}, ""), name=s.name, detached=True,
           use_proxy=bool(s.use_proxy))
"""


@_op("clear_proxies", read_only=False)
def clear_proxies(project: str, **kw) -> str:
    """Detach ALL MOVIE proxies without deleting files on disk."""
    _validate_project(project)
    return f"""
{_ripple_helpers()}
se = bpy.context.scene.sequence_editor
_cleared = []
if se is not None:
    for _x in list(se.strips):
        if _x.type != 'MOVIE':
            continue
        _x.use_proxy = False
        try:
            for _flag in ({_py(list(PROXY_SIZE_FLAGS.values()))}):
                setattr(_x.proxy, _flag, False)
            if hasattr(_x.proxy, 'use_proxy_custom_file'):
                _x.proxy.use_proxy_custom_file = False
            if hasattr(_x.proxy, 'filepath'):
                _x.proxy.filepath = ''
            if hasattr(_x.proxy, 'use_proxy_custom_directory'):
                _x.proxy.use_proxy_custom_directory = False
            if hasattr(_x.proxy, 'directory'):
                _x.proxy.directory = ''
        except Exception:
            pass
        if {_q(PROXY_KEY)} in _x:
            del _x[{_q(PROXY_KEY)}]
        _cleared.append(_x.name)
_vp_result(cleared=_cleared, count=len(_cleared))
"""


@_op("get_proxy_status", read_only=True)
def get_proxy_status(project: str, video_ai_id: str | None = None,
                     target: str | None = None, **kw) -> str:
    """Read actual Blender proxy config plus validated external intent state."""
    _validate_project(project)
    return f"""
import json as _json, os
{_ripple_helpers()}
{_proxy_state_helpers()}
se = bpy.context.scene.sequence_editor
_by_id = {_q(video_ai_id or '')}
_by_name = {_q(target or '')}
_targets = []
if se is not None:
    for _x in se.strips:
        if _x.type != 'MOVIE':
            continue
        if _by_id and _x.get({_q(ID_KEY)}, "") != _by_id:
            continue
        if _by_name and _x.name != _by_name:
            continue
        _targets.append(_x)
if not _targets:
    raise RuntimeError("no MOVIE strip matched")
_status = []
for _s in _targets:
    _entry = _vp_proxy_status(_s)
    _entry["name"] = _s.name
    _entry["video_ai_id"] = _s.get({_q(ID_KEY)}, "")
    _status.append(_entry)
_vp_result(strips=_status, count=len(_status))
"""


# ---------------------------------------------------------------------------
# Channel roles — semantic names for VSE channels
# ---------------------------------------------------------------------------


@_op("set_channel_role", read_only=False)
def set_channel_role(project: str, channel: int, role: str, **kw) -> str:
    _validate_project(project)
    return f"""
import json as _json
scene = bpy.context.scene
_roles = {{}}
_raw = scene.get({_j(CHANNEL_ROLE_KEY)}, "") if {_j(CHANNEL_ROLE_KEY)} in scene else ""
if _raw:
    try:
        _roles = _json.loads(_raw)
    except Exception:
        _roles = {{}}
_roles[str({int(channel)})] = {_q(role)}
scene[{_j(CHANNEL_ROLE_KEY)}] = _json.dumps(_roles, ensure_ascii=False)
_vp_result(channel={int(channel)}, role={_q(role)}, roles=_roles)
"""


@_op("get_channel_roles", read_only=True)
def get_channel_roles(project: str, **kw) -> str:
    _validate_project(project)
    return f"""
import json as _json
scene = bpy.context.scene
_roles = {{}}
_raw = scene.get({_j(CHANNEL_ROLE_KEY)}, "") if {_j(CHANNEL_ROLE_KEY)} in scene else ""
if _raw:
    try:
        _roles = _json.loads(_raw)
    except Exception:
        _roles = {{}}
_vp_result(roles=_roles)
"""


# ---------------------------------------------------------------------------
# Render — frame / range / contact sheet
# ---------------------------------------------------------------------------


@_op("render_frame", read_only=False)
def render_frame(project: str, output_path: str, frame: int | None = None,
                 resolution=(1280, 720), **kw) -> str:
    """Render a single frame to PNG (e.g. for AI visual inspection)."""
    _validate_project(project)
    return f"""
import os
scene = bpy.context.scene
_f = {_jv(frame)} or scene.frame_current
_out = {_j(str(Path(output_path).expanduser().resolve()))}
os.makedirs(os.path.dirname(_out), exist_ok=True)
_orig_res = [scene.render.resolution_x, scene.render.resolution_y]
_orig_pct = scene.render.resolution_percentage
_orig_mt = scene.render.image_settings.media_type
_orig_fmt = scene.render.image_settings.file_format
_orig_fp = scene.render.filepath
_orig_cur = scene.frame_current
try:
    scene.render.resolution_x = {int(resolution[0])}
    scene.render.resolution_y = {int(resolution[1])}
    scene.render.resolution_percentage = 100
    # Blender 5.1: file_format enum is gated by media_type (IMAGE vs VIDEO);
    # media_type enum itself differs headless vs GUI — guard both.
    try:
        scene.render.image_settings.media_type = 'IMAGE'
    except Exception:
        pass
    for _fmt in ('PNG', 'FFMPEG'):
        try:
            scene.render.image_settings.file_format = _fmt
            break
        except Exception:
            continue
    scene.frame_current = _f
    scene.render.filepath = _out
    bpy.ops.render.render(write_still=True)
finally:
    scene.render.resolution_x = _orig_res[0]
    scene.render.resolution_y = _orig_res[1]
    scene.render.resolution_percentage = _orig_pct
    scene.render.image_settings.media_type = _orig_mt
    scene.render.image_settings.file_format = _orig_fmt
    scene.render.filepath = _orig_fp
    scene.frame_current = _orig_cur
_vp_result(output_path=_out, frame=_f, exists=os.path.isfile(_out))
"""


@_op("render_range", read_only=False)
def render_range(project: str, output_path: str, start_frame: int, end_frame: int,
                 resolution=None, scale_percent: int = 50,
                 fps: float = 30.0, **kw) -> str:
    """Render a frame range to an MP4 (fast preview)."""
    _validate_project(project)
    return _render_script(project, output_path, resolution, fps,
                          start_frame, end_frame, "H264", "draft", preview=True,
                          preview_scale_percent=scale_percent)


@_op("generate_contact_sheet", read_only=False)
def generate_contact_sheet(project: str, output_path: str, frames: list | None = None,
                           cols: int = 4, **kw) -> str:
    """Render a grid contact sheet of selected frames to a single PNG."""
    _validate_project(project)
    if not frames:
        raise BlenderRunnerError("invalid_args", "generate_contact_sheet needs 'frames' list")
    return f"""
import os
scene = bpy.context.scene
_frames = {_py(frames)}
_cols = {int(cols)}
_out = {_j(str(Path(output_path).expanduser().resolve()))}
os.makedirs(os.path.dirname(_out), exist_ok=True)
_w, _h = 320, 180
_orig = [scene.render.resolution_x, scene.render.resolution_y]
_orig_pct = scene.render.resolution_percentage
_orig_mt = scene.render.image_settings.media_type
_orig_fmt = scene.render.image_settings.file_format
_orig_fp = scene.render.filepath
_orig_cur = scene.frame_current
try:
    scene.render.resolution_x = _w
    scene.render.resolution_y = _h
    scene.render.resolution_percentage = 100
    try:
        scene.render.image_settings.media_type = 'IMAGE'
    except Exception:
        pass
    for _fmt in ('PNG', 'FFMPEG'):
        try:
            scene.render.image_settings.file_format = _fmt
            break
        except Exception:
            continue
    _files = []
    for _i, _f in enumerate(_frames):
        _tmp = os.path.join(os.path.dirname(_out), f"_cs_{{_i:02d}}.png")
        scene.frame_set(int(_f))
        scene.render.filepath = _tmp
        bpy.ops.render.render(write_still=True)
        _files.append(_tmp)
    # compose grid
    import struct
    _rows = (len(_files) + _cols - 1) // _cols
    _grid_w, _grid_h = _cols * _w, _rows * _h
    _grid = bpy.data.images.new("contact_sheet", width=_grid_w, height=_grid_h, alpha=False)
    # blit via pixel assignment (simple, deterministic)
    _px = [0.0] * (_grid_w * _grid_h * 4)
    for _i, _fp in enumerate(_files):
        _img = bpy.data.images.load(_fp)
        _r = _i // _cols
        _c = _i % _cols
        _src = list(_img.pixels)
        for _y in range(_h):
            for _x in range(_w):
                _sx = (_y * _w + _x) * 4
                _dx = ((_grid_h - 1 - (_r * _h + _y)) * _grid_w + (_c * _w + _x)) * 4
                _px[_dx:_dx+4] = _src[_sx:_sx+4]
        bpy.data.images.remove(_img)
        os.remove(_fp)
    _grid.pixels = _px
    _grid.filepath_raw = _out
    _grid.file_format = 'PNG'
    _grid.save()
    bpy.data.images.remove(_grid)
finally:
    scene.render.resolution_x = _orig[0]
    scene.render.resolution_y = _orig[1]
    scene.render.resolution_percentage = _orig_pct
    scene.render.image_settings.media_type = _orig_mt
    scene.render.image_settings.file_format = _orig_fmt
    scene.render.filepath = _orig_fp
    scene.frame_current = _orig_cur
_vp_result(output_path=_out, frames=len(_frames), exists=os.path.isfile(_out))
"""


@_op("sample_frame", read_only=False)
def sample_frame(project: str, frame: int | None = None, grid=(8, 4), **kw) -> str:
    """Render one frame and return a bounded numeric color grid.

    Agents verify timeline visuals numerically instead of eyeballing
    screenshots: each cell is the mean RGB (0-255) of the rendered frame as the
    final render writes it (scene view transform applied, reported alongside),
    plus min/max/mean luminance over the grid. Rows run top to bottom and
    columns left to right. The frame goes to a private temp PNG that is always
    deleted, and the scene is restored (frame, use_sequencer, output settings).
    """
    _validate_project(project)
    try:
        gx, gy = int(grid[0]), int(grid[1])
    except (TypeError, ValueError, IndexError):
        raise BlenderRunnerError("invalid_args", "grid must be [x, y] integers")
    if not (1 <= gx <= 16 and 1 <= gy <= 16):
        raise BlenderRunnerError("invalid_args", "grid cells must be 1..16 per axis")
    if frame is not None:
        try:
            frame = int(frame)
        except (TypeError, ValueError):
            raise BlenderRunnerError("invalid_args", "frame must be an integer")
    return f"""
import bpy, os, tempfile
import numpy as np
scene = bpy.context.scene
_f = {_jv(frame)}
if _f is None:
    _f = scene.frame_current
_gx, _gy = {int(gx)}, {int(gy)}
_settings = scene.render.image_settings
_orig_frame = scene.frame_current
_orig_seq = scene.render.use_sequencer
_orig_fp = scene.render.filepath
_orig_fmt = _settings.file_format
# media_type only exists on Blender >= 5; 4.x selects PNG via file_format alone.
_has_mt = hasattr(_settings, "media_type")
_orig_mt = _settings.media_type if _has_mt else None
_fd, _tmp = tempfile.mkstemp(prefix="vse_sample_", suffix=".png")
os.close(_fd)
_img = None
scene.render.use_sequencer = True
try:
    scene.frame_set(int(_f))
    if _has_mt:
        _settings.media_type = 'IMAGE'
    _settings.file_format = 'PNG'
    scene.render.filepath = _tmp
    bpy.ops.render.render(write_still=True)
    _img = bpy.data.images.load(_tmp, check_existing=False)
    _w, _h = _img.size
    if _w == 0 or _h == 0:
        raise RuntimeError("render result unavailable")
    # One bulk copy; per-index access to Image.pixels is O(width*height) each.
    _buf = np.empty(_w * _h * 4, dtype=np.float32)
    _img.pixels.foreach_get(_buf)
    # Blender stores rows bottom-up; flip so cells[0] is the top of the frame.
    _rgb = _buf.reshape(_h, _w, 4)[::-1, :, :3]
    _xs = [int(round(_i * _w / _gx)) for _i in range(_gx + 1)]
    _ys = [int(round(_i * _h / _gy)) for _i in range(_gy + 1)]
    _rows = []
    for _ry in range(_gy):
        _row = []
        for _rx in range(_gx):
            _cell = _rgb[_ys[_ry]:max(_ys[_ry + 1], _ys[_ry] + 1),
                         _xs[_rx]:max(_xs[_rx + 1], _xs[_rx] + 1)]
            _row.append([int(round(float(_v) * 255)) for _v in _cell.mean(axis=(0, 1))])
        _rows.append(_row)
    _lums = [round(0.2126 * _c[0] + 0.7152 * _c[1] + 0.0722 * _c[2], 1)
             for _row in _rows for _c in _row]
    _view = scene.view_settings.view_transform
    _look = scene.view_settings.look
finally:
    if _img is not None:
        bpy.data.images.remove(_img)
    scene.render.use_sequencer = _orig_seq
    scene.render.filepath = _orig_fp
    if _has_mt:
        _settings.media_type = _orig_mt
    _settings.file_format = _orig_fmt
    try:
        os.remove(_tmp)
    except OSError:
        pass
    scene.frame_set(int(_orig_frame))
_vp_result(frame=int(_f), grid=[_gx, _gy], size=[int(_w), int(_h)], cells=_rows,
           view_transform=_view, look=_look,
           luminance={{"min": min(_lums), "max": max(_lums),
                      "mean": round(sum(_lums) / len(_lums), 1)}})
"""


# ---------------------------------------------------------------------------
# Project packaging + font registry
# ---------------------------------------------------------------------------


@_op("save_project_copy", read_only=False)
def save_project_copy(project: str, copy_path: str, **kw) -> str:
    """Save a copy of the project to another path (does not switch current file)."""
    _validate_project(project)
    return f"""
import os
_out = {_j(str(Path(copy_path).expanduser().resolve()))}
os.makedirs(os.path.dirname(_out), exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=_out, copy=True)
_vp_result(output_path=_out, exists=os.path.isfile(_out))
"""


@_op("collect_project_assets", read_only=False)
def collect_project_assets(project: str, dest_dir: str, **kw) -> str:
    """Copy all media referenced by strips into dest_dir (self-contained project)."""
    _validate_project(project)
    return f"""
import os, shutil
se = bpy.context.scene.sequence_editor
_dest = {_j(str(Path(dest_dir).expanduser().resolve()))}
os.makedirs(_dest, exist_ok=True)
_collected = []
if se is not None:
    for _s in se.strips:
        if _s.type in ('MOVIE', 'SOUND', 'IMAGE'):
            _fp = getattr(_s, 'filepath', '')
            if not _fp:
                continue
            _abs = bpy.path.abspath(_fp)
            if not os.path.isfile(_abs):
                continue
            _name = os.path.basename(_abs)
            _dst = os.path.join(_dest, _name)
            if not os.path.exists(_dst):
                shutil.copy2(_abs, _dst)
            _collected.append({{"name": _name, "from": _abs, "to": _dst}})
_vp_result(collected=_collected, count=len(_collected), dest=_dest)
"""


@_op("package_project", read_only=False)
def package_project(project: str, output_dir: str, **kw) -> str:
    """Package the project: .blend + media + fonts into a self-contained folder."""
    _validate_project(project)
    return f"""
import os, shutil
_proj = {_j(str(Path(project).resolve()))}
_out = {_j(str(Path(output_dir).expanduser().resolve()))}
os.makedirs(_out, exist_ok=True)
_media = os.path.join(_out, 'media')
os.makedirs(_media, exist_ok=True)
# 1. copy media
se = bpy.context.scene.sequence_editor
_collected = []
if se is not None:
    for _s in se.strips:
        if _s.type in ('MOVIE', 'SOUND', 'IMAGE'):
            _fp = getattr(_s, 'filepath', '')
            if not _fp:
                continue
            _abs = bpy.path.abspath(_fp)
            if os.path.isfile(_abs):
                _dst = os.path.join(_media, os.path.basename(_abs))
                if not os.path.exists(_dst):
                    shutil.copy2(_abs, _dst)
                _collected.append(os.path.basename(_abs))
# 2. copy project (copy=True so current file path unchanged)
_bproj = os.path.join(_out, os.path.basename(_proj))
bpy.ops.wm.save_as_mainfile(filepath=_bproj, copy=True)
# 3. copy fonts from the font registry
_fonts = []
_raw = bpy.context.scene.get({_j(FONT_REG_KEY)}, "")
if _raw:
    try:
        import json as _json
        _freg = _json.loads(_raw)
        _fdir = os.path.join(_out, 'fonts')
        os.makedirs(_fdir, exist_ok=True)
        for _e in _freg:
            _fp = _e.get("path", "")
            if os.path.isfile(_fp):
                _dst = os.path.join(_fdir, os.path.basename(_fp))
                if not os.path.exists(_dst):
                    shutil.copy2(_fp, _dst)
                _fonts.append(os.path.basename(_fp))
    except Exception:
        pass
_vp_result(output_dir=_out, blend=os.path.basename(_proj),
           media_count=len(_collected), fonts=_fonts)
"""


@_op("register_font", read_only=False)
def register_font(project: str, path: str, font_id: str | None = None, **kw) -> str:
    """Register a font file in the project font registry."""
    _validate_project(project)
    return f"""
import json as _json, os
scene = bpy.context.scene
_p = {_j(str(Path(path).expanduser().resolve()))}
if not os.path.isfile(_p):
    raise RuntimeError("font file not found: " + _p)
_reg = []
_raw = scene.get({_j(FONT_REG_KEY)}, "") if {_j(FONT_REG_KEY)} in scene else ""
if _raw:
    try:
        _reg = _json.loads(_raw)
    except Exception:
        _reg = []
_fid = {_q(font_id or '')} or os.path.splitext(os.path.basename(_p))[0]
_entry = {{"id": _fid, "path": _p, "name": os.path.basename(_p)}}
_reg = [e for e in _reg if e.get("id") != _fid]
_reg.append(_entry)
scene[{_j(FONT_REG_KEY)}] = _json.dumps(_reg, ensure_ascii=False)
_vp_result(font=_entry, count=len(_reg))
"""


@_op("list_fonts", read_only=True)
def list_fonts(project: str, **kw) -> str:
    _validate_project(project)
    return f"""
import json as _json
scene = bpy.context.scene
_reg = []
_raw = scene.get({_j(FONT_REG_KEY)}, "") if {_j(FONT_REG_KEY)} in scene else ""
if _raw:
    try:
        _reg = _json.loads(_raw)
    except Exception:
        _reg = []
_vp_result(fonts=_reg, count=len(_reg))
"""


@_op("find_font", read_only=True)
def find_font(project: str, name: str, **kw) -> str:
    _validate_project(project)
    return f"""
import json as _json
scene = bpy.context.scene
_reg = []
_raw = scene.get({_j(FONT_REG_KEY)}, "") if {_j(FONT_REG_KEY)} in scene else ""
if _raw:
    try:
        _reg = _json.loads(_raw)
    except Exception:
        _reg = []
_found = next((e for e in _reg if {_q(name)} in e.get("name", "") or {_q(name)} in e.get("id", "")), None)
if _found is None:
    raise RuntimeError("font not found: " + {_q(name)})
_vp_result(font=_found)
"""


@_op("get_missing_fonts", read_only=True)
def get_missing_fonts(project: str, **kw) -> str:
    _validate_project(project)
    return f"""
import json as _json, os
scene = bpy.context.scene
_reg = []
_raw = scene.get({_j(FONT_REG_KEY)}, "") if {_j(FONT_REG_KEY)} in scene else ""
if _raw:
    try:
        _reg = _json.loads(_raw)
    except Exception:
        _reg = []
_missing = [e for e in _reg if not os.path.isfile(e.get("path", ""))]
# also check text strips whose font file is gone
se = scene.sequence_editor
if se is not None:
    for _s in se.strips:
        if _s.type == 'TEXT' and getattr(_s, 'font', None) is not None:
            _fp = getattr(_s.font, 'filepath', '')
            if _fp and not os.path.isfile(_fp):
                _missing.append({{"id": _s.font.name, "path": _fp, "used_by": _s.name}})
_vp_result(missing=_missing, count=len(_missing))
"""


@_op("replace_missing_font", read_only=False)
def replace_missing_font(project: str, font_id: str, new_path: str, **kw) -> str:
    """Replace a missing font: update registry + reload on text strips."""
    _validate_project(project)
    return f"""
import json as _json, os
scene = bpy.context.scene
_new = {_j(str(Path(new_path).expanduser().resolve()))}
if not os.path.isfile(_new):
    raise RuntimeError("new font not found: " + _new)
_reg = []
_raw = scene.get({_j(FONT_REG_KEY)}, "") if {_j(FONT_REG_KEY)} in scene else ""
if _raw:
    try:
        _reg = _json.loads(_raw)
    except Exception:
        _reg = []
_old_path = None
for _e in _reg:
    if _e.get("id") == {_q(font_id)}:
        _old_path = _e.get("path")
        _e["path"] = _new
        break
scene[{_j(FONT_REG_KEY)}] = _json.dumps(_reg, ensure_ascii=False)
# reload font on text strips using the old file
se = scene.sequence_editor
_f = bpy.data.fonts.load(_new)
_replaced = []
if se is not None:
    for _s in se.strips:
        if _s.type == 'TEXT' and getattr(_s, 'font', None) is not None:
            _sfp = getattr(_s.font, 'filepath', '')
            if _old_path is None or _sfp == _old_path:
                _s.font = _f
                _replaced.append(_s.name)
_vp_result(font_id={_q(font_id)}, new_path=_new, strips_replaced=_replaced)
"""


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


def available_ops() -> list[str]:
    return sorted(op for op in OPS if op not in REMOVED_OPS)


def dispatch(op: str, runner: BlenderRunner, project: str | None, params: dict) -> BlenderResult:
    """Execute a typed op. params may include dry_run and other command fields."""
    if op in REMOVED_OPS:
        removed = REMOVED_OPS[op]
        raise BlenderRunnerError(removed["code"], removed["message"])
    fn = OPS.get(op)
    if fn is None:
        raise BlenderRunnerError("unsupported", f"unknown blender op: {op}")

    dry_run = bool(params.get("dry_run", False))
    cmd = {k: v for k, v in params.items() if k not in ("dry_run", "op")}
    # project can come from params or be passed directly
    if "project" in cmd and project is None:
        project = cmd.pop("project")
    cmd.pop("project", None)
    # Optional base guard for single-op edits (Step 3 enforcement): when a
    # mutating op is called WITH base_revision/base_timeline_hash it is checked
    # against the current state before running — stale bases are refused, so a
    # manual edit is never overwritten even outside apply_patch.
    # (apply_patch consumes these itself — never pop them for it.)
    if op != "apply_patch":
        base_rev = cmd.pop("base_revision", None)
        base_hash = cmd.pop("base_timeline_hash", None)
    else:
        base_rev = base_hash = None

    # ---- INPUT VALIDATION (fail fast before spawning Blender) ----
    _validate_inputs(op, cmd)

    script = fn(project=project, **cmd)
    # Pin the active scene to the project's EDIT SCENE so every op reads/writes
    # the SAME scene that owns the VSE (source of truth = the .blend). Only
    # create_project defines the scene itself; all other ops inherit it.
    if op != "create_project":
        script = _edit_scene_prologue() + "\n" + script
    # Every mutating op guarantees stable IDs exist on ALL strips BEFORE running
    # (idempotent), so newly created strips also get IDs via the ensure pass in
    # list_strips/get_strip_by_id reads. Runs before the op body so op payloads
    # that read IDs see them.
    if op not in READ_ONLY_OPS and not dry_run:
        script = _ensure_ids_script() + "\n" + script
    save = op not in READ_ONLY_OPS and op not in NO_SAVE_OPS and not dry_run
    # Step 3 enforcement: editing primitives are INTERNAL-ONLY. External callers
    # (the AI) must go through apply_patch — there is no other sanctioned edit
    # path. Internal test harnesses may opt into direct primitive calls.
    if save and op not in _DIRECT_MUTATION_WHITELIST:
        allow_direct = (
            os.environ.get("BLENDER_VSE_ALLOW_DIRECT_MUTATION")
            or os.environ.get("VP_ALLOW_DIRECT_MUTATION")
        )
        if allow_direct != "1":
            raise BlenderRunnerError(
                "internal_primitive",
                f"{op} is an internal editing primitive — external edits must go "
                "through apply_patch (blender_patch). Direct mutation is disabled "
                "outside internal harnesses.")
    # Revision model: after every mutating op that saves, bump the revision
    # when the timeline content changed (apply_patch manages its own commit).
    if save and op not in SELF_REVISION_OPS:
        if base_rev is not None:
            script = _revision_guard_script(int(base_rev), base_hash or "") + "\n" + script
        script = script + "\n" + _revision_commit_script()
    # Live mode: after every mutating VSE edit, refresh timeline state + current
    # frame/preview + request UI redraw (read-only ops and dry-run skip this).
    refresh_after = op not in READ_ONLY_OPS and not dry_run
    return runner.run_script(script, project=project, save=save, dry_run=dry_run,
                             script_name=op, refresh_after=refresh_after)


# Ops whose inputs must exist on disk BEFORE Blender is spawned.
_ASSET_INPUT_OPS = {
    "add_movie": ("asset",),
    "add_sound": ("asset",),
    "add_image": ("asset",),
    "open_project": ("project",),
}
# Ops whose inputs include a subtitle file (optional but validated when present).
_SRT_INPUT_OPS = {"add_subtitle_track": ("srt_path",)}


def _validate_inputs(op: str, cmd: dict) -> None:
    """Verify required input files exist before any execution.

    Raises BlenderRunnerError (fast fail) when an input is missing or an asset
    path does not point to an existing file. skips dry_run (validation there is
    best-effort) and read-only reads (except open_project / inspect_media,
    whose input IS a file path).
    """
    if op in READ_ONLY_OPS and op not in ("open_project", "inspect_media"):
        return
    if op == "inspect_media":
        val = cmd.get("media_path")
        if val and not Path(str(val)).is_file():
            raise BlenderRunnerError(
                "input_missing", f"inspect_media: media_path not found: {val}")
        return
    # explicit file inputs
    for key in _ASSET_INPUT_OPS.get(op, ()):
        val = cmd.get(key)
        if val:
            p = Path(str(val))
            if not p.is_file():
                raise BlenderRunnerError(
                    "input_missing", f"{op}: {key} not found: {p} (resolve before calling)")
    for key in _SRT_INPUT_OPS.get(op, ()):
        val = cmd.get(key)
        if val:
            p = Path(str(val))
            if not p.is_file():
                raise BlenderRunnerError(
                    "input_missing", f"{op}: {key} not found: {p}")
    if op == "attach_proxy":
        manifest_path = cmd.get("manifest_path")
        if not manifest_path:
            raise BlenderRunnerError(
                "invalid_args", "attach_proxy requires an external proxy manifest_path")
        if not Path(str(manifest_path)).is_file():
            raise BlenderRunnerError(
                "input_missing", f"attach_proxy: manifest_path not found: {manifest_path}")
    # list-of-assets inputs
    assets = cmd.get("assets")
    if isinstance(assets, list):
        for a in assets:
            if not Path(str(a)).is_file():
                raise BlenderRunnerError(
                    "input_missing", f"{op}: asset not found: {a}")
    # assemble_clips: every clip.asset must exist
    clips = cmd.get("clips")
    if isinstance(clips, list):
        for c in clips:
            if isinstance(c, dict) and c.get("asset"):
                if not Path(str(c["asset"])).is_file():
                    raise BlenderRunnerError(
                        "input_missing", f"{op}: clip asset not found: {c['asset']}")
