"""Font and text styling verification tests.

User's manual work is mostly font/size/position/style, so these MUST be verified:
font loading, font assignment, font size, text position, alignment, outline,
shadow, opacity, box.

Run through: python tests/run.py blender-full
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from blender_vse.blender import blender_execute

PROJECT = ROOT / "projects" / "text_fonts_test.blend"
FONT_SIMHEI = r"C:\Windows\Fonts\simhei.ttf"
FONT_ARIAL = r"C:\Windows\Fonts\arial.ttf"

RESULTS = []


def check(name, result, expect_ok=True):
    ok = result.get("ok") is expect_ok
    RESULTS.append({"name": name, "ok": ok, "result": result})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if not ok:
        print("   ", json.dumps(result, ensure_ascii=False)[:600])
    return ok


def read_timeline():
    r = blender_execute("list_strips", {"project": str(PROJECT), "with_text": True})
    return r.get("data", {}).get("strips", []) if r.get("ok") else []


def find(strips, name):
    return next((s for s in strips if s["id"] == name), None)


def main():
    global PROJECT
    print("=== Text and fonts: font & text styling verification ===")

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

    check("create project", blender_execute("create_project", {
        "project": str(PROJECT), "resolution": [1920, 1080], "fps": 30}))
    check("add text", blender_execute("add_text", {
        "project": str(PROJECT), "text": "Style Test", "channel": 3,
        "frame_start": 1, "length": 120, "font_size": 48, "position": [0.5, 0.5]}))

    # font loading + assignment
    check("set_font simhei", blender_execute("set_font", {
        "project": str(PROJECT), "target": "Text_1", "font": FONT_SIMHEI}))
    check("set_font arial", blender_execute("set_font", {
        "project": str(PROJECT), "target": "Text_1", "font": FONT_ARIAL}))
    check("set_font invalid path -> error", blender_execute("set_font", {
        "project": str(PROJECT), "target": "Text_1", "font": "Z:\\nonexistent.ttf"}),
        expect_ok=False)

    # font size
    check("set_font_size 80", blender_execute("set_font_size", {
        "project": str(PROJECT), "target": "Text_1", "font_size": 80}))
    check("set_font_size 24", blender_execute("set_font_size", {
        "project": str(PROJECT), "target": "Text_1", "font_size": 24}))

    # position
    check("set_text_position top", blender_execute("set_text_position", {
        "project": str(PROJECT), "target": "Text_1", "position": [0.5, 0.85]}))
    check("set_text_position bottom", blender_execute("set_text_position", {
        "project": str(PROJECT), "target": "Text_1", "position": [0.15, 0.1]}))

    # alignment
    check("set_alignment LEFT", blender_execute("set_alignment", {
        "project": str(PROJECT), "target": "Text_1", "alignment": "LEFT"}))
    check("set_alignment RIGHT", blender_execute("set_alignment", {
        "project": str(PROJECT), "target": "Text_1", "alignment": "RIGHT"}))
    check("set_alignment invalid -> error", blender_execute("set_alignment", {
        "project": str(PROJECT), "target": "Text_1", "alignment": "MIDDLE"}),
        expect_ok=False)

    # outline / shadow / box
    check("set_outline on", blender_execute("set_outline", {
        "project": str(PROJECT), "target": "Text_1", "outline": True}))
    check("set_shadow on", blender_execute("set_shadow", {
        "project": str(PROJECT), "target": "Text_1", "shadow": True}))
    check("set_box on", blender_execute("set_box", {
        "project": str(PROJECT), "target": "Text_1", "box": True}))
    check("set_outline off", blender_execute("set_outline", {
        "project": str(PROJECT), "target": "Text_1", "outline": False}))

    # opacity
    check("set_opacity 0.6", blender_execute("set_opacity", {
        "project": str(PROJECT), "target": "Text_1", "opacity": 0.6}))
    check("set_opacity 1.0", blender_execute("set_opacity", {
        "project": str(PROJECT), "target": "Text_1", "opacity": 1.0}))

    # final state verification via timeline
    strips = read_timeline()
    t = find(strips, "Text_1")
    check("text strip present", {"ok": t is not None})
    if t:
        check("final text content", {"ok": t.get("text") == "Style Test"})
        check("final font_size 24", {"ok": abs((t.get("font_size") or 0) - 24) < 0.01})
        pos = t.get("position") or []
        check("final position ~[0.15, 0.1]",
              {"ok": len(pos) == 2 and abs(pos[0] - 0.15) < 0.01 and abs(pos[1] - 0.1) < 0.01})

    passed = sum(1 for r in RESULTS if r["ok"])
    print(f"\n=== Text and fonts: {passed}/{len(RESULTS)} passed ===")
    if passed < len(RESULTS):
        sys.exit(1)


if __name__ == "__main__":
    main()
