"""Application ↔ Blender incremental adapter.

No more full project rebuilds: the caller sends an Edit Patch
  {base_revision, base_timeline_hash, commands: [{op, target, ...}]}
and Blender runs: validate revision → checkpoint → atomic batch → verify →
save .blend → commit revision+1.

Also verifies the Step 3 COMPLETION STANDARD:
  - a human edits the timeline directly in Blender (drag clip 3 to the front,
    Ctrl+S) — simulated here with a bridge-side edit + save
  - the caller re-reads and understands "revision changed" (get_revision
    reports dirty/revision_changed)
  - the AI's next incremental patch does NOT overwrite the manual edit
    (stale_base refusal) and applies cleanly once the new base is acknowledged.

Run through: python tests/run.py blender-full (requires visible Blender)
"""
import json
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

# internal harness: setup uses direct adapter calls (test scaffolding)
os.environ["BLENDER_VSE_ALLOW_DIRECT_MUTATION"] = "1"

from blender_vse.blender import blender_execute, live_session_available
from blender_vse.blender.live_session import execute_code as _live_exec

MEDIA = ROOT / "tests" / "fixtures" / "media"
PROJECT = ROOT / "projects" / "incremental_test.blend"

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


def movie_order(proj) -> list[str]:
    tl = blender_execute("list_strips", {"project": proj})
    movies = [s for s in (tl.get("data") or {}).get("strips", []) if s["type"] == "MOVIE"]
    return [m["name"] for m in sorted(movies, key=lambda x: x["frame_start"])]


