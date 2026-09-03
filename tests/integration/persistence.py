"""Persistence tests — the .blend is the SOURCE OF TRUTH, the MP4 is
derivative output.

Requirement (user): after every timeline modification AND after rendering, the
project .blend must be explicitly saved, and a persistence verification must
reopen the file in a fresh Blender instance and confirm the VSE timeline (movie/
sound/text strips) survived. Only persistence_verified=true completes a task.

Run through: python tests/run.py blender-full
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from blender_vse.blender import blender_execute

MEDIA = ROOT / "tests" / "fixtures" / "media"
PROJECT = ROOT / "projects" / "persistence_test.blend"
OUT = ROOT / "projects" / "persistence_final.mp4"

RESULTS = []


def check(name, result, expect_ok=True):
    ok = result.get("ok") is expect_ok
    RESULTS.append({"name": name, "ok": ok, "result": result})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if not ok:
        print("   ", json.dumps(result, ensure_ascii=False)[:500])
    return ok


def main():
    global PROJECT
    print("=== Persistence: persistence (source of truth = .blend) ===")

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

    # ---- 1. build timeline ----
    check("create_project (named edit scene)", blender_execute("create_project", {
        "project": str(PROJECT), "resolution": [1280, 720], "fps": 30}))
    check("add_movie A", blender_execute("add_movie", {
        "project": str(PROJECT), "asset": str(MEDIA / "clip_a.mp4"),
        "channel": 1, "frame_start": 1}))
    check("add_movie B", blender_execute("add_movie", {
        "project": str(PROJECT), "asset": str(MEDIA / "clip_b.mp4"),
        "channel": 1, "frame_start": 151}))
    check("add_sound", blender_execute("add_sound", {
        "project": str(PROJECT), "asset": str(MEDIA / "music.mp3"),
        "channel": 10, "frame_start": 1}))
    check("add_text", blender_execute("add_text", {
        "project": str(PROJECT), "text": "Persisted subtitle", "channel": 3,
        "frame_start": 1, "length": 90, "font_size": 48}))

    # ---- 2. explicit save_project ----
    check("save_project", blender_execute("save_project", {"project": str(PROJECT)}))

    # ---- 3. persistence verification (fresh reopen) ----
    vp = blender_execute("verify_persistence", {
        "project": str(PROJECT), "expected": {"movie": 2, "sound": 1, "text": 1}})
    check("verify_persistence after build", vp)
    if vp.get("ok"):
        d = vp["data"]
        check("persistence_verified=true", {"ok": d.get("persistence_verified") is True})
        check("edit scene owns VSE", {"ok": d.get("scene") == "VideoEditing"})
        check("vse_strip_count=4", {"ok": d.get("vse_strip_count") == 4})
        check("movie=2 sound=1 text=1", {"ok": d.get("movie_strips") == 2
                                          and d.get("sound_strips") == 1
                                          and d.get("text_strips") == 1})

    # ---- 4. render final.mp4 THEN save .blend again ----
    r = blender_execute("render_final", {
        "project": str(PROJECT), "output_path": str(OUT),
        "resolution": [640, 360], "frame_start": 1, "frame_end": 30,
        "quality": "draft"})
    check("render_final", r)
    check("final.mp4 exists", {"ok": OUT.exists() and OUT.stat().st_size > 0})

    # render params must NOT dirty the project (source of truth stays 1280x720)
    info = blender_execute("get_timeline_info", {"project": str(PROJECT)})
    res = (info.get("data") or {}).get("resolution") if info.get("ok") else None
    check("render did not dirty project resolution (1280x720)", {"ok": res == [1280, 720]})

    # ---- 5. persistence verification AFTER render (blend saved again) ----
    vp2 = blender_execute("verify_persistence", {
        "project": str(PROJECT), "expected": {"movie": 2, "sound": 1, "text": 1}})
    check("verify_persistence after render", vp2)
    if vp2.get("ok"):
        check("persistence still verified after render",
              {"ok": vp2["data"].get("persistence_verified") is True})
        check("strips identical after render (4)",
              {"ok": vp2["data"].get("vse_strip_count") == 4})

    # ---- 6. text content survived reopen ----
    tl = blender_execute("list_strips", {"project": str(PROJECT), "with_text": True})
    texts = [s.get("text") for s in (tl.get("data") or {}).get("strips", []) if s.get("type") == "TEXT"]
    check("text strip content survived", {"ok": "Persisted subtitle" in texts})

    passed = sum(1 for r in RESULTS if r["ok"])
    print(f"\n=== Persistence: {passed}/{len(RESULTS)} passed ===")
    if passed < len(RESULTS):
        sys.exit(1)


if __name__ == "__main__":
    main()
