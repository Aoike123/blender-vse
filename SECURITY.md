# Security policy

[Chinese version](SECURITY_zh-CN.md)

## Supported versions

Security fixes are made on the latest `0.x` release line until a stable support
matrix is published.

## Reporting

Do not open a public issue containing exploit details. Contact the repository
maintainer privately through the hosting platform with the affected version,
impact, minimal reproduction, and suggested mitigation. A dedicated security
address should be added before the first public release.

## Local bridge threat model

The bundled bridge can execute Python inside Blender. It is intended only for a
trusted local machine and has no authentication protocol.

- Binding is restricted to loopback (`127.0.0.1`, `::1`, or `localhost`).
- Do not expose port `10850` through firewall rules, containers, SSH tunnels, or
  port forwarding.
- Do not call the raw `execute_code` channel with untrusted input.
- Public operations use fixed templates and JSON/Python-literal encoders.
- Media, project, font, subtitle, output, and manifest paths remain part of the
  host application's trust boundary.

## Integrity boundaries

- Revision/hash/token checks prevent stale automatic writes.
- Patch IDs prevent accidental duplicate application.
- Proxy manifests validate required fields, hashes, file sizes, source mtime,
  allowed scale/profile, and project-directory containment.
- A different open Blender project is never switched silently.
- Checkpoint restore keeps a pre-restore backup and repeats visible-session
  discovery after replacement.

## MCP boundary

- The optional MCP server uses local stdio and does not open a network port.
- Every call requires an explicit `.blend` path below
  `BLENDER_VSE_ALLOWED_ROOTS` (or the default projects directory).
- Paths are canonicalized before Blender is contacted; suffix, containment, and
  existing-file type are checked.
- Operations for the same canonical project are serialized.
- Only `blender_read`, `blender_patch`, `blender_acknowledge`, and
  `blender_verify` are published. Raw bridge execution is not an MCP tool.
- Tool annotations are usability hints, not authorization. The server-side
  path and revision checks remain authoritative.
- Skill instructions are orchestration guidance, not an authorization layer;
  they cannot widen allowed roots or bypass revision checks.
- The local plugin uses `uv --no-project` to provision a cached MCP environment
  without writing into installed plugin source. Review the exact SDK pin in
  `.mcp.json`; first start may require package-index network access.
- Plugin configuration forwards an explicit environment-variable allowlist and
  never forwards provider secrets or the direct-mutation test switch.

The fast test gate includes hostile multiline string encoding, fragmented socket
frames, non-loopback rejection, path escape, stale proxy content, project
mismatch, and checkpoint recovery contracts. Real persistence remains part of
the GUI smoke release gate; see [Testing](docs/testing.md).
