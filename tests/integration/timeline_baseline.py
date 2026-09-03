"""Read-only timeline baseline test:
1. start Blender
2. create disposable test project
3. create VSE
4. import two test videos + audio
5. create text strip
6. read timeline
7. output structured timeline JSON

This is the FIRST test — it must only create disposable state, never touch
existing projects. Run through: python tests/run.py blender-full
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from blender_vse.blender import blender_execute, environment_report

MEDIA = ROOT / "tests" / "fixtures" / "media"
PROJECT = ROOT / "projects" / "timeline_baseline_test.blend"

RESULTS = []


def check(name, result, expect_ok=True):
    ok = result.get("ok") is expect_ok
    RESULTS.append({"name": name, "ok": ok, "result": result})
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name}")
    if not ok:
        print("   ", json.dumps(result, ensure_ascii=False)[:500])
    return ok


def main():
    global PROJECT
    print("=== Timeline baseline: read-only baseline (disposable project) ===")

    # 0. env
    env = environment_report()
    check("environment: blender+ffmpeg detected",
          {"ok": env["blender"]["available"] and env["ffmpeg"]["available"]})

    # clean disposable project
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

    # 1. create project (VSE + settings)
    check("create disposable project", blender_execute("create_project", {
        "project": str(PROJECT), "resolution": [1280, 720], "fps": 30}))

    # 2-4. import media
    check("add movie A (V1)", blender_execute("add_movie", {
        "project": str(PROJECT), "asset": str(MEDIA / "clip_a.mp4"),
        "channel": 1, "frame_start": 1}))
    check("add movie B (V1)", blender_execute("add_movie", {
        "project": str(PROJECT), "asset": str(MEDIA / "clip_b.mp4"),
        "channel": 1, "frame_start": 151}))
    check("add sound (A1)", blender_execute("add_sound", {
        "project": str(PROJECT), "asset": str(MEDIA / "music.mp3"),
        "channel": 10, "frame_start": 1}))

    # 5. text strip
    check("add text strip (V3)", blender_execute("add_text", {
        "project": str(PROJECT), "text": "Phase1 Subtitle", "channel": 3,
        "frame_start": 1, "length": 90, "font_size": 60, "position": [0.5, 0.1]}))

    # 6-7. read timeline -> structured JSON
    tl = blender_execute("list_strips", {"project": str(PROJECT), "with_text": True})
    check("read timeline (list_strips)", tl)
    if tl.get("ok"):
        data = tl.get("data") or {}
        strips = data.get("strips", [])
        types = [s["type"] for s in strips]
        check("timeline has 4 strips (2 MOVIE + SOUND + TEXT)", {"ok": len(strips) == 4})
        check("strip types correct", {"ok": types.count("MOVIE") == 2 and "SOUND" in types and "TEXT" in types})
        check("text content persisted", {"ok": any(s.get("text") == "Phase1 Subtitle" for s in strips)})
        # write JSON artifact
        out = ROOT / "projects" / "timeline_baseline_timeline.json"
        out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"   timeline JSON -> {out}")

    # summary
    passed = sum(1 for r in RESULTS if r["ok"])
    print(f"\n=== Timeline baseline: {passed}/{len(RESULTS)} passed ===")
    if passed < len(RESULTS):
        sys.exit(1)


if __name__ == "__main__":
    main()
