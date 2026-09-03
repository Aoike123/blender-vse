"""One end-to-end public API workflow against a disposable Blender project."""

from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from blender_vse import BlenderVSE  # noqa: E402
from blender_vse.blender import live_session  # noqa: E402

MEDIA = ROOT / "tests" / "fixtures" / "media"
PROJECT = ROOT / "projects" / "public-api-smoke.blend"


def cleanup_failed_launch(result: dict) -> bool:
    """Close only a clean blank/test session launched by this smoke run."""

    session = result.get("session") or {}
    state = session.get("last_observation") or session
    if not session.get("launched") or state.get("is_dirty"):
        return False
    current = state.get("filepath") or ""
    if current and Path(current).resolve() != PROJECT.resolve():
        return False
    cleaned = live_session._shutdown_hidden_session(state)
    print(f"[{'PASS' if cleaned else 'WARN'}] clean up failed smoke launch")
    return cleaned


def require(result: dict, label: str) -> dict:
    if not result.get("ok"):
        print(json.dumps({"step": label, "result": result}, indent=2, default=str))
        raise SystemExit(1)
    print(f"[PASS] {label}")
    return result["data"]


def require_bounded(data: dict, label: str) -> None:
    context = data.get("context") or {}
    if not context.get("bounded") or context.get("response_bytes", 0) > context.get(
        "max_bytes", 0
    ):
        raise SystemExit(f"{label} was not context bounded: {context}")
    print(f"[PASS] {label} context budget")


def patch(controller: BlenderVSE, base: dict, commands: list[dict], label: str) -> None:
    require(
        controller.patch(
            PROJECT,
            base_revision=base["revision"],
            base_timeline_hash=base["timeline_hash"],
            read_token=base["observation_id"],
            patch_id="smoke-" + uuid.uuid4().hex,
            commands=commands,
        ),
        label,
    )


def main() -> None:
    started = time.perf_counter()
    controller = BlenderVSE()
    initial = controller.read(
        PROJECT,
        create_if_missing=True,
        resolution=(640, 360),
        fps=30,
    )
    if not initial.get("ok"):
        cleanup_failed_launch(initial)
    base = require(
        initial,
        "create/read disposable project",
    )
    require_bounded(base, "initial summary")
    if base["summary"]["total_strips"]:
        patch(controller, base, [{"op": "clear_vse"}], "clear prior smoke timeline")
        base = require(controller.read(PROJECT), "read after cleanup")
        require_bounded(base, "cleanup summary")

    patch(
        controller,
        base,
        [
            {
                "op": "add_movie",
                "asset": str(MEDIA / "clip_a.mp4"),
                "channel": 1,
                "frame_start": 1,
                "strip_name": "Smoke_A",
            },
            {
                "op": "add_movie",
                "asset": str(MEDIA / "clip_b.mp4"),
                "channel": 1,
                "frame_start": 151,
                "strip_name": "Smoke_B",
            },
            {
                "op": "add_sound",
                "asset": str(MEDIA / "music.mp3"),
                "channel": 10,
                "frame_start": 1,
                "strip_name": "Smoke_Music",
            },
            {
                "op": "add_text",
                "text": "Smoke title",
                "channel": 3,
                "frame_start": 1,
                "length": 90,
                "strip_name": "Smoke_Title",
            },
            {"op": "add_marker", "name": "smoke-start", "frame": 1},
        ],
        "apply atomic assembly patch",
    )

    observed = require(
        controller.read(
            PROJECT,
            view="range",
            frame_range=(1, 300),
            include=("text",),
            limit=50,
        ),
        "read assembled timeline range",
    )
    require_bounded(observed, "assembled range")
    strips = observed["strips"]
    counts = {
        kind: sum(strip["type"] == kind for strip in strips)
        for kind in ("MOVIE", "SOUND", "TEXT")
    }
    if counts != {"MOVIE": 2, "SOUND": 1, "TEXT": 1}:
        raise SystemExit(f"unexpected strip counts: {counts}")
    print("[PASS] assembled strip counts")

    title = next(strip for strip in strips if strip["type"] == "TEXT")
    patch(
        controller,
        observed,
        [
            {
                "op": "set_text",
                "video_ai_id": title["video_ai_id"],
                "text": "Smoke title updated",
            }
        ],
        "apply second patch from fresh observation",
    )
    final = require(
        controller.read(
            PROJECT,
            view="detail",
            strip_ids=(title["video_ai_id"],),
            include=("text",),
        ),
        "read updated title detail",
    )
    require_bounded(final, "updated detail")
    if not any(strip.get("text") == "Smoke title updated" for strip in final["strips"]):
        raise SystemExit("updated title was not observed")
    print("[PASS] read-after-write observed updated title")

    require(
        controller.verify(PROJECT, expected={"movie": 2, "sound": 1, "text": 1}),
        "fresh-process persistence verification",
    )
    print(f"SMOKE PASSED in {time.perf_counter() - started:.2f}s")


if __name__ == "__main__":
    main()
