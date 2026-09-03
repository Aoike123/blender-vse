"""Native media inspector.

The ONE media-facts model: {duration, fps, width, height, video_codec,
audio_codec, audio_channels, sample_rate} + native provenance, produced ONLY by
Blender's native decode path (inspect_media) — NEVER ffprobe.

Verifies:
  1. unified MediaInfo fields for video (clip_a/clip_b) and audio (music.mp3)
  2. schema conformance (manual field checks; jsonschema when importable)
  3. fail-fast input validation (missing file -> input_missing)
  4. cross-mode consistency: headless subprocess result == GUI-bridge result
     (the exact generated script, executed inside the running Blender)
  5. invariants: duration * source_fps ~= decoded frames
  6. cleanliness: no probe strips / sound datablocks left behind

Run through: python tests/run.py blender-headless
Headless is the production path; the live-consistency section runs only when a
GUI bridge is reachable.
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from blender_vse.blender import blender_execute, live_session_available
from blender_vse.blender.vse_ops import _edit_scene_prologue, inspect_media as _gen_inspect

MEDIA = ROOT / "tests" / "fixtures" / "media"
RESULTS = []
LIVE_CHECKS = os.environ.get("BLENDER_VSE_TEST_LIVE", "1").strip().lower() \
    not in {"0", "false", "no", "off"}


def check(name, ok, detail=""):
    RESULTS.append((name, ok))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail and not ok else ""))
    return ok


def check_schema(name, info):
    """Manual conformance against schemas/media-info.schema.json (jsonschema optional)."""
    required = ["path", "kind", "duration", "fps", "width", "height",
                "video_codec", "audio_codec", "audio_channels", "sample_rate", "native"]
    ok = isinstance(info, dict) and all(k in info for k in required)
    ok = ok and info["kind"] in ("video", "audio")
    ok = ok and (info["fps"] is None or isinstance(info["fps"], (int, float)))
    ok = ok and (info["width"] is None or isinstance(info["width"], int))
    ok = ok and (info["height"] is None or isinstance(info["height"], int))
    ok = ok and (info["audio_channels"] in (None, 1, 2))
    ok = ok and (info["duration"] is None or isinstance(info["duration"], (int, float)))
    ok = ok and info["native"].get("source") == "blender-native"
    ok = ok and info["video_codec"] is None and info["audio_codec"] is None \
        and info["sample_rate"] is None
    try:
        import jsonschema  # strict check when available
        schema = json.loads(
            (
                ROOT
                / "src"
                / "blender_vse"
                / "schemas"
                / "media-info.schema.json"
            ).read_text(encoding="utf-8-sig")
        )
        jsonschema.validate(info, schema)
        strict = True
    except ImportError:
        strict = False
    except Exception as e:
        check(name + " (strict schema)", False, str(e)[:200])
        return
    check(name + (" (schema)" if strict else " (field check)"), ok, "" if ok else json.dumps(info)[:300])


def main():
    print("=== Media inspector: Native Media Inspector (single source of truth) ===")
    # ---- 1. fail-fast input validation ----
    r = blender_execute("inspect_media", {"project": None,
                                          "media_path": str(MEDIA / "nope.mp4")})
    check("missing file -> input_missing", not r.get("ok")
          and (r.get("error") or {}).get("code") == "input_missing",
          str(r.get("error"))[:120])

    # ---- 2. headless facts (production path) ----
    facts = {}
    for f in ("clip_a.mp4", "clip_b.mp4", "music.mp3"):
        r = blender_execute("inspect_media", {"project": None,
                                              "media_path": str(MEDIA / f)})
        check(f"inspect_media {f}", r.get("ok"), str(r.get("error"))[:200])
        if r.get("ok"):
            facts[f] = r["data"]

    a = facts.get("clip_a.mp4", {})
    check_schema("clip_a.mp4", a)
    check("clip_a kind=video", a.get("kind") == "video")
    check("clip_a duration 5.0s", a.get("duration") is not None and abs(a["duration"] - 5.0) < 0.06,
          f"duration={a.get('duration')}")
    check("clip_a fps 30", a.get("fps") == 30.0, f"fps={a.get('fps')}")
    check("clip_a 1280x720", a.get("width") == 1280 and a.get("height") == 720)
    check("clip_a audio_channels 1", a.get("audio_channels") == 1)

    b = facts.get("clip_b.mp4", {})
    check_schema("clip_b.mp4", b)
    check("clip_b duration 4.0s", b.get("duration") is not None and abs(b["duration"] - 4.0) < 0.06,
          f"duration={b.get('duration')}")
    check("clip_b fps 30 + 1280x720", b.get("fps") == 30.0 and b.get("width") == 1280
          and b.get("height") == 720)

    m = facts.get("music.mp3", {})
    check_schema("music.mp3", m)
    check("music kind=audio", m.get("kind") == "audio")
    check("music fps/width/height null", m.get("fps") is None and m.get("width") is None
          and m.get("height") is None)
    check("music duration ~3.04s", m.get("duration") is not None and abs(m["duration"] - 3.04) < 0.2,
          f"duration={m.get('duration')}")
    check("music audio_channels 1", m.get("audio_channels") == 1)

    # invariants: duration * source_fps == decoded frames
    na = a.get("native", {})
    check("invariant clip_a: dur*fps == strip frames",
          na.get("strip_frame_duration") is not None
          and abs(a["duration"] * a["fps"] - na["strip_frame_duration"]) < 1.0)
    nm = m.get("native", {})
    check("invariant music: sound frames decoded",
          nm.get("sound_frame_duration") is not None and nm["sound_frame_duration"] > 0)

    # ---- 3. cross-mode consistency: GUI-bridge result == headless result ----
    if LIVE_CHECKS and live_session_available():
        from blender_vse.blender.live_session import execute_code as _live_exec
        from blender_vse.blender.runner import BlenderRunner
        for f in ("clip_a.mp4", "music.mp3"):
            script = _edit_scene_prologue() + "\n" + _gen_inspect(project=None,
                                                                  media_path=str(MEDIA / f))
            rr = _live_exec(BlenderRunner._wrap_live(script, "inspect_media"))
            live_data = None
            for _l in (rr.get("output") or "").splitlines():
                if _l.startswith("VP_RESULT:"):
                    try:
                        live_data = json.loads(_l[len("VP_RESULT:"):])
                    except Exception:
                        pass
            head = facts[f]
            # audio duration is decoded-frame / scene-fps: frame rounding differs
            # by <=1 frame between scenes (24 vs 30 fps) — tolerate 0.1s for audio
            tol = 0.1 if head.get("kind") == "audio" else 1e-6
            same = (live_data is not None
                    and live_data.get("kind") == head.get("kind")
                    and live_data.get("fps") == head.get("fps")
                    and live_data.get("width") == head.get("width")
                    and live_data.get("height") == head.get("height")
                    and live_data.get("audio_channels") == head.get("audio_channels")
                    and abs((live_data.get("duration") or 0) - (head.get("duration") or 0)) < tol)
            check(f"live/headless facts identical ({f})", same,
                  f"live={live_data} head={head}" if not same else "")
    else:
        print("[SKIP] live-bridge consistency check (no bridge — headless path verified only)")

    # ---- 4. cleanliness: no probe strips or Sound datablocks left behind ----
    if LIVE_CHECKS and live_session_available():
        from blender_vse.blender.live_session import execute_code as _live_exec
        rr = _live_exec(
            "import bpy\n"
            "se = bpy.context.scene.sequence_editor\n"
            "_left = []\n"
            "if se is not None:\n"
            "    _left = [s.name for s in se.strips if s.name.startswith('_vp_inspect')]\n"
            "_snd = [s.name for s in bpy.data.sounds if s.name.startswith('_vp_inspect')]\n"
            "print('LEFT:' + repr(_left))\n"
            "print('SOUNDS:' + repr(_snd))\n")
        out = rr.get("output") or ""
        left = "LEFT:[]" in out
        snds = "SOUNDS:[]" in out
        check("no probe strips left in GUI", left, out[-300:])
        check("no probe sound datablocks left", snds, out[-300:])

    passed = sum(1 for _, ok in RESULTS if ok)
    print(f"\n=== Media inspector: {passed}/{len(RESULTS)} passed ===")
    if passed < len(RESULTS):
        sys.exit(1)


if __name__ == "__main__":
    main()
