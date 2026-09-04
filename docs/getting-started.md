# Getting started

[Chinese version](getting-started_zh-CN.md)

## 1. Prerequisites

- Python 3.10 or newer for development from source or through the CLI. Users
  who install through a Harness plugin do not need Python installed
  system-wide; the installation process bootstraps `uv`, which provisions a
  managed Python 3.12 environment.
- A separate Blender installation
- FFmpeg, only for proxy-media workflows and generated integration fixtures

Blender 5.1 is the primary verified target. Do not install a separate `bpy`
wheel; the controller uses Blender's bundled runtime.

## 2. Install for development

```bash
python -m venv .venv
python -m pip install -e ".[dev]"
```

If Blender is not on `PATH`, specify the path to its executable:

```powershell
$env:BLENDER_VSE_BLENDER_EXECUTABLE = "C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"
```

```bash
export BLENDER_VSE_BLENDER_EXECUTABLE=/Applications/Blender.app/Contents/MacOS/Blender
```

Confirm that the controller can discover its environment without modifying a
project:

```bash
blender-vse status
blender-vse context-policy
blender-vse ops --family revision
```

The `status` command only observes the environment. It is normal for no live
session to exist until the first interactive operation starts Blender or
connects to it.

## 3. Create and read a project

```bash
blender-vse read ./projects/demo.blend --create --resolution 1920 1080 --fps 30
```

Save these fields from the response:

- `revision`
- `timeline_hash`
- `observation_id`

Together, they identify the exact timeline state on which the next patch must
be based. The default response is a bounded summary and does not list
individual strips.

Inspect only the part of the timeline that you plan to edit:

```bash
blender-vse read ./projects/demo.blend \
  --view range --frame-range 1 300 --include text --limit 50

blender-vse read ./projects/demo.blend \
  --view detail --strip-id TEXT_STRIP_ID --include text
```

If `context.has_more` is true, repeat the same query with
`--cursor NEXT_CURSOR`. Build the patch from the observation fields returned by
the most recent targeted read.

## 4. Apply one atomic patch

If the command data is too complex to quote safely in the shell, place the
commands in a JSON file:

```json
[
  {
    "op": "add_text",
    "text": "Hello",
    "channel": 3,
    "frame_start": 1,
    "length": 90
  }
]
```

```bash
blender-vse patch ./projects/demo.blend \
  --base-revision 0 \
  --base-timeline-hash HASH_FROM_READ \
  --read-token TOKEN_FROM_READ \
  --patch-id patch-title-001 \
  --commands @commands.json
```

Patch IDs are idempotency keys. Reusing an ID from a successful patch must not
apply the same edit a second time.

## 5. Read again and verify

```bash
blender-vse read ./projects/demo.blend
blender-vse verify ./projects/demo.blend --expected '{"text":1}'
```

Never construct another patch from a previous patch response. Perform a fresh
read to obtain a new, single-use observation ID.

## Python equivalent

```python
from blender_vse import BlenderVSE

controller = BlenderVSE()
controller.read("demo.blend")  # bounded project summary
observed = controller.read(
    "demo.blend",
    view="detail",
    strip_ids=("text-strip-id",),
    include=("text",),
)
base = observed["data"]
title = base["strips"][0]

result = controller.patch(
    "demo.blend",
    base_revision=base["revision"],
    base_timeline_hash=base["timeline_hash"],
    read_token=base["observation_id"],
    patch_id="patch-title-001",
    commands=[
        {
            "op": "set_text",
            "target": title["name"],
            "text": "Updated title",
        }
    ],
)
```

For result and error handling, continue with the [API reference](api.md).

## Agent-hosted MCP

The CLI and Python examples above do not require an Agent framework. To make the
same revision-safe workflow available to Codex, Claude, or another MCP host,
continue with the [local MCP server guide](mcp.md). The optional MCP extra does
not change the four-step API contract.
