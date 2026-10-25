"""Canonical operation catalog for Blender VSE Control.

The catalog is deliberately independent of Blender imports. Documentation,
CLI discovery, routing, execution policy, schemas, and tests all consume these
sets so they cannot silently drift apart.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

CATALOG_VERSION = "1.0"

OPERATION_FAMILIES: dict[str, tuple[str, ...]] = {
    "project": (
        "create_project",
        "open_project",
        "save_project",
        "get_project_info",
        "configure_vse_layout",
    ),
    "capabilities": (
        "get_capabilities",
        "list_operations",
    ),
    "timeline": (
        "list_strips",
        "get_timeline_info",
        "validate_timeline",
        "find_gaps",
        "find_overlaps",
        "clear_vse",
        "set_frame_range",
    ),
    "media": ("inspect_media",),
    "add": (
        "add_movie",
        "add_sound",
        "add_image",
        "add_image_sequence",
        "add_text",
        "add_subtitle_track",
        "assemble_clips",
        "add_color",
        "add_scene",
        "add_effect",
        "add_transition",
    ),
    "edit": (
        "delete_strip",
        "cut_strip",
        "trim_strip",
        "move",
        "change_channel",
        "mute",
        "lock",
        "set_speed",
        "set_blend",
        "set_opacity",
        "set_transform",
        "set_crop",
    ),
    "nle": (
        "ripple_delete",
        "ripple_insert",
        "close_gap",
        "close_all_gaps",
        "insert_edit",
        "overwrite_edit",
        "lift_edit",
        "extract_edit",
        "replace_clip",
        "slip",
        "slide",
        "roll_trim",
        "nudge_start",
        "nudge_end",
        "swap_clips",
        "reorder_clips",
    ),
    "text": (
        "set_text",
        "set_font",
        "set_font_size",
        "set_alignment",
        "set_outline",
        "set_shadow",
        "set_box",
        "set_text_position",
    ),
    "metadata": (
        "ensure_strip_ids",
        "get_strip_by_id",
        "resolve_strip",
        "find_strips",
        "set_strip_metadata",
        "get_strip_metadata",
    ),
    "playhead": (
        "get_playhead",
        "set_playhead",
        "move_playhead",
    ),
    "markers": (
        "list_markers",
        "add_marker",
        "update_marker",
        "move_marker",
        "delete_marker",
    ),
    "checkpoints": (
        "batch",
        "create_checkpoint",
        "list_checkpoints",
        "delete_checkpoint",
    ),
    "text_styles": (
        "create_text_style",
        "update_text_style",
        "delete_text_style",
        "list_text_styles",
        "apply_text_style",
    ),
    "subtitles": (
        "split_subtitle",
        "merge_subtitles",
        "retime_subtitles",
        "shift_subtitles",
        "replace_subtitle_text",
        "delete_subtitle_range",
        "import_srt",
        "export_srt",
    ),
    "animation": (
        "add_keyframe",
        "update_keyframe",
        "delete_keyframe",
        "set_keyframe_interpolation",
        "list_keyframes",
        "clear_keyframes",
        "fade_in",
        "fade_out",
        "zoom_in",
        "zoom_out",
        "slide_in",
        "slide_out",
        "punch_in",
        "punch_out",
    ),
    "audio": (
        "set_volume",
        "fade_audio_in",
        "fade_audio_out",
        "set_pan",
        "duck_audio",
        "mute_range",
        "set_volume_range",
    ),
    "asset_binding": (
        "bind_asset",
        "relink_asset_binding",
        "replace_asset_binding",
    ),
    "proxy": (
        "attach_proxy",
        "detach_proxy",
        "clear_proxies",
        "get_proxy_status",
    ),
    "channel_roles": (
        "set_channel_role",
        "get_channel_roles",
    ),
    "render": (
        "render_preview",
        "render_final",
        "render_frame",
        "render_range",
        "generate_contact_sheet",
        "sample_frame",
    ),
    "revision": (
        "get_revision",
        "apply_patch",
        "acknowledge_revision",
    ),
    "packaging": (
        "save_project_copy",
        "collect_project_assets",
        "package_project",
    ),
    "fonts": (
        "register_font",
        "list_fonts",
        "find_font",
        "get_missing_fonts",
        "replace_missing_font",
    ),
    "persistence": ("verify_persistence",),
}

_family_members = tuple(
    operation
    for operations in OPERATION_FAMILIES.values()
    for operation in operations
)
PUBLIC_OPERATIONS = frozenset(_family_members)

# A control-plane command is valid inside the high-level API but must never be
# dispatched as an in-memory Blender operation.
CONTROL_PLANE_COMMANDS = frozenset({"restore_checkpoint"})

# These primitives support the checkpoint control transaction and are not
# part of the public router or CLI catalog.
INTERNAL_OPERATIONS = frozenset(
    {"validate_checkpoint_restore", "finalize_checkpoint_restore"}
)

HEADLESS_OPERATIONS = frozenset(
    {"render_preview", "render_final", "verify_persistence", "inspect_media"}
)
PROJECT_OPTIONAL_OPERATIONS = frozenset({"inspect_media"})

RUNTIME_ERROR_CODES = frozenset(
    {
        "asset_binding_stale",
        "asset_binding_type_mismatch",
        "asset_registry_externalized",
        "asset_source_mismatch",
        "batch",
        "input_missing",
        "invalid_read_token",
        "invalid_render_range",
        "overlap_detected",
        "preview_resolution_must_be_integer_scale",
        "proxy_custom_file_unsupported",
        "proxy_source_mismatch",
        "revision_mismatch",
        "stale_base",
        "stale_observation",
        "strip_not_found",
        "vse_scene_mismatch",
        "vse_scene_unbound",
        "vse_visible_strip_mismatch",
        "window_ambiguous",
    }
)

ERROR_CODES = RUNTIME_ERROR_CODES | frozenset(
    {
        "backup_failed",
        "blender_exited",
        "blender_missing",
        "bootstrap_missing",
        "bridge_error",
        "bridge_not_ready",
        "bridge_unreachable",
        "checkpoint_copy_failed",
        "checkpoint_not_found",
        "checkpoint_reopen_failed",
        "context_budget_exceeded",
        "execution_failed",
        "gui_not_stable",
        "gui_not_visible",
        "hidden_session_repair_failed",
        "internal_primitive",
        "invalid_args",
        "invalid_cli_input",
        "invalid_cursor",
        "invalid_proxy_manifest",
        "invalid_read_query",
        "launch_failed",
        "not_found",
        "operation_externalized",
        "patch_rolled_back",
        "project_mismatch",
        "project_not_found",
        "project_open_failed",
        "proxy_generation_externalized",
        "read_required",
        "restore_session_close_failed",
        "restore_session_close_timeout",
        "restore_session_not_ready",
        "session_close_failed",
        "session_discovery_timeout",
        "session_identity_pending",
        "session_not_ready",
        "stale_cursor",
        "stale_proxy_source",
        "timeout",
        "unsaved_session_dirty",
        "unsupported",
        "validation_failed",
        "vse_content_not_framed",
        "vse_current_frame_empty",
        "vse_media_missing",
        "vse_not_visible",
    }
)

READ_ONLY_OPERATIONS = frozenset(
    {
        "open_project",
        "list_strips",
        "get_timeline_info",
        "get_capabilities",
        "list_operations",
        "get_project_info",
        "validate_timeline",
        "get_strip_by_id",
        "resolve_strip",
        "find_strips",
        "get_strip_metadata",
        "get_playhead",
        "list_markers",
        "find_gaps",
        "find_overlaps",
        "list_checkpoints",
        "list_text_styles",
        "export_srt",
        "list_keyframes",
        "get_channel_roles",
        "get_proxy_status",
        "inspect_media",
        "get_revision",
        "list_fonts",
        "find_font",
        "get_missing_fonts",
        "verify_persistence",
    }
)

REMOVED_OPERATIONS: dict[str, dict[str, str]] = {
    "generate_proxy": {
        "code": "proxy_generation_externalized",
        "message": (
            "Blender-side proxy generation is not supported; build an FFmpeg "
            "proxy manifest externally, then call attach_proxy with manifest_path"
        ),
    },
    "rebuild_proxy": {
        "code": "proxy_generation_externalized",
        "message": (
            "Blender-side proxy rebuilding is not supported; rebuild the FFmpeg "
            "proxy externally, then call attach_proxy with manifest_path"
        ),
    },
    "restore_checkpoint": {
        "code": "operation_externalized",
        "message": (
            "checkpoint restore is a control-plane transaction; pass it as the "
            "only command to BlenderVSE.patch"
        ),
    },
    "import_asset": {
        "code": "operation_externalized",
        "message": "the host application owns asset registration; use bind_asset",
    },
    "list_assets": {
        "code": "operation_externalized",
        "message": "the host application owns the asset registry",
    },
    "get_asset": {
        "code": "operation_externalized",
        "message": "the host application owns the asset registry",
    },
    "inspect_asset": {
        "code": "operation_externalized",
        "message": "the host application owns asset inspection",
    },
    "remove_asset": {
        "code": "operation_externalized",
        "message": "the host application owns asset registration",
    },
    "find_missing_assets": {
        "code": "operation_externalized",
        "message": "the host application owns asset diagnostics",
    },
    "relink_asset": {
        "code": "operation_externalized",
        "message": "use relink_asset_binding with a host-owned asset ID",
    },
    "replace_asset": {
        "code": "operation_externalized",
        "message": "use replace_asset_binding with a host-owned asset ID",
    },
}


def duplicate_family_members() -> set[str]:
    """Return operations assigned to more than one family."""

    return {
        operation
        for operation, count in Counter(_family_members).items()
        if count > 1
    }


def operation_catalog() -> dict[str, Any]:
    """Return a stable JSON-serializable capability manifest."""

    return {
        "catalog_version": CATALOG_VERSION,
        "operations": sorted(PUBLIC_OPERATIONS),
        "families": {
            family: sorted(operations)
            for family, operations in OPERATION_FAMILIES.items()
        },
        "read_only": sorted(READ_ONLY_OPERATIONS),
        "headless": sorted(HEADLESS_OPERATIONS),
        "project_optional": sorted(PROJECT_OPTIONAL_OPERATIONS),
        "control_plane": sorted(CONTROL_PLANE_COMMANDS),
        "internal": sorted(INTERNAL_OPERATIONS),
        "removed": {
            name: dict(details) for name, details in sorted(REMOVED_OPERATIONS.items())
        },
        "error_codes": sorted(ERROR_CODES),
    }