def main():
    global PROJECT
    print("=== Incremental revision: Incremental adapter (Edit Patch + revision) ===")
    if not live_session_available():
        print("[SKIP] no live bridge (interactive ops require it)")
        sys.exit(0)
    proj = resolve_project()
    blender_execute("clear_vse", {"project": proj})
    r = blender_execute("create_project", {"project": proj, "resolution": [1280, 720], "fps": 30})
    check("create_project (revision baseline)", r.get("ok") and r["data"].get("revision") == 1)

    # ---- build a 3-clip + title timeline (each add bumps the revision) ----
    blender_execute("add_movie", {"project": proj, "asset": str(MEDIA / "clip_a.mp4"),
                                  "channel": 1, "frame_start": 1, "strip_name": "clipA"})
    blender_execute("add_movie", {"project": proj, "asset": str(MEDIA / "clip_b.mp4"),
                                  "channel": 1, "frame_start": 151, "strip_name": "clipB"})
    blender_execute("add_movie", {"project": proj, "asset": str(MEDIA / "clip_a.mp4"),
                                  "channel": 1, "frame_start": 301, "strip_name": "clipC"})
    blender_execute("add_text", {"project": proj, "text": "Hello", "channel": 3,
                                 "frame_start": 1, "length": 120, "strip_name": "Title"})
    blender_execute("create_text_style", {"project": proj, "name": "big",
                                          "style": {"font_size": 80, "alignment": "CENTER"}})
    check("timeline order A,B,C", movie_order(proj) == ["clipA", "clipB", "clipC"])

    r = blender_execute("get_revision", {"project": proj})
    d = r.get("data") or {}
    check("get_revision consistent after build", r.get("ok") and d.get("consistent") is True
          and d.get("revision_changed") is False, str(d)[:200])
    rev = d.get("revision")
    hsh = d.get("timeline_hash")
    check("revision advanced past 1", isinstance(rev, int) and rev > 1, f"rev={rev}")

    # ids for stable references
    tl = blender_execute("list_strips", {"project": proj})
    strips = {s["name"]: s for s in (tl.get("data") or {}).get("strips", [])}
    b_id = strips["clipB"]["video_ai_id"]
    a_id = strips["clipA"]["video_ai_id"]

    # ---- 1. Edit Patch: ripple_delete B + apply_text_style Title ----
    # patch commands reference strips by STABLE ID (video_ai_id) or by name
    # (target). ripple_delete's 'target' slot is the strip NAME, so the ID goes
    # through the video_ai_id slot — this is exactly how the stable ID pays off
    # after a manual reorder.
    r = blender_execute("apply_patch", {"project": proj, "base_revision": rev,
                                        "base_timeline_hash": hsh, "patch_id": "p11_1_" + uuid.uuid4().hex[:10], "commands": [
        {"op": "ripple_delete", "video_ai_id": b_id},
        {"op": "apply_text_style", "target": "Title", "style": "big"},
    ]})
    check("apply_patch ok", r.get("ok") and r["data"].get("applied") is True,
          str(r.get("error"))[:300])
    if r.get("ok"):
        d = r["data"]
        check("patch committed revision+1", d.get("applied_revision") == rev + 1,
              f"applied_revision={d.get('applied_revision')}")
        check("patch results all ok", all(x.get("ok") for x in d.get("results", []))
              and len(d.get("results", [])) == 2, str(d.get("results"))[:200])
        check("checkpoint created", (PROJECT.parent / "checkpoints" / f"patch_r{rev}.blend").is_file())
    check("timeline order A,C after ripple_delete", movie_order(proj) == ["clipA", "clipC"])
    tl = blender_execute("list_strips", {"project": proj, "with_text": True})
    title = next((s for s in (tl.get("data") or {}).get("strips", []) if s["name"] == "Title"), {})
    check("style applied by patch (font_size 80)", title.get("font_size") == 80.0,
          f"font_size={title.get('font_size')}")

    # ---- 2. stale base revision refused ----
    r = blender_execute("apply_patch", {"project": proj, "base_revision": rev,  # old!
                                        "base_timeline_hash": hsh,
                                        "patch_id": "p11_old_" + uuid.uuid4().hex[:10],
                                        "commands": [
        {"op": "set_opacity", "target": a_id, "opacity": 0.5}]})
    check("revision_mismatch refused (old base_revision)", not r.get("ok")
          and "revision_mismatch" in str(r.get("error")), str(r.get("error"))[:200])

    # ---- 3. COMPLETION STANDARD: manual edit in Blender GUI ----
    # "Human drags the last clip to the front and saves" — simulated via the
    # bridge (exactly what the user does by hand, then Ctrl+S).
    r = _live_exec(f"""
import bpy
se = bpy.context.scene.sequence_editor
_a = se.strips["clipA"]; _c = se.strips["clipC"]
# drag clipC to the front; A shifts back (ripple by hand)
_a.frame_start = 151
_c.frame_start = 1
bpy.ops.wm.save_as_mainfile(filepath={json.dumps(proj)})
print("MANUAL_EDIT_DONE")
""")
    check("manual edit applied + saved (simulated)", "MANUAL_EDIT_DONE" in (r.get("output") or ""))

    r = blender_execute("get_revision", {"project": proj})
    d = r.get("data") or {}
    check("revision changed detected (dirty/revision_changed)",
          r.get("ok") and d.get("dirty") is True and d.get("revision_changed") is True
          and d.get("consistent") is False, str(d)[:200])
    check("revision number unchanged by manual edit", d.get("revision") == rev + 1,
          f"rev={d.get('revision')}")
    check("caller re-reads manual order C,A", movie_order(proj) == ["clipC", "clipA"],
          str(movie_order(proj)))

    # AI's next patch based on the OLD hash must be REFUSED (never overwrite manual work)
    r = blender_execute("apply_patch", {"project": proj, "base_revision": rev + 1,
                                        "base_timeline_hash": hsh, "patch_id": "p11_2_" + uuid.uuid4().hex[:10], "commands": [
        {"op": "set_opacity", "target": "clipA", "opacity": 0.5}]})
    check("stale_base refused (manual edit not overwritten)", not r.get("ok")
          and "stale_base" in str(r.get("error")), str(r.get("error"))[:200])
    check("manual order intact after refusal", movie_order(proj) == ["clipC", "clipA"])

    # ---- 4. acknowledge the manual edit as the new base ----
    _ra = blender_execute("get_revision", {"project": proj})
    r = blender_execute("acknowledge_revision", {"project": proj,
        "observed_revision": _ra["data"]["revision"],
        "observed_hash": _ra["data"]["timeline_hash"],
        "read_token": _ra["data"]["observation_id"]})
    check("acknowledge_revision", r.get("ok") and r["data"].get("acknowledged") is True
          and r["data"].get("revision") == rev + 2)
    r = blender_execute("get_revision", {"project": proj})
    d = r.get("data") or {}
    check("consistent again after acknowledge", r.get("ok") and d.get("consistent") is True
          and d.get("dirty") is False)
    new_hsh = d.get("timeline_hash")

    # ---- 5. AI continues incrementally on the NEW base, manual order preserved ----
    r = blender_execute("apply_patch", {"project": proj, "base_revision": rev + 2,
                                        "base_timeline_hash": new_hsh, "patch_id": "p11_4_" + uuid.uuid4().hex[:10], "commands": [
        {"op": "set_opacity", "target": "clipA", "opacity": 0.6},
        {"op": "set_text", "target": "Title", "text": "Incremental"},
    ]})
    check("next patch applies on acknowledged base", r.get("ok") and r["data"].get("applied") is True)
    check("manual order STILL C,A after incremental patch",
          movie_order(proj) == ["clipC", "clipA"], str(movie_order(proj)))
    tl = blender_execute("list_strips", {"project": proj, "with_text": True})
    title = next((s for s in (tl.get("data") or {}).get("strips", []) if s["name"] == "Title"), {})
    check("incremental edit landed (text)", title.get("text") == "Incremental")
    r = blender_execute("get_revision", {"project": proj})
    d = r.get("data") or {}
    check("final revision consistent", r.get("ok") and d.get("revision") == rev + 3
          and d.get("consistent") is True, str(d)[:150])

    # persistence gate: .blend is the source of truth
    vp = blender_execute("verify_persistence", {"project": proj,
                                                "expected": {"movie": 2, "sound": 0, "text": 1}})
    check("verify_persistence ok", vp.get("ok"))
    if vp.get("ok"):
        check("persistence_verified=true", vp["data"].get("persistence_verified") is True)

    passed = sum(1 for _, ok in RESULTS if ok)
    print(f"\n=== Incremental revision: {passed}/{len(RESULTS)} passed ===")
    if passed < len(RESULTS):
        sys.exit(1)


if __name__ == "__main__":
    main()
