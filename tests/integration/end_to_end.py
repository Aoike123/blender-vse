"""End-to-end acceptance demo — mimics real user requests from requirement 二十:

"读取这个 Blender 项目的时间线"
"把第三个镜头放到第二个镜头前面"
"所有字幕字号改成 60"
"把标题向上移动一点"
"生成一个低码率 preview"

Builds a 3-shot timeline, reorders shots, restyles text, renders preview.

NOTE: functional demo — interactive ops run against a LIVE GUI bridge
(production path). Requires the Blender MCP Bridge addon running; skipped with
a hint if no bridge is reachable (never downgraded to headless).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from blender_vse import router_execute
from blender_vse.blender import blender_execute

MEDIA = ROOT / "tests" / "fixtures" / "media"
PROJECT = ROOT / "projects" / "e2e_demo.blend"
OUT = ROOT / "projects" / "e2e_preview.mp4"

steps = []


def step(label, fn):
    r = fn()
    ok = r.get("ok")
    steps.append((label, ok))
    print(f"[{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        print("   ", json.dumps(r, ensure_ascii=False)[:400])
    return r


def main():
    global PROJECT
    print("=== End-to-end acceptance demo ===")

    # live-mode preamble: need a live bridge; operate on the GUI's open .blend
    from blender_vse.blender import live_session_available
    from blender_vse.blender.live_session import execute_code as _live_exec
    if not live_session_available():
        print("\n[SKIP] no live Blender GUI bridge — interactive demo requires a "
              "live session (see tools/bridge-status.py). Not downgrading to headless.")
        sys.exit(0)
    _fp = None
    _rr = _live_exec("import bpy; print('FP:' + repr(bpy.data.filepath))")
    for _l in (_rr.get("output") or "").splitlines():
        if _l.startswith("FP:"):
            _fp = _l[3:].strip().strip("'\"").strip('"') or None
    if _fp:
        PROJECT = Path(_fp)
    blender_execute("clear_vse", {"project": str(PROJECT)})

    # ---- build: 3 shots + music + 2 captions (V3) ----
    step("create project", lambda: blender_execute("create_project", {
        "project": str(PROJECT), "resolution": [1280, 720], "fps": 30}))

    # main video = clip_a (5s) + clip_b (4s) + clip_a again = "three shots"
    step("add shot 1 (clip_a)", lambda: blender_execute("add_movie", {
        "project": str(PROJECT), "asset": str(MEDIA / "clip_a.mp4"),
        "channel": 1, "frame_start": 1}))
    step("add shot 2 (clip_b)", lambda: blender_execute("add_movie", {
        "project": str(PROJECT), "asset": str(MEDIA / "clip_b.mp4"),
        "channel": 1, "frame_start": 151}))
    step("add shot 3 (clip_a2)", lambda: blender_execute("add_movie", {
        "project": str(PROJECT), "asset": str(MEDIA / "clip_a.mp4"),
        "channel": 1, "frame_start": 271, "strip_name": "shot_3"}))
    step("add music", lambda: blender_execute("add_sound", {
        "project": str(PROJECT), "asset": str(MEDIA / "music.mp3"),
        "channel": 10, "frame_start": 1}))
    step("add subtitle 1", lambda: blender_execute("add_text", {
        "project": str(PROJECT), "text": "第一段字幕", "channel": 3,
        "frame_start": 1, "length": 90, "font_size": 48, "position": [0.5, 0.12],
        "strip_name": "sub_01"}))
    step("add subtitle 2", lambda: blender_execute("add_text", {
        "project": str(PROJECT), "text": "第二段字幕", "channel": 3,
        "frame_start": 151, "length": 90, "font_size": 48, "position": [0.5, 0.12],
        "strip_name": "sub_02"}))

    # ---- user request 1: read timeline ----
    tl = blender_execute("list_strips", {"project": str(PROJECT), "with_text": True})
    step("read timeline", lambda: tl)
    strips = tl.get("data", {}).get("strips", [])
    shots = [s for s in strips if s["type"] == "MOVIE"]
    step("timeline has 3 movie shots", lambda: {"ok": len(shots) == 3})

    # ---- user request 2: put shot 3 before shot 2 (swap) ----
    # shot_3 at 271-421, shot_2 (clip_b) at 151-271: swap them
    r1 = blender_execute("move", {"project": str(PROJECT), "target": "shot_3",
                                  "frame_start": 151, "channel": 1, "swap": True})
    step("swap shot_3 <-> shot_2 (shot_3 to 151)", lambda: r1)

    tl2 = blender_execute("list_strips", {"project": str(PROJECT)})
    shots2 = [s for s in (tl2.get("data", {}).get("strips", [])) if s["type"] == "MOVIE"]
    order = [(s["id"], s["frame_start"]) for s in sorted(shots2, key=lambda x: x["frame_start"])]
    print("   shot order now:", order)
    # expected: clip_a(1), shot_3(151), clip_b(271) — shot_3 now BEFORE shot_2 (clip_b)
    step("verify new order: shot_3 before shot_2",
         lambda: {"ok": order[0][0] == "clip_a" and order[1][0] == "shot_3" and order[2][0] == "clip_b"})

    # ---- user request 3: all subtitle font size -> 60 ----
    ok = True
    for sub in ["sub_01", "sub_02"]:
        r = blender_execute("set_font_size", {"project": str(PROJECT), "target": sub, "font_size": 60})
        ok = ok and r.get("ok")
    step("set all subtitle font_size to 60", lambda: {"ok": ok})
    tl3 = blender_execute("list_strips", {"project": str(PROJECT), "with_text": True})
    subs = [s for s in (tl3.get("data", {}).get("strips", [])) if s["type"] == "TEXT"]
    step("verify all subtitles at 60",
         lambda: {"ok": all(abs((s.get("font_size") or 0) - 60) < 0.01 for s in subs)})

    # ---- user request 4: move title up ----
    r = blender_execute("set_text_position", {"project": str(PROJECT),
                                              "target": "sub_01", "position": [0.5, 0.35]})
    step("move title up (sub_01 -> y=0.35)", lambda: r)

    # ---- user request 5: low-bitrate preview ----
    r = blender_execute("render_preview", {
        "project": str(PROJECT), "output_path": str(OUT),
        "resolution": [320, 180], "frame_start": 1, "frame_end": 30,
        "quality": "draft"})
    step("render low-bitrate preview", lambda: r)
    step("preview file exists", lambda: {"ok": OUT.exists() and OUT.stat().st_size > 0})

    # render must NOT persist its settings into the project
    info = blender_execute("get_timeline_info", {"project": str(PROJECT)})
    res = (info.get("data") or {}).get("resolution") if info.get("ok") else None
    step("render did not dirty project resolution (still 1280x720)",
         lambda: {"ok": res == [1280, 720]})

    # summary
    passed = sum(1 for _, ok in steps if ok)
    print(f"\n=== E2E: {passed}/{len(steps)} passed ===")
    print(f"project: {PROJECT}")
    print(f"preview: {OUT} ({OUT.stat().st_size if OUT.exists() else 0} bytes)")
    if passed < len(steps):
        sys.exit(1)


if __name__ == "__main__":
    main()
