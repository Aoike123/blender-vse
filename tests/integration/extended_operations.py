"""Extended editing operations: text style presets,
subtitle surgery (split/merge/retime/shift/replace/delete-range/SRT io),
keyframes + animation presets, audio (fades/pan/ducking), asset registry,
channel roles, frame/range/contact-sheet render, project packaging, fonts.

Also runs the user's completion-standard workflow: read timeline -> 30 chained
modifications -> mid-failure batch rollback -> save -> verify_persistence.

Run through: python tests/run.py blender-full
Requires a live GUI bridge (interactive ops) — skipped otherwise.
"""
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from blender_vse.blender import blender_execute, live_session_available
from blender_vse.blender.live_session import execute_code as _live_exec

MEDIA = ROOT / "tests" / "fixtures" / "media"
PROJECT = ROOT / "projects" / "extended_test.blend"
OUT = ROOT / "projects"
TMP = ROOT / ".tmp"

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, ok))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail and not ok else ""))
    return ok


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
    print("=== Extended editing operations ===")
    if not live_session_available():
        print("[SKIP] no live bridge (interactive ops require it)")
        sys.exit(0)
    proj = resolve_project()
    blender_execute("clear_vse", {"project": proj})
    blender_execute("create_project", {"project": proj, "resolution": [1280, 720], "fps": 30})
    # clear scene-level registries (fonts/assets/styles/roles) so re-runs are
    # deterministic — these live in scene custom props, clear_vse doesn't reset them
    _live_exec(
        "import bpy\n"
        "s = bpy.context.scene\n"
        "for _k in ('video_ai_fonts', 'video_ai_assets', 'video_ai_text_styles', "
        "'video_ai_channel_roles'):\n"
        "    try:\n"
        "        del s[_k]\n"
        "    except Exception:\n"
        "        pass\n")
    # deterministic base timeline
    blender_execute("add_movie", {"project": proj, "asset": str(MEDIA / "clip_a.mp4"),
                                  "channel": 1, "frame_start": 1, "strip_name": "clipA"})
    blender_execute("add_movie", {"project": proj, "asset": str(MEDIA / "clip_b.mp4"),
                                  "channel": 1, "frame_start": 151, "strip_name": "clipB"})
    blender_execute("add_sound", {"project": proj, "asset": str(MEDIA / "music.mp3"),
                                  "channel": 2, "frame_start": 1, "strip_name": "music"})
    blender_execute("add_text", {"project": proj, "text": "Hello", "channel": 3,
                                 "frame_start": 1, "length": 120, "strip_name": "Title",
                                 "font_size": 60})
    tl = blender_execute("list_strips", {"project": proj})
    strips = (tl.get("data") or {}).get("strips", [])
    clipA = next(s for s in strips if s["name"] == "clipA")
    clipB = next(s for s in strips if s["name"] == "clipB")
    music = next(s for s in strips if s["name"] == "music")
    title = next(s for s in strips if s["name"] == "Title")
    a_id, b_id, m_id, t_id = (clipA["video_ai_id"], clipB["video_ai_id"],
                              music["video_ai_id"], title["video_ai_id"])

    # =====================================================================
    # 1. Text style presets
    # =====================================================================
    check("create_text_style", blender_execute("create_text_style", {"project": proj, "name": "big",
        "style": {"font_size": 72, "alignment": "CENTER", "outline": True, "color": [1, 1, 1, 1]}}).get("ok"))
    check("create_text_style small", blender_execute("create_text_style", {"project": proj, "name": "small",
        "style": {"font_size": 24, "position": [0.5, 0.1]}}).get("ok"))
    r = blender_execute("update_text_style", {"project": proj, "name": "big", "style": {"font_size": 80}})
    check("update_text_style", r.get("ok"))
    r = blender_execute("list_text_styles", {"project": proj})
    styles = (r.get("data") or {}).get("styles", {}) if r.get("ok") else {}
    check("list_text_styles (2)", r.get("ok") and r["data"]["count"] == 2
          and set(styles.keys()) == {"big", "small"}, str(sorted(styles.keys())))
    check("big.font_size updated to 80", styles.get("big", {}).get("font_size") == 80)
    r = blender_execute("apply_text_style", {"project": proj, "style": "big", "target": "Title"})
    check("apply_text_style", r.get("ok") and r["data"]["count"] == 1)
    tl = blender_execute("list_strips", {"project": proj, "with_text": True})
    t_now = next(s for s in (tl.get("data") or {}).get("strips", []) if s["name"] == "Title")
    check("style applied (font_size 80, CENTER)", t_now.get("font_size") == 80.0
          and t_now.get("alignment_x") == "CENTER")

    # =====================================================================
    # 2. Subtitles: import -> split -> replace -> retime -> shift -> merge
    #    -> export -> delete-range (SRT round trip)
    # =====================================================================
    srt_in = TMP / "extended_in.srt"
    TMP.mkdir(exist_ok=True)
    srt_in.write_text(
        "1\n00:00:01,000 --> 00:00:03,000\nFirst line\n\n"
        "2\n00:00:03,500 --> 00:00:06,000\nSecond line\n\n"
        "3\n00:00:06,500 --> 00:00:09,000\nThird line\n", encoding="utf-8")
    r = blender_execute("import_srt", {"project": proj, "srt_path": str(srt_in),
                                       "channel": 4, "fps": 30, "strip_prefix": "Sub_"})
    check("import_srt", r.get("ok"))
    tl = blender_execute("list_strips", {"project": proj, "with_text": True})
    subs = [s for s in (tl.get("data") or {}).get("strips", [])
            if s["type"] == "TEXT" and s["name"].startswith("Sub_")]
    check("3 subtitle strips", len(subs) == 3, str([s["name"] for s in subs]))
    check("subtitle text has no timestamp junk",
          all("-->" not in (s.get("text") or "") for s in subs),
          str([s.get("text") for s in subs]))
    subs_sorted = sorted(subs, key=lambda s: s["frame_start"])
    s1, s2, s3 = subs_sorted[0]["video_ai_id"], subs_sorted[1]["video_ai_id"], subs_sorted[2]["video_ai_id"]

    r = blender_execute("split_subtitle", {"project": proj, "video_ai_id": s1, "frame": 40})
    check("split_subtitle", r.get("ok") and len(r["data"]["parts"]) == 2)
    r = blender_execute("replace_subtitle_text", {"project": proj, "video_ai_id": s2, "text": "Changed text"})
    check("replace_subtitle_text", r.get("ok") and r["data"]["text"] == "Changed text")
    r = blender_execute("retime_subtitles", {"project": proj, "video_ai_ids": [s3], "offset_frames": 30})
    check("retime_subtitles", r.get("ok") and r["data"]["count"] == 1)
    r = blender_execute("shift_subtitles", {"project": proj, "video_ai_ids": [s3], "delta_frames": -10})
    check("shift_subtitles", r.get("ok") and r["data"]["count"] == 1)
    r = blender_execute("merge_subtitles", {"project": proj, "video_ai_ids": [s2, s3]})
    check("merge_subtitles", r.get("ok") and r["data"]["text"] == "Changed text Third line",
          r.get("data", {}).get("text") if r.get("ok") else str(r.get("error")))

    srt_out = TMP / "extended_out.srt"
    r = blender_execute("export_srt", {"project": proj, "output_path": str(srt_out),
                                       "channel": 4, "fps": 30})
    # export runs BEFORE delete-range: ch4 holds split halves (2) + merged (1) = 3
    check("export_srt (3 entries)", r.get("ok") and r["data"]["count"] == 3,
          f"count={r['data'].get('count')}" if r.get("ok") else str(r.get("error")))
    srt_blocks = [b for b in srt_out.read_text(encoding="utf-8").split("\n\n") if b.strip()] \
        if srt_out.exists() else []
    srt_texts = []
    for _b in srt_blocks:
        _lines = _b.strip().splitlines()
        _txt = _lines[-1].strip() if _lines else ""
        srt_texts.append(_txt)
        check(f"srt entry text clean ({_txt[:20]!r})", "-->" not in _txt and not _txt.isdigit())
    check("srt last entry = merged text", bool(srt_texts) and srt_texts[-1] == "Changed text Third line",
          str(srt_texts))

    r = blender_execute("delete_subtitle_range", {"project": proj, "start_frame": 1,
                                                  "end_frame": 45, "channel": 4})
    check("delete_subtitle_range", r.get("ok") and r["data"]["count"] == 2)
    tl = blender_execute("list_strips", {"project": proj})
    text_count = len([s for s in (tl.get("data") or {}).get("strips", []) if s["type"] == "TEXT"])
    check("2 text strips remain (Title + merged)", text_count == 2, f"count={text_count}")

    # =====================================================================
    # 3. Keyframes + animation presets
    # =====================================================================
    check("add_keyframe", blender_execute("add_keyframe", {"project": proj, "video_ai_id": a_id,
        "frame": 1, "props": {"blend_alpha": 0.0}}).get("ok"))
    check("add_keyframe 2", blender_execute("add_keyframe", {"project": proj, "video_ai_id": a_id,
        "frame": 30, "props": {"blend_alpha": 1.0}}).get("ok"))
    r = blender_execute("list_keyframes", {"project": proj, "video_ai_id": a_id})
    check("list_keyframes (2)", r.get("ok") and len(r["data"]["frames"]) == 2)
    check("fade_in", blender_execute("fade_in", {"project": proj, "video_ai_id": a_id,
                                                 "duration_frames": 12}).get("ok"))
    check("fade_out", blender_execute("fade_out", {"project": proj, "video_ai_id": a_id,
                                                   "duration_frames": 12}).get("ok"))
    r = blender_execute("zoom_in", {"project": proj, "video_ai_id": a_id, "scale": 1.2,
                                    "duration_frames": 12})
    check("zoom_in", r.get("ok") and r["data"].get("preset") == "zoom_in")
    r = blender_execute("punch_in", {"project": proj, "video_ai_id": a_id, "scale": 1.1,
                                     "duration_frames": 6})
    check("punch_in", r.get("ok") and r["data"].get("preset") == "punch_in")
    r = blender_execute("list_keyframes", {"project": proj, "video_ai_id": a_id})
    check("presets recorded", r.get("ok") and set(r["data"]["presets"]) >=
          {"fade_in", "fade_out", "zoom_in", "punch_in"})
    check("clear_keyframes", blender_execute("clear_keyframes", {"project": proj,
                                                                 "video_ai_id": a_id}).get("ok"))
    r = blender_execute("list_keyframes", {"project": proj, "video_ai_id": a_id})
    check("keyframes cleared", r.get("ok") and r["data"]["frames"] == [])

    # =====================================================================
    # 4. Audio: fades / pan / ducking
    # =====================================================================
    check("fade_audio_in", blender_execute("fade_audio_in", {"project": proj, "video_ai_id": m_id,
                                                             "duration_frames": 12}).get("ok"))
    check("fade_audio_out", blender_execute("fade_audio_out", {"project": proj, "video_ai_id": m_id,
                                                               "duration_frames": 12}).get("ok"))
    r = blender_execute("set_pan", {"project": proj, "video_ai_id": m_id, "pan": 0.5})
    check("set_pan", r.get("ok") and abs(r["data"]["pan"] - 0.5) < 1e-6)
    r = blender_execute("duck_audio", {"project": proj, "video_ai_id": m_id, "under": "clipA",
                                       "reduction_db": -6.0})
    check("duck_audio", r.get("ok") and r["data"]["windows"] >= 1)

    # =====================================================================
    # 5. Legacy Blender asset registry is externalized in Stage 1.
    # =====================================================================
    legacy_asset_ops = (
        "import_asset", "list_assets", "get_asset", "inspect_asset",
        "remove_asset", "find_missing_assets", "relink_asset", "replace_asset",
    )
    legacy_results = [blender_execute(op, {"project": proj}) for op in legacy_asset_ops]
    check(
        "legacy Blender asset registry is externalized",
        all(
            not result.get("ok")
            and (result.get("error") or {}).get("code") == "asset_registry_externalized"
            for result in legacy_results
        ),
    )

    # =====================================================================
    # 6. Channel roles
    # =====================================================================
    check("set_channel_role video", blender_execute("set_channel_role", {"project": proj,
        "channel": 1, "role": "video"}).get("ok"))
    check("set_channel_role subtitles", blender_execute("set_channel_role", {"project": proj,
        "channel": 4, "role": "subtitles"}).get("ok"))
    r = blender_execute("get_channel_roles", {"project": proj})
    roles = (r.get("data") or {}).get("roles", {}) if r.get("ok") else {}
    check("get_channel_roles", roles.get("1") == "video" and roles.get("4") == "subtitles",
          str(roles))

    # =====================================================================
    # 7. Render: frame / range / contact sheet
    # =====================================================================
    frame_png = OUT / "extended_frame.png"
    r = blender_execute("render_frame", {"project": proj, "output_path": str(frame_png), "frame": 15})
    check("render_frame", r.get("ok") and r["data"]["exists"] and frame_png.is_file())
    sheet_png = OUT / "extended_sheet.png"
    r = blender_execute("generate_contact_sheet", {"project": proj, "output_path": str(sheet_png),
                                                   "frames": [5, 15, 25], "cols": 3})
    check("generate_contact_sheet", r.get("ok") and r["data"]["exists"] and sheet_png.is_file())
    range_mp4 = OUT / "extended_range.mp4"
    r = blender_execute("render_range", {"project": proj, "output_path": str(range_mp4),
                                         "start_frame": 1, "end_frame": 15,
                                         "resolution": [320, 180]})
    check("render_range", r.get("ok") and range_mp4.is_file() and range_mp4.stat().st_size > 0)

    # =====================================================================
    # 8. Project packaging
    # =====================================================================
    copy_path = OUT / "extended_copy.blend"
    r = blender_execute("save_project_copy", {"project": proj, "copy_path": str(copy_path)})
    check("save_project_copy", r.get("ok") and r["data"]["exists"] and copy_path.is_file())
    r = blender_execute("collect_project_assets", {"project": proj,
        "dest_dir": str(TMP / "extended_pkg_media")})
    check("collect_project_assets", r.get("ok") and r["data"]["count"] >= 1)
    r = blender_execute("package_project", {"project": proj, "output_dir": str(TMP / "extended_pkg_out")})
    check("package_project", r.get("ok") and r["data"]["media_count"] >= 1
          and (TMP / "extended_pkg_out").is_dir())

    # =====================================================================
    # 9. Font registry
    # =====================================================================
    font = Path(r"C:\Windows\Fonts\arial.ttf")
    if not font.is_file():
        for f in Path(r"C:\Windows\Fonts").iterdir():
            if f.suffix.lower() == ".ttf":
                font = f
                break
    check("register_font", blender_execute("register_font", {"project": proj,
        "path": str(font), "font_id": "arial"}).get("ok"))
    r = blender_execute("list_fonts", {"project": proj})
    check("list_fonts (1)", r.get("ok") and r["data"]["count"] == 1)
    check("find_font", blender_execute("find_font", {"project": proj, "name": "arial"}).get("ok"))
    tmp_font = TMP / "extended_tmp_font.ttf"
    shutil.copy2(font, tmp_font)
    check("register_font tmp", blender_execute("register_font", {"project": proj,
        "path": str(tmp_font), "font_id": "tmpfont"}).get("ok"))
    tmp_font.unlink()
    r = blender_execute("get_missing_fonts", {"project": proj})
    check("get_missing_fonts (1 missing)", r.get("ok") and r["data"]["count"] == 1)
    check("replace_missing_font", blender_execute("replace_missing_font", {"project": proj,
        "font_id": "tmpfont", "new_path": str(font)}).get("ok"))
    r = blender_execute("get_missing_fonts", {"project": proj})
    check("missing fonts resolved", r.get("ok") and r["data"]["count"] == 0)

    # =====================================================================
    # 10. Completion standard: read -> 30 chained mods -> failing batch
    #     rollback -> save -> verify_persistence
    # =====================================================================
    tl = blender_execute("list_strips", {"project": proj})
    check("workflow: read timeline", tl.get("ok") and len(tl["data"]["strips"]) == 5,
          f"strips={len(tl['data']['strips'])}" if tl.get("ok") else str(tl.get("error")))

    chain = [
        ("add_keyframe", {"video_ai_id": a_id, "frame": 5, "props": {"blend_alpha": 0.4}}),
        ("add_keyframe", {"video_ai_id": a_id, "frame": 10, "props": {"blend_alpha": 0.7}}),
        ("add_keyframe", {"video_ai_id": a_id, "frame": 15, "props": {"blend_alpha": 1.0}}),
        ("add_keyframe", {"video_ai_id": b_id, "frame": 160, "props": {"blend_alpha": 0.8}}),
        ("add_keyframe", {"video_ai_id": t_id, "frame": 2, "props": {"blend_alpha": 0.9}}),
        ("fade_in", {"video_ai_id": b_id, "duration_frames": 10}),
        ("fade_out", {"video_ai_id": b_id, "duration_frames": 10}),
        ("zoom_in", {"video_ai_id": b_id, "scale": 1.1, "duration_frames": 12}),
        ("punch_in", {"video_ai_id": b_id, "scale": 1.05, "duration_frames": 6}),
        ("fade_audio_in", {"video_ai_id": m_id, "duration_frames": 10}),
        ("fade_audio_out", {"video_ai_id": m_id, "duration_frames": 10}),
        ("set_pan", {"video_ai_id": m_id, "pan": -0.4}),
        ("set_volume", {"target": "music", "volume": 0.8}),
        ("set_opacity", {"target": "clipA", "opacity": 0.9}),
        ("apply_text_style", {"style": "small", "target": "Title"}),
        ("update_text_style", {"name": "small", "style": {"font_size": 26}}),
        ("apply_text_style", {"style": "small", "target": "Title"}),
        ("retime_subtitles", {"video_ai_ids": [s2], "offset_frames": 5}),
        ("shift_subtitles", {"video_ai_ids": [s2], "delta_frames": -2}),
        ("replace_subtitle_text", {"video_ai_id": s2, "text": "Workflow text"}),
        ("set_strip_metadata", {"video_ai_id": a_id, "metadata": {"role": "hero"}}),
        ("set_channel_role", {"channel": 2, "role": "music"}),
        ("set_channel_role", {"channel": 3, "role": "titles"}),
        ("add_marker", {"name": "W1", "frame": 60}),
        ("add_marker", {"name": "W2", "frame": 200, "metadata": {"k": "v"}}),
        ("move_playhead", {"delta_frames": 120}),
        ("register_font", {"path": str(font), "font_id": "arial2"}),
        ("set_strip_metadata", {"video_ai_id": b_id,
                                "metadata": {"role": "secondary", "asset_contract": "external"}}),
        ("create_text_style", {"name": "chain", "style": {"font_size": 30}}),
        ("apply_text_style", {"style": "chain", "target": "Title"}),
    ]
    assert len(chain) == 30, f"chain has {len(chain)} steps"
    failed = []
    for i, (op, p) in enumerate(chain):
        r = blender_execute(op, {"project": proj, **p})
        if not r.get("ok"):
            failed.append((i, op, r.get("error")))
    check("workflow: 30 chained modifications all ok", not failed,
          str(failed[:3]) if failed else "")

    # failing batch must roll back atomically
    r = blender_execute("batch", {"project": proj, "atomic": True, "commands": [
        {"op": "set_opacity", "target": "clipA", "opacity": 0.5},
        {"op": "delete_strip", "target": "definitely_missing_strip"},
    ]})
    check("workflow: failing batch rolled back", r.get("ok") and r["data"].get("rolled_back") is True)

    # save + persistence (fresh reopen of the .blend)
    r = blender_execute("save_project", {"project": proj})
    check("workflow: save_project", r.get("ok"))
    vp = blender_execute("verify_persistence", {"project": proj,
                                                "expected": {"movie": 2, "sound": 1, "text": 2}})
    check("workflow: verify_persistence ok", vp.get("ok"))
    if vp.get("ok"):
        d = vp["data"]
        check("persistence_verified=true", d.get("persistence_verified") is True)
        check("scene=VideoEditing", d.get("scene") == "VideoEditing")
        check("movie=2 sound=1 text=2", d.get("movie_strips") == 2
              and d.get("sound_strips") == 1 and d.get("text_strips") == 2,
              f"m={d.get('movie_strips')} s={d.get('sound_strips')} t={d.get('text_strips')}")
    # result still correct after reopen: style + merged subtitle text survive
    tl = blender_execute("list_strips", {"project": proj, "with_text": True})
    t_final = next((s for s in (tl.get("data") or {}).get("strips", [])
                    if s["name"] == "Title"), {})
    check("result still correct after reopen (style font_size 30)",
          t_final.get("font_size") == 30.0, f"font_size={t_final.get('font_size')}")

    passed = sum(1 for _, ok in RESULTS if ok)
    print(f"\n=== Extended operations: {passed}/{len(RESULTS)} passed ===")
    if passed < len(RESULTS):
        sys.exit(1)


if __name__ == "__main__":
    main()
