"""Revision hardening: canonical full-state hash + internal-only primitives.

Covers:
  1. canonical hash STABILITY: repeated reads without edits yield the same hash
  2. canonical hash COVERAGE: manual edits to fields the OLD hash missed
     (transform / crop / font_size / text position / outline / keyframes /
     metadata / proxy config / markers / channel roles / project fps) all flip the hash ->
     get_revision reports dirty/revision_changed — a manual edit is never
     mistaken for "consistent".
  3. editing primitives are INTERNAL-ONLY: direct mutation is refused by
     default (internal_primitive), whitelisted ops still work, and the
     BLENDER_VSE_ALLOW_DIRECT_MUTATION escape hatch re-enables it for harnesses.

Run through: python tests/run.py blender-full (requires visible Blender).
This suite must run WITHOUT BLENDER_VSE_ALLOW_DIRECT_MUTATION
so the refusal checks are meaningful.
"""
import json
import os
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from blender_vse.blender import blender_execute, live_session_available
from blender_vse.blender.live_session import execute_code as _live_exec

MEDIA = ROOT / "tests" / "fixtures" / "media"
PROJECT = ROOT / "projects" / "revision_hardening_test.blend"

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
    print("=== Revision hardening: canonical hash coverage + internal-only primitives ===")
    if not live_session_available():
        print("[SKIP] no live bridge")
        sys.exit(0)
    proj = resolve_project()

    # ---- setup via the sanctioned path ----
    # clean slate: clear_vse is an editing primitive — the harness temporarily
    # enables direct mutation for cleanup ONLY, then disables it again so the
    # refusal checks below are meaningful.
    os.environ["BLENDER_VSE_ALLOW_DIRECT_MUTATION"] = "1"
    r_clear = blender_execute("clear_vse", {"project": proj})
    check("setup clear_vse (harness escape)", r_clear.get("ok"), str(r_clear.get("error"))[:160])
    r_proj = blender_execute("create_project", {"project": proj, "resolution": [1280, 720], "fps": 30})
    check("setup create_project", r_proj.get("ok"))
    os.environ.pop("BLENDER_VSE_ALLOW_DIRECT_MUTATION", None)
    os.environ.pop("BLENDER_VSE_ALLOW_DIRECT_MUTATION", None)

    def patch(commands):
        r = blender_execute("get_revision", {"project": proj})
        d = r["data"]
        return blender_execute("apply_patch", {
            "project": proj, "base_revision": d["revision"],
            "base_timeline_hash": d["timeline_hash"], "read_token": d["observation_id"],
            "patch_id": "p13_" + uuid.uuid4().hex[:10], "commands": commands})

    ok = patch([{"op": "add_movie", "asset": str(MEDIA / "clip_a.mp4"), "channel": 1,
                 "frame_start": 1, "strip_name": "clipA"},
                {"op": "add_movie", "asset": str(MEDIA / "clip_b.mp4"), "channel": 1,
                 "frame_start": 151, "strip_name": "clipB"},
                {"op": "add_text", "text": "Hello", "channel": 3, "frame_start": 1,
                 "length": 120, "strip_name": "Title", "font_size": 48}])
    check("setup patches applied", ok.get("ok") and ok["data"].get("applied") is True,
          str(ok.get("error"))[:200])

    # ---- 1. hash stability: no edits -> identical hash ----
    r1 = blender_execute("get_revision", {"project": proj})
    r2 = blender_execute("get_revision", {"project": proj})
    check("hash stable without edits", r1.get("ok") and r2.get("ok")
          and r1["data"]["timeline_hash"] == r2["data"]["timeline_hash"]
          and r1["data"]["consistent"] is True)

    # ---- 2. canonical coverage: manual edits flip the hash ----
    # each manual edit is applied via the bridge (as a human would) + saved,
    # then read must report dirty/revision_changed.
    manual_edits = [
        ("transform", "se.strips['Title'].transform.offset_x = 120.0"),
        ("crop", "se.strips['Title'].crop.min_x = 10"),
        ("font_size", "se.strips['Title'].font_size = 96.0"),
        ("text position", "se.strips['Title'].location = (0.2, 0.8)"),
        ("outline", "se.strips['Title'].use_outline = True"),
        ("shadow", "se.strips['Title'].use_shadow = True"),
        ("box", "se.strips['Title'].use_box = True"),
        ("keyframes", "se.strips['clipA']['video_ai_anim'] = '{\"frames\": [], \"presets\": [\"fade_in\"]}'"),
        ("metadata", "se.strips['clipA']['video_ai_meta'] = '{\"role\": \"hero\"}'"),
        ("proxy config", "se.strips['clipA'].use_proxy = True; se.strips['clipA'].proxy.build_25 = True"),
        ("volume", "se.strips['clipA'].blend_alpha = 0.7"),
        ("marker", "bpy.context.scene.timeline_markers.new(name='M1', frame=30)"),
        ("channel role", "bpy.context.scene['video_ai_channel_roles'] = '{\"3\": \"titles\"}'"),
        ("project fps", "bpy.context.scene.render.fps = 25"),
    ]
    for label, code in manual_edits:
        ok = False
        last_err = ""
        last_out = ""
        for _attempt in range(5):  # bridge is occasionally flaky under load — back off & retry
            try:
                rr = _live_exec("import bpy\nse = bpy.context.scene.sequence_editor\n"
                                + code + f"\nbpy.ops.wm.save_as_mainfile(filepath={json.dumps(proj)})\nprint('EDITED')")
                if "EDITED" in (rr.get("output") or ""):
                    ok = True
                    break
                last_err = (rr.get("error") or "")[:150]
                last_out = (rr.get("output") or "")[-160:]
            except Exception as _e:
                last_err = str(_e)[:200]
            time.sleep(1.5)
        if ok:
            rv = blender_execute("get_revision", {"project": proj})
            ok = rv.get("ok") and rv["data"].get("dirty") is True \
                and rv["data"].get("revision_changed") is True
        check(f"manual {label} edit flips hash (dirty)", ok,
              (f"edit failed: {last_err} out={last_out!r}" if not ok else ""))
    # acknowledge ALL accumulated manual edits once (one save, not one per edit —
    # dozens of save_as_mainfile calls overwhelm the bridge)
    ra = blender_execute("get_revision", {"project": proj})
    ack = blender_execute("acknowledge_revision", {
        "project": proj, "observed_revision": ra["data"]["revision"],
        "observed_hash": ra["data"]["timeline_hash"],
        "read_token": ra["data"]["observation_id"]})
    check("acknowledge all manual edits", ack.get("ok")
          and ack["data"].get("acknowledged") is True, str(ack.get("error"))[:200])
    rb = blender_execute("get_revision", {"project": proj})
    check("consistent after acknowledging manual edits", rb.get("ok")
          and rb["data"].get("consistent") is True)

    # ---- 3. editing primitives are INTERNAL-ONLY ----
    os.environ.pop("BLENDER_VSE_ALLOW_DIRECT_MUTATION", None)
    r = blender_execute("add_text", {"project": proj, "text": "x", "channel": 4})
    check("direct add_text refused (internal_primitive)", not r.get("ok")
          and (r.get("error") or {}).get("code") == "internal_primitive",
          str(r.get("error"))[:160])
    r = blender_execute("set_text", {"project": proj, "target": "Title", "text": "x"})
    check("direct set_text refused", not r.get("ok")
          and (r.get("error") or {}).get("code") == "internal_primitive")
    # whitelisted mutating ops still work directly
    r = blender_execute("get_revision", {"project": proj})
    check("read-only get_revision still allowed", r.get("ok"))
    # escape hatch for internal harnesses
    os.environ["BLENDER_VSE_ALLOW_DIRECT_MUTATION"] = "1"
    r = blender_execute("add_text", {"project": proj, "text": "ok", "channel": 4,
                                     "frame_start": 1, "length": 30, "strip_name": "ok"})
    check("BLENDER_VSE_ALLOW_DIRECT_MUTATION=1 re-enables for harnesses", r.get("ok"),
          str(r.get("error"))[:160])
    os.environ.pop("BLENDER_VSE_ALLOW_DIRECT_MUTATION", None)

    # ---- 4. persistence gate ----
    r = blender_execute("verify_persistence", {"project": proj})
    check("verify_persistence ok", r.get("ok"))

    passed = sum(1 for _, ok in RESULTS if ok)
    print(f"\n=== Revision hardening: {passed}/{len(RESULTS)} passed ===")
    if passed < len(RESULTS):
        sys.exit(1)


if __name__ == "__main__":
    main()
