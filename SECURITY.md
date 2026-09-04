# Security policy

[Chinese version](SECURITY_zh-CN.md)

## Supported versions

Until a stable support matrix is published, security fixes target the latest
`0.x` release line.

## Reporting

Do not include exploit details in a public issue. Contact the repository
maintainer privately through the hosting platform and provide the affected
version, impact, a minimal reproduction, and any suggested mitigation. A
dedicated security address should be configured before the first public
release.

## Local bridge threat model

The bundled Bridge can execute Python inside Blender. It is intended only for a
trusted local machine and provides no authentication mechanism.

- Binding is restricted to loopback (`127.0.0.1`, `::1`, or `localhost`).
- Do not expose port `10850` through firewall rules, containers, SSH tunnels, or
  port forwarding.
- Do not call the raw `execute_code` channel with untrusted input.
- Public operations use fixed templates and JSON/Python-literal encoding.
- Media, project, font, subtitle, output, and manifest paths remain part of the
  host application's trust boundary.

## Integrity boundaries

- Revision, hash, and token checks prevent automated writes based on stale
  state.
- Patch IDs prevent the same patch from being applied twice accidentally.
- Proxy manifests validate required fields, hashes, file sizes, source mtime,
  allowed scale/profile, and project-directory containment.
- The controller never silently switches away from a different Blender project
  that is already open.
- Checkpoint restore keeps a pre-restore backup and repeats visible-session
  discovery after replacement.

## MCP boundary

- The optional MCP server uses local stdio and does not open a network port.
- Every call must name an explicit `.blend` path under
  `BLENDER_VSE_ALLOWED_ROOTS` (or the default projects directory).
- Paths are canonicalized before Blender is contacted. The server checks the
  suffix and root containment; if a path already exists, it also verifies that
  the path names a file.
- Operations for the same canonical project are serialized.
- Only `blender_read`, `blender_patch`, `blender_acknowledge`, and
  `blender_verify` are published. Raw bridge execution is not an MCP tool.
- Tool annotations are usability hints, not authorization. The server-side
  path and revision checks remain authoritative.
- Skill instructions are orchestration guidance, not an authorization layer;
  they cannot widen allowed roots or bypass revision checks.
- The local plugin uses `uv --no-project` to provision a cached MCP environment
  without writing to the installed plugin source. Review the exact SDK version
  pinned in `.mcp.json`; the first start may require network access to a package
  index.
- Plugin configuration forwards an explicit environment-variable allowlist and
  never forwards provider secrets or the direct-mutation test switch.

The fast test gate covers hostile multiline-string encoding, fragmented socket
frames, non-loopback rejection, path escapes, stale proxy content, project
mismatches, and checkpoint-recovery contracts. Real persistence remains part
of the GUI smoke release gate; see [Testing](docs/testing.md).
