# Configuration

[Chinese version](configuration_zh-CN.md)

All settings are optional. Preferred names use `BLENDER_VSE_*`; listed `VP_*`
aliases exist only for migration compatibility.

## Project location

Projects always live in `<workspace>/blender-vse-projects`, where the workspace
is the folder the MCP host starts the server in. Tool calls pass paths relative
to that folder. See [Installation](installation.md#where-projects-live).

## Runtime and execution

| Variable | Legacy alias | Default | Purpose |
| --- | --- | --- | --- |
| `BLENDER_VSE_BLENDER_EXECUTABLE` | `VP_BLENDER_EXECUTABLE` | `BLENDER_EXECUTABLE`, known install paths, then `PATH` | Blender executable |
| `BLENDER_VSE_EXECUTION` | `VP_BLENDER_EXECUTION` | `live_session` | `live_session` or `headless`; interactive edits still refuse headless |
| `BLENDER_VSE_STATE_DIR` | — | OS user-data directory | Runtime state root |
| `BLENDER_VSE_TMP_DIR` | `VP_TMP_DIR` | `<state>/tmp` | Generated fixed scripts and session logs |
| `BLENDER_VSE_TEST_MEDIA_DIR` | — | `<state>/test-media` | Optional external test-media location |
| `BLENDER_VSE_FFMPEG` | `VP_FFMPEG` | `PATH`, then known Windows paths | FFmpeg executable |
| `BLENDER_VSE_FFPROBE` | `VP_FFPROBE` | `PATH`, then known Windows paths | ffprobe executable |

## Visible session discovery

| Variable | Legacy alias | Default | Purpose |
| --- | --- | --- | --- |
| `BLENDER_VSE_AUTOSTART` | `VP_BLENDER_AUTOSTART` | `1` | Start a visible Blender session when required |
| `BLENDER_VSE_START_TIMEOUT` | `VP_BLENDER_START_TIMEOUT` | `45` | Deadline for completing GUI discovery, in seconds |
| `BLENDER_VSE_VISIBILITY_GRACE` | `VP_BLENDER_VISIBILITY_GRACE` | `5` | Grace period before repairing a hidden session |
| `BLENDER_VSE_STABILITY_SAMPLES` | `VP_BLENDER_STABILITY_SAMPLES` | `3` | Consecutive stable-window observations |
| `BLENDER_VSE_STABILITY_INTERVAL` | `VP_BLENDER_STABILITY_INTERVAL` | `0.35` | Seconds between stability samples |

## Local bridge

| Variable | Default | Purpose |
| --- | --- | --- |
| `BLENDER_BRIDGE_HOST` | `127.0.0.1` | Bridge host; only loopback names and addresses are accepted |
| `BLENDER_BRIDGE_PORT` | `10850` | Local TCP port |
| `BLENDER_BRIDGE_TIMEOUT` | `30` | Socket-operation timeout, in seconds |

The bridge has no authentication. Non-loopback binding is rejected; do not
forward its port. See [Security](../SECURITY.md).

## MCP boundary

| Variable | Default | Purpose |
| --- | --- | --- |
| `BLENDER_VSE_WORKSPACE` | Server working directory | Workspace folder, for hosts that start MCP servers elsewhere |

The MCP adapter resolves each `.blend` path against
`<workspace>/blender-vse-projects` and rejects it before Blender starts if it
leaves that folder. See [Local MCP server](mcp.md).

The local plugin forwards the documented Blender VSE variables and basic OS/uv
runtime paths through the explicit `env_vars` allowlist in `.mcp.json`. It does
not forward arbitrary host variables.

## Test-only switch

`BLENDER_VSE_ALLOW_DIRECT_MUTATION=1` (legacy alias
`VP_ALLOW_DIRECT_MUTATION`) bypasses the public patch boundary for explicitly
registered compatibility integration suites. Production applications must never
set it. The public GUI smoke profile proves the normal path without this switch.

## Inspect effective configuration

```bash
blender-vse status
```

This read-only command reports resolved executables, execution policy, bridge
readiness, state directories, the source of the project-directory setting,
allowed roots, and whether post-install configuration is still required. It
does not launch Blender.
