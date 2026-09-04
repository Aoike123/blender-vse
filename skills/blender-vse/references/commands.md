# Patch commands

[Chinese version](commands_zh-CN.md)

Read this reference only when preparing `blender_patch.commands`. Each command
is a JSON object containing an `op` and its operation-specific parameters. The
patch-level project, revision, hash, observation ID, and patch ID do not belong
inside individual commands.

## Find the exact command shape

[command-index.json](command-index.json) is generated from the canonical Python
operation catalog and function signatures. Search that file for the exact
operation name instead of loading the entire index. A parameter without `=` is
required; a parameter with `=` is optional and shows its default. Type
annotations describe the values accepted by the host.

Do not invent parameters. The outer patch is already atomic, so do not use the
excluded `batch` operation. Project creation belongs to
`blender_read(create_if_missing=true)`, acknowledgement belongs to
`blender_acknowledge`, and persistence proof belongs to `blender_verify`.

Read-only catalog operations are intentionally absent: use `blender_read`
instead of placing discovery or inspection operations in a patch.

## Reference strips correctly

- When an operation accepts `video_ai_id`, prefer the stable ID returned by a
  targeted read.
- When an operation accepts only `target`, pass the current strip name from that
  same fresh read. Do not assume every legacy `target` field accepts an ID.
- Never guess a strip identifier. If the required field was not returned, make
  a narrower detail read before patching.

## Time and paths

- Prefer frame fields (`frame_start`, `frame_end`, `at_frame`, `frames`) for
  frame-exact work. Use second-based source/timeline fields only when the
  operation calls for them; do not mix units accidentally.
- Use absolute media, subtitle, font, manifest, render, copy, and package paths.
  Do not invent missing source paths, and never overwrite a source asset with a
  render.
- Proxies are built outside Blender. `attach_proxy` consumes an external
  `manifest_path` that has already been verified; `detach_proxy` and
  `clear_proxies` do not authorize file deletion.

## Small examples

Add an editable title:

```json
[
  {
    "op": "add_text",
    "text": "Opening title",
    "channel": 3,
    "frame_start": 1,
    "length": 90,
    "font_size": 64,
    "position": [0.5, 0.82],
    "strip_name": "OpeningTitle"
  }
]
```

Make two related edits atomically after a detail read returned the current
names:

```json
[
  {"op": "trim_strip", "target": "Interview_A", "frame_end": 420},
  {"op": "set_volume", "target": "Interview_Audio", "volume": 0.82}
]
```

Render the verified timeline to a new output path:

```json
[
  {
    "op": "render_final",
    "output_path": "/absolute/output/final.mp4",
    "resolution": [1920, 1080],
    "fps": 30,
    "frame_start": 1,
    "frame_end": 900,
    "codec": "H264",
    "quality": "high"
  }
]
```

Adapt path syntax to the local operating system.

## High-risk commands

- `clear_vse`, deletion, ripple edits, extraction, overwrites, asset
  replacement, checkpoint deletion, and restore operations require clear user
  intent.
- `restore_checkpoint` must be the only command in its patch. The controller
  creates a recoverable pre-restore backup and reopens the exact GUI project.
- A render or package command can be grouped with edits only when one atomic
  transaction is genuinely desired; normally re-read the completed edit first,
  then render in a fresh patch.
- Prefer one coherent editorial action per patch. Smaller patches are easier to
  reason about during rollback, stale-base recovery, and human review.
