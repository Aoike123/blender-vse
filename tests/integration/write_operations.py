"""Write-operation integration tests:
move strip / trim strip / change channel / change text / change font size.
Each op: execute -> re-read timeline -> verify result.

Run through: python tests/run.py blender-full
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from blender_vse.blender import blender_execute

MEDIA = ROOT / "tests" / "fixtures" / "media"
PROJECT = ROOT / "projects" / "write_operations_test.blend"

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


def find(strips, name):
    return next((s for s in strips if s["id"] == name), None)


def main():
    global PROJECT
    print("=== Write operations: write operations (each verified by re-read) ===")

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

    # setup: A(1-151) B(151-271) on V1, music on A1, text on V3
    for op, params in [
        ("create_project", {"resolution": [1280, 720], "fps": 30}),
        ("add_movie", {"asset": str(MEDIA / "clip_a.mp4"), "channel": 1, "frame_start": 1}),
        ("add_movie", {"asset": str(MEDIA / "clip_b.mp4"), "channel": 1, "frame_start": 151}),
        ("add_sound", {"asset": str(MEDIA / "music.mp3"), "channel": 10, "frame_start": 1}),
        ("add_text", {"text": "Original", "channel": 3, "frame_start": 1, "length": 90, "font_size": 48}),
    ]:
        r = blender_execute(op, {"project": str(PROJECT), **params})
        check(f"setup {op}", r)

    # ---- move strip (frame) ----
    r = blender_execute("move", {"project": str(PROJECT), "target": "clip_a",
                                 "frame_start": 300, "channel": 2})
    check("move clip_a -> frame 300 ch2", r)
    strips = read_timeline()
    a = find(strips, "clip_a")
    check("verify move: clip_a at 300-450 ch2",
          {"ok": a and a["frame_start"] == 300 and a["channel"] == 2})

    # ---- move with overlap -> must FAIL safely ----
    # clip_a is at ch2 frames 300-450; try moving clip_b to ch2 frame 320 -> overlap
    r = blender_execute("move", {"project": str(PROJECT), "target": "clip_b",
                                 "frame_start": 320, "channel": 2})
    check("move clip_b into overlap -> rejected", r, expect_ok=False)
    strips = read_timeline()
    b = find(strips, "clip_b")
    check("verify clip_b unchanged after rejected move",
          {"ok": b and b["frame_start"] == 151})

    # ---- trim (source seconds) ----
    r = blender_execute("trim_strip", {"project": str(PROJECT), "target": "clip_b",
                                       "source_in": 0.5, "source_out": 2.5, "fps": 30})
    check("trim clip_b source 0.5-2.5s", r)
    strips = read_timeline()
    b = find(strips, "clip_b")
    check("verify trim: source_in=15, source_out=45 (content 120)",
          {"ok": b and b["source_in"] == 15 and b["source_out"] == 45})

    # ---- change channel ----
    r = blender_execute("change_channel", {"project": str(PROJECT), "target": "music", "channel": 11})
    check("change_channel music -> 11", r)
    strips = read_timeline()
    m = find(strips, "music")
    check("verify music on ch11", {"ok": m and m["channel"] == 11})

    # ---- change text ----
    r = blender_execute("set_text", {"project": str(PROJECT), "target": "Text_1", "text": "Changed"})
    check("set_text -> Changed", r)
    strips = read_timeline()
    t = find(strips, "Text_1")
    check("verify text changed", {"ok": t and t.get("text") == "Changed"})

    # ---- change font size ----
    r = blender_execute("set_font_size", {"project": str(PROJECT), "target": "Text_1", "font_size": 72})
    check("set_font_size -> 72", r)
    strips = read_timeline()
    t = find(strips, "Text_1")
    check("verify font_size 72", {"ok": t and abs((t.get("font_size") or 0) - 72) < 0.01})

    # ---- mute + volume ----
    check("set_volume music 0.5", blender_execute("set_volume", {
        "project": str(PROJECT), "target": "music", "volume": 0.5}))
    check("mute clip_b", blender_execute("mute", {
        "project": str(PROJECT), "target": "clip_b", "mute": True}))
    strips = read_timeline()
    m = find(strips, "music")
    b = find(strips, "clip_b")
    check("verify volume 0.5", {"ok": m and abs((m.get("volume") or 0) - 0.5) < 0.01})
    check("verify clip_b muted", {"ok": b and b.get("mute") is True})

    # ---- dry-run safety ----
    before = read_timeline()
    r = blender_execute("move", {"project": str(PROJECT), "target": "clip_a",
                                 "frame_start": 500, "channel": 5, "dry_run": True})
    check("dry-run move returns ok + dry_run flag", {"ok": r.get("ok") and r.get("dry_run")})
    after = read_timeline()
    a2 = find(after, "clip_a")
    check("dry-run did NOT persist (clip_a still 300)",
          {"ok": a2 and a2["frame_start"] == 300})

    passed = sum(1 for r in RESULTS if r["ok"])
    print(f"\n=== Write operations: {passed}/{len(RESULTS)} passed ===")
    if passed < len(RESULTS):
        sys.exit(1)


if __name__ == "__main__":
    main()
