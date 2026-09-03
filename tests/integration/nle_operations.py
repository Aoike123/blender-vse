"""NLE operation tests: stable IDs, ripple, NLE edits, trims, reorder,
playhead, markers, gaps/overlaps, batch, checkpoints, capabilities.

Run through: python tests/run.py blender-full
Requires a live GUI bridge (interactive ops) — skipped otherwise.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from blender_vse.blender import blender_execute, live_session_available
from blender_vse.blender.live_session import execute_code as _live_exec

MEDIA = ROOT / "tests" / "fixtures" / "media"
PROJECT = ROOT / "projects" / "nle_test.blend"

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, ok))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail and not ok else ""))


def resolve_project() -> str:
    global PROJECT
    _fp = None
    _rr = _live_exec("import bpy; print('FP:' + repr(bpy.data.filepath))")
    for _l in (_rr.get("output") or "").splitlines():
        if _l.startswith("FP:"):
            _fp = _l[3:].strip().strip("'\"").strip('"') or None
    if _fp:
        PROJECT = Path(_fp)
    return str(PROJECT)


def main():
    global PROJECT
    print("=== NLE operations: AI NLE Core ===")
    if not live_session_available():
        print("[SKIP] no live bridge (interactive ops require it)")
        sys.exit(0)
    proj = resolve_project()
    blender_execute("clear_vse", {"project": proj})
    blender_execute("create_project", {"project": proj, "resolution": [1280, 720], "fps": 30})
    # clean leftover markers + test checkpoints so assertions are deterministic
    _live_exec("import bpy; [bpy.context.scene.timeline_markers.remove(m) "
               "for m in list(bpy.context.scene.timeline_markers)]")
    import os as _os
    _ckdir = _os.path.join(_os.path.dirname(proj), "checkpoints")
    if _os.path.isdir(_ckdir):
        for _f in _os.listdir(_ckdir):
            if _f.startswith("before_roughcut") and _f.endswith(".blend"):
                try:
                    _os.remove(_os.path.join(_ckdir, _f))
                except Exception:
                    pass

    # ---- 1. capabilities / list_operations / project info ----
    r = blender_execute("get_capabilities", {"project": proj})
    check("get_capabilities", r.get("ok"))
    if r.get("ok"):
        d = r["data"]
        check("plugin_version present", bool(d.get("plugin_version")))
        check("schema_version present", bool(d.get("schema_version")))
        check("blender_version present", bool(d.get("blender_version")))
    r = blender_execute("list_operations", {"project": proj})
    check("list_operations", r.get("ok") and len((r.get("data") or {}).get("operations", {})) > 0)
    r = blender_execute("get_project_info", {"project": proj})
    check("get_project_info", r.get("ok") and (r.get("data") or {}).get("strip_count") is not None)

    # ---- 2. assemble clips -> stable IDs auto-assigned ----
    r = blender_execute("assemble_clips", {"project": proj, "clips": [
        {"asset": str(MEDIA / "clip_a.mp4")},
        {"asset": str(MEDIA / "clip_b.mp4")},
        {"asset": str(MEDIA / "clip_a.mp4")},
    ], "channel": 1, "fps": 30, "strip_prefix": "Clip_"})
    check("assemble_clips", r.get("ok"))

    tl = blender_execute("list_strips", {"project": proj})
    strips = (tl.get("data") or {}).get("strips", [])
    movies = [s for s in strips if s["type"] == "MOVIE"]
    check("3 movie strips", len(movies) == 3)
    check("all have stable video_ai_id",
          all(m.get("video_ai_id") for m in movies),
          str([m.get("video_ai_id") for m in movies]))
    clip_ids = [m["video_ai_id"] for m in movies]
    check("ids are unique", len(set(clip_ids)) == 3)

    # ---- 3. get_strip_by_id / resolve_strip / find_strips ----
    r = blender_execute("get_strip_by_id", {"project": proj, "video_ai_id": clip_ids[0]})
    check("get_strip_by_id", r.get("ok") and (r.get("data") or {}).get("found") is True)
    r = blender_execute("resolve_strip", {"project": proj, "video_ai_id": clip_ids[1]})
    check("resolve_strip by id", r.get("ok") and (r.get("data") or {}).get("resolved_by") == "id")
    r = blender_execute("find_strips", {"project": proj, "type": "MOVIE"})
    check("find_strips by type", r.get("ok") and (r.get("data") or {}).get("count") == 3)

    # ---- 4. metadata ----
    r = blender_execute("set_strip_metadata", {"project": proj, "video_ai_id": clip_ids[0],
                                               "metadata": {"role": "broll", "speaker": "host"}})
    check("set_strip_metadata", r.get("ok"))
    r = blender_execute("get_strip_metadata", {"project": proj, "video_ai_id": clip_ids[0]})
    meta = (r.get("data") or {}).get("metadata", {}) if r.get("ok") else {}
    check("get_strip_metadata", r.get("ok") and meta.get("role") == "broll")
    r = blender_execute("find_strips", {"project": proj, "meta_key": "role", "meta_value": "broll"})
    check("find_strips by metadata", r.get("ok") and (r.get("data") or {}).get("count") == 1)

    # ---- 5. IDs survive rename ----
    r = blender_execute("get_strip_by_id", {"project": proj, "video_ai_id": clip_ids[0]})
    name_before = (r.get("data") or {}).get("name")
    r = blender_execute("set_text", {"project": proj, "target": name_before, "text": "x"})  # no-op for movie
    tl2 = blender_execute("list_strips", {"project": proj})
    movies2 = [s for s in (tl2.get("data") or {}).get("strips", []) if s["type"] == "MOVIE"]
    id_after = next((m["video_ai_id"] for m in movies2 if m["name"] == name_before), None)
    check("ID stable after ops", id_after == clip_ids[0])

    # ---- 6. ripple_delete ----
    r = blender_execute("ripple_delete", {"project": proj, "video_ai_id": clip_ids[1]})
    check("ripple_delete", r.get("ok"))
    tl3 = blender_execute("list_strips", {"project": proj})
    movies3 = [s for s in (tl3.get("data") or {}).get("strips", []) if s["type"] == "MOVIE"]
    check("2 movies after ripple_delete", len(movies3) == 2)
    # gap check: no gap on channel 1
    gaps = blender_execute("find_gaps", {"project": proj, "channel": 1})
    gap_list = (gaps.get("data") or {}).get("gaps", []) if gaps.get("ok") else []
    check("no gap after ripple_delete", len(gap_list) == 0, str(gap_list))

    # ---- 7. insert_edit (ripple insert) ----
    r = blender_execute("insert_edit", {"project": proj, "asset": str(MEDIA / "clip_b.mp4"),
                                        "channel": 1, "at_frame": 1, "strip_name": "inserted"})
    check("insert_edit", r.get("ok"))
    tl4 = blender_execute("list_strips", {"project": proj})
    movies4 = [s for s in (tl4.get("data") or {}).get("strips", []) if s["type"] == "MOVIE"]
    check("3 movies after insert_edit", len(movies4) == 3)
    first = min(movies4, key=lambda x: x["frame_start"])
    check("inserted clip is first (frame 1)", first["name"] == "inserted" and first["frame_start"] == 1)

    # ---- 8. reorder_clips ----
    ids = [m["video_ai_id"] for m in sorted(movies4, key=lambda x: x["frame_start"])]
    new_order = [ids[2], ids[0], ids[1]]
    r = blender_execute("reorder_clips", {"project": proj, "order": new_order,
                                          "channel": 1, "ripple": True})
    check("reorder_clips", r.get("ok"))
    tl5 = blender_execute("list_strips", {"project": proj})
    order5 = [m["video_ai_id"] for m in sorted(
        [s for s in (tl5.get("data") or {}).get("strips", []) if s["type"] == "MOVIE"],
        key=lambda x: x["frame_start"])]
    check("order matches requested", order5 == new_order, str(order5))

    # ---- 9. swap_clips ----
    a_id, b_id = order5[0], order5[2]
    r = blender_execute("swap_clips", {"project": proj, "a_id": a_id, "b_id": b_id})
    check("swap_clips", r.get("ok"))
    tl6 = blender_execute("list_strips", {"project": proj})
    order6 = [m["video_ai_id"] for m in sorted(
        [s for s in (tl6.get("data") or {}).get("strips", []) if s["type"] == "MOVIE"],
        key=lambda x: x["frame_start"])]
    check("swap reflected in order", order6[0] == b_id and order6[2] == a_id, str(order6))

    # ---- 10. slip / slide / nudge ----
    target = order6[0]
    r = blender_execute("slip", {"project": proj, "video_ai_id": target, "source_in": 0.5, "fps": 30})
    check("slip", r.get("ok") and (r.get("data") or {}).get("source_in") == 15)
    r = blender_execute("slide", {"project": proj, "video_ai_id": target, "frames": 10})
    check("slide", r.get("ok") and (r.get("data") or {}).get("delta_frames") == 10)
    r = blender_execute("nudge_start", {"project": proj, "video_ai_id": target, "frames": 5})
    check("nudge_start", r.get("ok"))
    r = blender_execute("nudge_end", {"project": proj, "video_ai_id": target, "frames": -5})
    check("nudge_end", r.get("ok"))

    # ---- 11. playhead ----
    r = blender_execute("set_playhead", {"project": proj, "frame": 300})
    check("set_playhead", r.get("ok"))
    r = blender_execute("get_playhead", {"project": proj})
    check("get_playhead", r.get("ok") and (r.get("data") or {}).get("playhead") == 300)
    r = blender_execute("move_playhead", {"project": proj, "delta_frames": 50})
    check("move_playhead", r.get("ok") and (r.get("data") or {}).get("playhead") == 350)

    # ---- 12. markers ----
    r = blender_execute("add_marker", {"project": proj, "name": "HOOK", "frame": 100,
                                       "metadata": {"type": "hook"}})
    check("add_marker", r.get("ok"))
    r = blender_execute("add_marker", {"project": proj, "name": "CTA", "frame": 900})
    check("add_marker 2", r.get("ok"))
    r = blender_execute("list_markers", {"project": proj})
    markers = (r.get("data") or {}).get("markers", []) if r.get("ok") else []
    check("list_markers (2)", len(markers) == 2)
    r = blender_execute("move_marker", {"project": proj, "name": "CTA", "frame": 950})
    check("move_marker", r.get("ok"))
    r = blender_execute("update_marker", {"project": proj, "name": "HOOK",
                                          "metadata": {"type": "hook", "color": "red"}})
    check("update_marker", r.get("ok"))
    r = blender_execute("list_markers", {"project": proj})
    hook = next((m for m in (r.get("data") or {}).get("markers", []) if m["name"] == "HOOK"), {})
    check("marker metadata persisted", (hook.get("meta") or {}).get("color") == "red")
    r = blender_execute("delete_marker", {"project": proj, "name": "CTA"})
    check("delete_marker", r.get("ok"))

    # ---- 13. gaps / overlaps / validate ----
    r = blender_execute("find_overlaps", {"project": proj})
    check("find_overlaps runs (may be 0)", r.get("ok"))
    r = blender_execute("validate_timeline", {"project": proj})
    check("validate_timeline", r.get("ok") and "valid" in (r.get("data") or {}))

    # ---- 14. batch + rollback ----
    # add a text strip so batch can exercise text ops; movie gets mute
    r = blender_execute("add_text", {"project": proj, "text": "batch test", "channel": 3,
                                     "frame_start": 1, "length": 60, "strip_name": "bt"})
    check("add_text for batch", r.get("ok"))
    r = blender_execute("batch", {"project": proj, "atomic": True, "commands": [
        {"op": "mute", "video_ai_id": order6[0], "mute": True},
        {"op": "set_font_size", "target": "bt", "font_size": 66},
    ]})
    check("batch ok", r.get("ok") and (r.get("data") or {}).get("ok") is True)
    # failing batch rolls back (file-level snapshot restored)
    r = blender_execute("batch", {"project": proj, "atomic": True, "commands": [
        {"op": "mute", "video_ai_id": order6[0], "mute": False},
        {"op": "delete_strip", "target": "does_not_exist"},
    ]})
    check("batch rollback on failure", r.get("ok") and (r.get("data") or {}).get("rolled_back") is True)

    # ---- 15. checkpoint ----
    r = blender_execute("create_checkpoint", {"project": proj, "name": "before_roughcut"})
    check("create_checkpoint", r.get("ok"))
    if r.get("ok"):
        check("checkpoint file exists", bool((r.get("data") or {}).get("exists")))
    r = blender_execute("list_checkpoints", {"project": proj})
    ckpts = (r.get("data") or {}).get("checkpoints", []) if r.get("ok") else []
    check("list_checkpoints has 1", len(ckpts) >= 1)

    # ---- 16. persistence ----
    vp = blender_execute("verify_persistence", {"project": proj})
    check("verify_persistence ok", vp.get("ok"))

    passed = sum(1 for _, ok in RESULTS if ok)
    print(f"\n=== NLE operations: {passed}/{len(RESULTS)} passed ===")
    if passed < len(RESULTS):
        sys.exit(1)


if __name__ == "__main__":
    main()
