"""Create a project, add a title, then verify the saved timeline."""

from __future__ import annotations

import json
import uuid

from blender_vse import BlenderVSE


def main() -> None:
    controller = BlenderVSE()
    observed = controller.read("demo.blend", create_if_missing=True)
    if not observed.get("ok"):
        raise SystemExit(json.dumps(observed, indent=2))
    base = observed["data"]
    patched = controller.patch(
        "demo.blend",
        base_revision=base["revision"],
        base_timeline_hash=base["timeline_hash"],
        read_token=base["observation_id"],
        patch_id="example-" + uuid.uuid4().hex,
        commands=[
            {
                "op": "add_text",
                "text": "Blender VSE Control",
                "channel": 3,
                "frame_start": 1,
                "length": 90,
            }
        ],
    )
    print(json.dumps(patched, indent=2, ensure_ascii=False))
    if not patched.get("ok"):
        raise SystemExit(1)
    verified = controller.verify("demo.blend", expected={"text": 1})
    print(json.dumps(verified, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
