# Configuration

[Chinese version](configuration_zh-CN.md)

All settings are optional. Preferred names use `BLENDER_VSE_*`; listed `VP_*`
aliases exist only for migration compatibility.

## Project storage readiness

`BLENDER_VSE_PROJECTS_DIR` is optional for backwards-compatible runtime use,
but required by the installation contract. A newly installed Harness must ask
the user to choose an absolute directory and must not report `ready` while the
variable is absent, inherited only through the legacy alias, or relative.

The OS-specific fallback remains available so existing CLI calls do not break.
It is not evidence that the user selected a storage location. Plugin caches,
marketplace checkouts, temporary clones, and package directories must never be
used for editable projects.

When the Harness has an active workspace, recommend
`<workspace>/blender-vse-projects`. No workspace or a directory outside it is
an advisory condition, not a hard error: explain the sandbox and portability
trade-offs, obtain explicit confirmation, then authorize the chosen external
root. Never relocate existing projects or media without a separate request.

## Runtime and execution

| Variable | Legacy alias | Default | Purpose |
| --- | --- | --- | --- |
| `BLENDER_VSE_BLENDER_EXECUTABLE` | `VP_BLENDER_EXECUTABLE` | `BLENDER_EXECUTABLE`, known install paths, then `PATH` | Blender executable |
| `BLENDER_VSE_EXECUTION` | `VP_BLENDER_EXECUTION` | `live_session` | `live_session` or `headless`; interactive edits still refuse headless |
| `BLENDER_VSE_STATE_DIR` | — | OS user-data directory | Runtime state root |
| `BLENDER_VSE_PROJECTS_DIR` | `VP_PROJECTS_DIR` | `<state>/projects` | Default project directory shown in status |
| `BLENDER_VSE_TMP_DIR` | `VP_TMP_DIR` | `<state>/tmp` | Generated fixed scripts and session logs |
| `BLENDER_VSE_TEST_MEDIA_DIR` | — | `<state>/test-media` | Optional external test-media location |
| `BLENDER_VSE_FFMPEG` | `VP_FFMPEG` | `PATH`, then known Windows paths | FFmpeg executable |
| `BLENDER_VSE_FFPROBE` | `VP_FFPROBE` | `PATH`, then known Windows paths | ffprobe executable |

## Visible session discovery

| Variable | Legacy alias | Default | Purpose |
| --- | --- | --- | --- |
| `BLENDER_VSE_AUTOSTART` | `VP_BLENDER_AUTOSTART` | `1` | Start a visible Blender session when required |
| `BLENDER_VSE_START_TIMEOUT` | `VP_BLENDER_START_TIMEOUT` | `45` | Complete GUI discovery deadline in seconds |
| `BLENDER_VSE_VISIBILITY_GRACE` | `VP_BLENDER_VISIBILITY_GRACE` | `5` | Grace period before repairing a hidden session |
| `BLENDER_VSE_STABILITY_SAMPLES` | `VP_BLENDER_STABILITY_SAMPLES` | `3` | Consecutive stable-window observations |
| `BLENDER_VSE_STABILITY_INTERVAL` | `VP_BLENDER_STABILITY_INTERVAL` | `0.35` | Seconds between stability samples |

## Local bridge

| Variable | Default | Purpose |
| --- | --- | --- |
| `BLENDER_BRIDGE_HOST` | `127.0.0.1` | Bridge host; only loopback names and addresses are accepted |
| `BLENDER_BRIDGE_PORT` | `10850` | Local TCP port |
| `BLENDER_BRIDGE_TIMEOUT` | `30` | Socket operation timeout in seconds |

The bridge has no authentication. Non-loopback binding is rejected; do not
forward its port. See [Security](../SECURITY.md).

## MCP boundary

| Variable | Default | Purpose |
| --- | --- | --- |
| `BLENDER_VSE_ALLOWED_ROOTS` | Effective `BLENDER_VSE_PROJECTS_DIR` | OS path-separator-delimited directories containing projects callable through MCP |

The MCP adapter resolves each explicit `.blend` path and rejects it before
Blender startup when it escapes every allowed root. On Windows separate roots
with `;`; on POSIX systems use `:`. See [Local MCP server](mcp.md).

The local plugin forwards the documented Blender VSE variables and basic OS/uv
runtime paths through an explicit `env_vars` allowlist in `.mcp.json`. It does
not forward arbitrary host variables. Set project roots persistently before
starting Codex; changing an interactive shell after the plugin has launched
does not update the running server.

## Test-only switch

`BLENDER_VSE_ALLOW_DIRECT_MUTATION=1` (legacy alias
`VP_ALLOW_DIRECT_MUTATION`) bypasses the public patch boundary for explicitly
registered compatibility integration suites. Production applications must never
set it. The public GUI smoke profile proves the normal path without this switch.

## Inspect effective configuration

```bash
blender-vse status
```

The command is read-only and reports resolved executables, execution policy,
bridge readiness, state directories, the project-directory configuration
source, allowed roots, and whether post-install configuration is still
required, without launching Blender.
