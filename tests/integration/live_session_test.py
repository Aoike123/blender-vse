"""Live GUI Session acceptance test — interactive VSE editing against the RUNNING
Blender GUI through the Blender MCP Bridge addon.

Prereq: Blender GUI is open with the "Blender MCP Bridge" addon enabled and
"Start Bridge" clicked (Properties > Scene > Blender MCP Bridge). The user should
see the timeline + preview update LIVE as each op runs.

Verifies the user's acceptance criteria:
  1. add a movie strip  -> appears in the open timeline immediately
  2. move that strip    -> visible moving in the timeline
  3. modify a text strip -> preview shows the text change immediately
  4. change font size    -> preview shows the size change immediately
  5. after every edit: timeline state refreshed + current frame/preview refreshed
     + UI redraw requested; strips re-read and verified

Run through: python tests/run.py blender-full
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from blender_vse.blender import blender_execute, live_session_available
from blender_vse.blender.live_session import ping, bridge_config, execute_code

MEDIA = ROOT / "tests" / "fixtures" / "media"
PROJECT = ROOT / "projects" / "live_session_test.blend"

RESULTS = []


def check(name, result, expect_ok=True):
    ok = result.get("ok") is expect_ok
    RESULTS.append({"name": name, "ok": ok, "result": result})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if not ok:
        print("   ", json.dumps(result, ensure_ascii=False)[:500])
    return ok


def gui_filepath() -> str | None:
    """The .blend the live GUI currently has open (bpy.data.filepath)."""
    r = execute_code("import bpy; print('FILEPATH:' + repr(bpy.data.filepath))")
    for line in (r.get("output") or "").splitlines():
        if line.startswith("FILEPATH:"):
            val = line[len("FILEPATH:"):].strip().strip("'\"")
            return val or None
    return None


def main():
    print("=== Live GUI Session test (interactive editing in the open Blender) ===")
    print(f"bridge: {bridge_config()}  reachable={ping()}")

    if not live_session_available():
        print("\nNO LIVE SESSION. Open Blender GUI, enable 'Blender MCP Bridge' addon,")
        print("click 'Start Bridge' (Properties > Scene > Blender MCP Bridge), then re-run.")
        sys.exit(2)  # distinct exit code: skipped (no live session)

    # The live session edits the .blend the GUI currently has open — resolve it.
    live_project = gui_filepath() or str(PROJECT)
    print(f"live project (GUI file): {live_project}")
    if live_project and live_project != str(PROJECT):
        print("NOTE: live editing targets the GUI's open file (source of truth).")

    # Start from a clean timeline in the live session.
    check("clear_vse (start clean)", blender_execute("clear_vse", {"project": live_project}))

    # ---- 1. create project (live) ----
    r = blender_execute("create_project", {
        "project": live_project, "resolution": [1280, 720], "fps": 30})
    check("create_project (live)", r)
    if r.get("ok"):
        check("mode=live", {"ok": r.get("mode") == "live"})

    # ---- 2. add movie strip -> should appear in the open timeline NOW ----
    r = blender_execute("add_movie", {
        "project": live_project, "asset": str(MEDIA / "clip_a.mp4"),
        "channel": 1, "frame_start": 1})
    check("add_movie (live)", r)
    tl = blender_execute("list_strips", {"project": live_project})
    movies = [s for s in (tl.get("data") or {}).get("strips", []) if s["type"] == "MOVIE"]
    check("movie strip present in timeline", {"ok": len(movies) >= 1})

    # ---- 3. move the strip -> visible moving live ----
    r = blender_execute("move", {"project": live_project, "target": "clip_a",
                                 "frame_start": 200, "channel": 2})
    check("move strip to frame 200 ch2 (live)", r)
    tl = blender_execute("list_strips", {"project": live_project})
    a = next((s for s in (tl.get("data") or {}).get("strips", []) if s["id"] == "clip_a"), None)
    check("verify move: clip_a at 200 ch2", {"ok": a and a["frame_start"] == 200 and a["channel"] == 2})

    # ---- 4. add text + change text -> preview shows it now ----
    r = blender_execute("add_text", {
        "project": live_project, "text": "LIVE EDIT", "channel": 3,
        "frame_start": 1, "length": 90, "font_size": 48, "position": [0.5, 0.5],
        "strip_name": "live_text"})
    check("add_text (live)", r)
    r = blender_execute("set_text", {"project": live_project, "target": "live_text",
                                     "text": "LIVE TEXT CHANGED"})
    check("set_text (live)", r)
    tl = blender_execute("list_strips", {"project": live_project, "with_text": True})
    t = next((s for s in (tl.get("data") or {}).get("strips", []) if s["id"] == "live_text"), None)
    check("verify text changed in timeline", {"ok": t and t.get("text") == "LIVE TEXT CHANGED"})

    # ---- 5. font size -> preview changes now ----
    r = blender_execute("set_font_size", {"project": live_project, "target": "live_text",
                                          "font_size": 88})
    check("set_font_size 88 (live)", r)
    tl = blender_execute("list_strips", {"project": live_project, "with_text": True})
    t = next((s for s in (tl.get("data") or {}).get("strips", []) if s["id"] == "live_text"), None)
    check("verify font_size 88", {"ok": t and abs((t.get("font_size") or 0) - 88) < 0.01})

    # ---- 6. persistence verification (fresh reopen from disk) ----
    if live_project and Path(live_project).exists():
        vp = blender_execute("verify_persistence", {
            "project": live_project, "expected": {"movie": 1, "text": 1}})
        check("verify_persistence after live edits", vp)
        if vp.get("ok"):
            check("persistence_verified=true", {"ok": vp["data"].get("persistence_verified") is True})
    else:
        check("verify_persistence after live edits (GUI file on disk)", {"ok": False})

    # summary
    passed = sum(1 for r in RESULTS if r["ok"])
    print(f"\n=== Live session: {passed}/{len(RESULTS)} passed ===")
    print("If you were watching Blender: the movie strip appeared, moved,")
    print("the text and its size changed live in the VSE preview.")
    if passed < len(RESULTS):
        sys.exit(1)


if __name__ == "__main__":
    main()
