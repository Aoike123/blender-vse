"""Execution governance tests: headless refusal + input/output verification.

Verifies the two governance rules:

  1. INTERACTIVE VSE OPS REQUIRE A LIVE GUI SESSION.
     Under BLENDER_VSE_EXECUTION=headless, add/move/trim/text/assemble/subtitle
     ops are REFUSED with a clear error (no escape hatch). Only
     render_preview/render_final/verify_persistence may run headless.
  2. INPUT/OUTPUT VERIFICATION (exercised against a LIVE bridge).
     - Missing input assets are rejected BEFORE Blender is spawned
       (input_missing error).
     - Mutating ops report `save_verified` (the .blend was written) and
       `timeline_verified` (strips re-read after the edit).

Part 1 (refusal) runs headless. Part 2/3 (I/O verification) require a live
bridge and are SKIPPED if none is reachable — they are never downgraded to
headless.

Run through: python tests/run.py blender-full
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from blender_vse.blender import blender_execute, live_session_available, get_runner
from blender_vse.blender.runner import RunnerConfig, HEADLESS_ALLOWED_OPS

MEDIA = ROOT / "tests" / "fixtures" / "media"
PROJECT = ROOT / "projects" / "execution_governance_test.blend"

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, ok))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail and not ok else ""))


def main():
    print("=== Execution governance: governance (headless refusal + I/O verification) ===\n")

    # ---- 1. Interactive ops are refused under headless (no escape hatch) ----
    # Force an explicit headless runner; NO exemption variable exists anymore.
    os.environ["BLENDER_VSE_EXECUTION"] = "headless"
    runner = get_runner()
    runner.config = RunnerConfig(execution="headless")

    if PROJECT.exists():
        PROJECT.unlink()

    r = blender_execute("add_movie", {"project": str(PROJECT),
                                      "asset": str(MEDIA / "clip_a.mp4"), "channel": 1})
    check("interactive add_movie REFUSED under headless", not r.get("ok"))
    if not r.get("ok"):
        msg = (r.get("error") or {}).get("message", "")
        check("refusal mentions live GUI requirement", "INTERACTIVE VSE edit" in msg
              and "live" in msg.lower())

    r2 = blender_execute("add_subtitle_track", {"project": str(PROJECT), "segments": [
        {"start_seconds": 0, "end_seconds": 1, "text": "x"}]})
    check("interactive add_subtitle_track REFUSED under headless", not r2.get("ok"))

    r3 = blender_execute("assemble_clips", {"project": str(PROJECT), "clips": [
        {"asset": str(MEDIA / "clip_a.mp4")}]})
    check("interactive assemble_clips REFUSED under headless", not r3.get("ok"))

    # headless whitelist shape: render/verify ops + native media probing
    # (inspect_media is media preprocessing — headless is its production path)
    check("headless whitelist is render/verify + media probe",
          HEADLESS_ALLOWED_OPS == {"render_preview", "render_final",
                                   "verify_persistence", "inspect_media"},
          str(HEADLESS_ALLOWED_OPS))

    # ---- 2/3. Input + output verification — REQUIRES live bridge ----
    if not live_session_available():
        print("\n[SKIP] no live bridge — I/O verification needs a live session "
              "(not downgrading to headless).")
        passed = sum(1 for _, ok in RESULTS if ok)
        print(f"\n=== Execution governance: {passed}/{len(RESULTS)} passed (I/O part skipped) ===")
        sys.exit(0 if passed == len(RESULTS) else 1)

    os.environ["BLENDER_VSE_EXECUTION"] = "live_session"
    runner.config = RunnerConfig(execution="live_session")

    # ---- 2. Input validation (missing asset rejected before Blender) ----
    r5 = blender_execute("add_movie", {"project": str(PROJECT),
                                       "asset": str(MEDIA / "does_not_exist.mp4"), "channel": 1})
    check("missing asset rejected (input_missing)", not r5.get("ok"))
    if not r5.get("ok"):
        check("error code is input_missing", (r5.get("error") or {}).get("code") == "input_missing")

    r6 = blender_execute("assemble_clips", {"project": str(PROJECT), "clips": [
        {"asset": str(MEDIA / "nope.mp4")}]})
    check("missing clip asset rejected (input_missing)", not r6.get("ok"))

    # ---- 3. Output verification on real mutating ops (LIVE) ----
    if PROJECT.exists():
        PROJECT.unlink()
    r_c = blender_execute("create_project", {"project": str(PROJECT),
                                             "resolution": [640, 360], "fps": 30})
    check("create_project ok (live)", r_c.get("ok"))
    if r_c.get("ok"):
        check("create_project ran live", r_c.get("mode") == "live")
        sv = r_c.get("save_verified") or {}
        check("create_project save_verified (file created)",
              sv.get("saved") is True, json.dumps(sv)[:200])

    r4 = blender_execute("get_timeline_info", {"project": str(PROJECT)})
    check("read-only get_timeline_info allowed (live)", r4.get("ok"))

    r8 = blender_execute("add_movie", {"project": str(PROJECT),
                                       "asset": str(MEDIA / "clip_a.mp4"),
                                       "channel": 1, "frame_start": 1})
    check("add_movie ok (live)", r8.get("ok"))
    if r8.get("ok"):
        check("add_movie ran live", r8.get("mode") == "live")
        sv = r8.get("save_verified") or {}
        check("add_movie save_verified (blend written)",
              sv.get("saved") is True, json.dumps(sv)[:200])
        tv = r8.get("timeline_verified") or {}
        check("add_movie timeline_verified (re-read)",
              tv.get("strip_count", 0) >= 1, json.dumps(tv)[:200])

    r9 = blender_execute("add_subtitle_track", {"project": str(PROJECT), "segments": [
        {"start_seconds": 0, "end_seconds": 2, "text": "governance"}],
        "channel": 5, "fps": 30, "strip_prefix": "Sub_"})
    check("add_subtitle_track ok (live)", r9.get("ok"))
    if r9.get("ok"):
        tv = r9.get("timeline_verified") or {}
        check("subtitle timeline re-read has text strips",
              tv.get("strip_count", 0) >= 2, json.dumps(tv)[:200])

    passed = sum(1 for _, ok in RESULTS if ok)
    print(f"\n=== Execution governance: {passed}/{len(RESULTS)} passed ===")
    if passed < len(RESULTS):
        sys.exit(1)


if __name__ == "__main__":
    main()
