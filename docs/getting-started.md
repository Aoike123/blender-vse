# Getting started

[Chinese version](getting-started_zh-CN.md)

## 1. Prerequisites

- For source/CLI development, Python 3.10 or newer. Harness plugin users do not
  need system Python; the installation flow bootstraps `uv`, which provisions
  managed Python 3.12.
- Blender installed separately
- FFmpeg only for proxy workflows and generated integration fixtures

Blender 5.1 is the primary verified target. Do not install a separate `bpy`
wheel; the controller uses Blender's own runtime.

## 2. Install for development

```bash
python -m venv .venv
python -m pip install -e ".[dev]"
```

If Blender is not on `PATH`, set its executable:

```powershell
$env:BLENDER_VSE_BLENDER_EXECUTABLE = "C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"
```

```bash
export BLENDER_VSE_BLENDER_EXECUTABLE=/Applications/Blender.app/Contents/MacOS/Blender
```

Verify discovery without changing a project:

```bash
blender-vse status
blender-vse context-policy
blender-vse ops --family revision
```

`status` is observational. A missing live session is normal until the first
interactive operation starts or connects to Blender.

## 3. Create and read a project

```bash
blender-vse read ./projects/demo.blend --create --resolution 1920 1080 --fps 30
```

Keep these fields from the result:

- `revision`
- `timeline_hash`
- `observation_id`

Together they prove which timeline state the next patch was built from.
The default response is a bounded summary and does not include individual
strips.

Inspect only the part you plan to edit:

```bash
blender-vse read ./projects/demo.blend \
  --view range --frame-range 1 300 --include text --limit 50

blender-vse read ./projects/demo.blend \
  --view detail --strip-id TEXT_STRIP_ID --include text
```

If `context.has_more` is true, call the same query with
`--cursor NEXT_CURSOR`. Use the observation fields from the last targeted read
for the patch.

## 4. Apply one atomic patch

For shell quoting beyond a short example, place commands in a JSON file:

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

Patch IDs are idempotency keys. Repeating the same successful ID must not apply
the edit twice.

## 5. Read again and verify

```bash
blender-vse read ./projects/demo.blend
blender-vse verify ./projects/demo.blend --expected '{"text":1}'
```

Never construct a second patch from a previous patch response. Read again to
obtain a new single-use observation token.

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

result = controller.patch(
    "demo.blend",
    base_revision=base["revision"],
    base_timeline_hash=base["timeline_hash"],
    read_token=base["observation_id"],
    patch_id="patch-title-001",
    commands=[
        {
            "op": "set_text",
            "video_ai_id": "text-strip-id",
            "text": "Updated title",
        }
    ],
)
```

For result and error handling, continue with the [API reference](api.md).

## Agent-hosted MCP

The CLI and Python examples above can run without an Agent framework. To expose
the same revision-safe workflow to Codex, Claude, or another MCP host, continue
with the [local MCP server guide](mcp.md). The MCP extra is optional and does
not change the four-step API contract.
