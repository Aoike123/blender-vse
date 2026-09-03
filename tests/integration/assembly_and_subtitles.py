"""Blender assembly and subtitle tests (.blend is the only source of truth).

Verifies:
  1. assemble_clips: source footage concatenated as EDITABLE movie strips,
     back-to-back with optional source trimming; idempotent rebuild.
  2. add_subtitle_track: subtitle segments become EDITABLE text strips on V3;
     idempotent rebuild; SRT parsing works.
  3. After a render, the .blend still holds the full assembled timeline
     (persistence verification) — subtitles/assembly are NOT burned anywhere.

Run through: python tests/run.py blender-full
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from blender_vse.blender import blender_execute

MEDIA = ROOT / "tests" / "fixtures" / "media"
PROJECT = ROOT / "projects" / "assembly_subtitles_test.blend"
OUT = ROOT / "projects" / "assembly_subtitles_final.mp4"
SRT = ROOT / "projects" / "assembly_subtitles.srt"

RESULTS = []


def check(name, result, expect_ok=True):
    ok = result.get("ok") is expect_ok
    RESULTS.append({"name": name, "ok": ok, "result": result})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if not ok:
        print("   ", json.dumps(result, ensure_ascii=False)[:500])
    return ok


def read_timeline():
    r = blender_execute("list_strips", {"project": str(PROJECT), "with_text": True})
    return r.get("data", {}).get("strips", []) if r.get("ok") else []


def main():
    global PROJECT
    print("=== Assembly and subtitles: Blender assembly + subtitles (.blend = source of truth) ===")

    if PROJECT.exists():
        PROJECT.unlink()

    # ---- live-mode preamble: operate on the GUI's open .blend ----
    from blender_vse.blender.live_session import execute_code as _live_exec
    _fp = None
    _rr = _live_exec("import bpy; print('FP:' + repr(bpy.data.filepath))")
    for _l in (_rr.get("output") or "").splitlines():
        if _l.startswith("FP:"):
            _fp = _l[3:].strip().strip("'\"").strip('"') or None
    if _fp:
        PROJECT = Path(_fp)
    blender_execute("clear_vse", {"project": str(PROJECT)})
    if OUT.exists():
        OUT.unlink()

    # ---- 1. create project ----
    check("create_project", blender_execute("create_project", {
        "project": str(PROJECT), "resolution": [1280, 720], "fps": 30}))

    # ---- 2. assemble clips (sequential, no trim) ----
    r = blender_execute("assemble_clips", {
        "project": str(PROJECT),
        "clips": [
            {"asset": str(MEDIA / "clip_a.mp4"), "strip_name": "shot_01"},
            {"asset": str(MEDIA / "clip_b.mp4"), "strip_name": "shot_02"},
            {"asset": str(MEDIA / "clip_a.mp4"), "strip_name": "shot_03"},
        ],
        "channel": 1, "fps": 30})
    check("assemble_clips (3 clips)", r)
    if r.get("ok"):
        d = r["data"]
        check("assembled=3", {"ok": d.get("assembled") == 3})
        check("sequential: shot_02 starts where shot_01 ends",
              {"ok": d["clips"][1]["frame_start"] == d["clips"][0]["frame_end"]})
        check("total duration > 0", {"ok": d.get("total_duration_frames", 0) > 0})

    strips = read_timeline()
    movies = [s for s in strips if s["type"] == "MOVIE"]
    check("3 movie strips in timeline", {"ok": len(movies) == 3})
    order = [s["id"] for s in sorted(movies, key=lambda x: x["frame_start"])]
    check("strip order preserved", {"ok": order == ["shot_01", "shot_02", "shot_03"]})

    # ---- 3. assemble idempotent rebuild (same call, default prefix) ----
    r2 = blender_execute("assemble_clips", {
        "project": str(PROJECT),
        "clips": [
            {"asset": str(MEDIA / "clip_a.mp4")},
            {"asset": str(MEDIA / "clip_b.mp4")},
        ],
        "channel": 1, "fps": 30, "strip_prefix": "Clip_"})
    check("assemble_clips idempotent rebuild (2 clips)", r2)
    if r2.get("ok"):
        check("rebuild created exactly 2 new clips", {"ok": r2["data"].get("assembled") == 2})
    # Note: strips created with custom names (shot_*) in step 2 are intentionally
    # not removed by prefix cleanup — that's by design (only the prefix-owned
    # track is rebuilt). Verify the timeline still holds what we expect.
    strips = read_timeline()
    clip_prefixed = [s for s in strips if s["id"].startswith("Clip_")]
    check("Clip_* rebuild replaced old Clip_* strips (2 remain)",
          {"ok": len(clip_prefixed) == 2})

    # ---- 4. assemble with source trim (default prefix) ----
    r3 = blender_execute("assemble_clips", {
        "project": str(PROJECT),
        "clips": [
            {"asset": str(MEDIA / "clip_a.mp4"), "source_in": 1.0, "source_out": 3.0},
        ],
        "channel": 1, "fps": 30, "strip_prefix": "Trim_"})
    check("assemble_clips with source trim", r3)
    if r3.get("ok"):
        check("trim created 1 clip", {"ok": r3["data"].get("assembled") == 1})
        tinfo = r3["data"]["clips"][0]
        check("trimmed source_in=30 (1s)",
              {"ok": tinfo.get("source_in") == 30 and tinfo.get("source_out", 0) > 0})

    # ---- 5. subtitle track from segments ----
    r4 = blender_execute("add_subtitle_track", {
        "project": str(PROJECT),
        "segments": [
            {"start_seconds": 0.0, "end_seconds": 2.0, "text": "第一句字幕"},
            {"start_seconds": 2.5, "end_seconds": 4.5, "text": "第二句字幕"},
            {"start_seconds": 5.0, "end_seconds": 7.0, "text": "Third line"},
        ],
        "channel": 3, "fps": 30, "font_size": 48, "position": [0.5, 0.12],
        "strip_prefix": "Sub_"})
    check("add_subtitle_track (3 segments)", r4)
    if r4.get("ok"):
        check("created=3", {"ok": r4["data"].get("created") == 3})
    strips = read_timeline()
    subs = [s for s in strips if s["type"] == "TEXT"]
    check("3 text strips on V3", {"ok": len(subs) == 3
                                  and all(s["channel"] == 3 for s in subs)})
    texts = [s.get("text") for s in subs]
    check("subtitle text preserved", {"ok": "第一句字幕" in texts and "Third line" in texts})

    # ---- 6. subtitle idempotent rebuild ----
    r5 = blender_execute("add_subtitle_track", {
        "project": str(PROJECT),
        "segments": [
            {"start_seconds": 0.0, "end_seconds": 1.0, "text": "Only one"},
        ],
        "channel": 3, "fps": 30, "strip_prefix": "Sub_"})
    check("add_subtitle_track idempotent rebuild", r5)
    strips = read_timeline()
    subs = [s for s in strips if s["type"] == "TEXT"]
    check("rebuild left exactly 1 text strip", {"ok": len(subs) == 1})

    # ---- 7. subtitle track from SRT file ----
    SRT.write_text(
        "1\n00:00:00,000 --> 00:00:02,000\nSRT line one\n\n"
        "2\n00:00:03,000 --> 00:00:05,000\nSRT line two\n",
        encoding="utf-8")
    r6 = blender_execute("add_subtitle_track", {
        "project": str(PROJECT), "srt_path": str(SRT),
        "channel": 3, "fps": 30, "strip_prefix": "Sub_"})
    check("add_subtitle_track from SRT", r6)
    if r6.get("ok"):
        check("srt parsed 2 lines", {"ok": r6["data"].get("created") == 2})
    strips = read_timeline()
    subs = [s for s in strips if s["type"] == "TEXT"]
    check("2 text strips from SRT", {"ok": len(subs) == 2})

    # ---- 8. rebuild full timeline + render + persistence ----
    check("clear timeline", blender_execute("clear_vse", {"project": str(PROJECT)}))
    check("assemble final (2 clips)", blender_execute("assemble_clips", {
        "project": str(PROJECT),
        "clips": [
            {"asset": str(MEDIA / "clip_a.mp4")},
            {"asset": str(MEDIA / "clip_b.mp4")},
        ], "channel": 1, "fps": 30, "strip_prefix": "Clip_"}))
    check("add subtitle track (2)", blender_execute("add_subtitle_track", {
        "project": str(PROJECT),
        "segments": [
            {"start_seconds": 0.0, "end_seconds": 2.0, "text": "字幕一"},
            {"start_seconds": 2.5, "end_seconds": 4.5, "text": "字幕二"},
        ],
        "channel": 3, "fps": 30, "strip_prefix": "Sub_"}))
    check("add music (A1)", blender_execute("add_sound", {
        "project": str(PROJECT), "asset": str(MEDIA / "music.mp3"),
        "channel": 10, "frame_start": 1}))
    r7 = blender_execute("render_final", {
        "project": str(PROJECT), "output_path": str(OUT),
        "resolution": [640, 360], "frame_start": 1, "frame_end": 60,
        "quality": "draft"})
    check("render_final", r7)
    check("final.mp4 exists", {"ok": OUT.exists() and OUT.stat().st_size > 0})

    vp = blender_execute("verify_persistence", {
        "project": str(PROJECT), "expected": {"movie": 2, "sound": 1, "text": 2}})
    check("verify_persistence after render", vp)
    if vp.get("ok"):
        check("persistence_verified=true", {"ok": vp["data"].get("persistence_verified") is True})

    SRT.unlink(missing_ok=True)
    passed = sum(1 for r in RESULTS if r["ok"])
    print(f"\n=== Assembly and subtitles: {passed}/{len(RESULTS)} passed ===")
    if passed < len(RESULTS):
        sys.exit(1)


if __name__ == "__main__":
    main()
