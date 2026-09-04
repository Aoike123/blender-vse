# Architecture

[Chinese version](architecture_zh-CN.md)

## Boundary and source of truth

Blender VSE Control is a local control plane around a persistent `.blend`
timeline. The `.blend` is the source of truth; rendered media, JSON responses,
proxy files, and session observations are derived artifacts.

The package has no runtime dependency on an agent framework, production
database, downloader, or media provider.

```text
Application / Agent host
        |
        | read / patch / acknowledge / verify
        v
optional local stdio MCP     exactly four tools; explicitly allowed project roots
        |
        v
blender_vse.api              collaboration and checkpoint policy
        |
        +--> catalog          public capability and execution manifest
        +--> context          bounded views, cursors, and byte budgets
        +--> resume           bounded compaction/handoff capsule
        +--> router           public operation boundary
        v
blender_vse.blender          result envelope and save verification
        |
        +--> vse_ops          fixed, typed bpy script templates
        +--> runner           live-versus-headless policy
        +--> live_session     local bridge, identity, and visible UI proof
        +--> .blend           canonical persistent state
```

## Canonical manifests

The project avoids duplicating hand-maintained lists:

- `catalog.py` owns operation families, read-only operations, headless
  operations, project-optional operations, control-plane commands, internal
  primitives, and removed-operation migration errors.
- `context-policy.json` owns response budgets, optional field groups, and
  compaction/resume state.
- JSON Schemas define serialized input and output shapes.
- `tests/test-plan.json` defines test profiles and budgets.
- Contract tests verify that the catalog, adapter registry, router, schemas,
  CLI, and documentation remain synchronized.

## Execution modes

Interactive edits require a visible Blender GUI in the Video Editing workspace.
Before execution, the session layer verifies the bridge process, native window,
requested project, scene binding, timeline area, preview area, and visible strip
count. Missing or ambiguous evidence causes the operation to fail closed.

Only native media inspection, rendering, and fresh-process persistence
verification may run headless. An interactive edit never silently falls back to
a second background Blender process.

## Revision protocol

1. `read` returns the persisted revision, a canonical full-timeline hash, and a
   single-use observation ID.
2. `patch` validates all three immediately before mutation.
3. Commands execute as one atomic batch with an idempotent patch ID.
4. Success commits one revision. Failure restores the pre-patch state.
5. The next patch requires another `read`.

A manual Blender edit changes the canonical hash. The caller must read and
understand it, then either build from the new state or explicitly acknowledge
it. The controller never blesses an unobserved change.

## Agent context and state

The Agent host owns conversation history; this package does not. The
context layer keeps tool results bounded through `summary`, `range`, and
`detail` views. Pagination cursors are tied to one timeline revision and query.
After Agent host compaction, callers discard observation IDs and perform a fresh
targeted read. See [Context model](context-model.md).

The optional MCP process is deliberately memory-light: it retains only bounded
deterministic project-lock stripes, not conversation messages, observations, or
a current project. Every call supplies and reauthorizes its project path. See
[Local MCP server](mcp.md).

The optional Skill provides the prompt and orchestration layer. Its compact
entry point defines the state-transition rules; command signatures and recovery
guidance are loaded from focused references only when needed. The fast gate
checks a generated command index against the canonical catalog and Python
signatures.

`resume.py` is a host-side helper, not conversation storage. It turns durable
handoff facts into a 4 KB capsule, retaining recent history plus counts and
digests. The stateful eval corpus replays conflict/recovery paths and measures
active context over 250 synthetic edit cycles without pretending that the core
library owns the Agent conversation.

## Multi-host distribution

The repository root serves as a marketplace/plugin for both Codex and Claude
Code. DSH uses the same canonical Skill through its filesystem provider and a
single generated Cordis patch. All three launch the same stdio server; client
files contain no editing implementation.

The MCP command uses uv-managed Python 3.12, so system Python is not an end-user
dependency and installed source need not be writable. Bootstrapping a missing
uv installation requires user approval; Blender and FFmpeg remain external
applications installed through guided steps. A deterministic builder emits the
offline Codex marketplace archive, while GitHub is the primary cross-Harness
distribution path. None of these local paths claims that stdio satisfies public
HTTPS plugin-submission requirements. See
[multi-host installation guide](installation.md).

## Checkpoint restore

Restore is a control-plane transaction, not a normal bpy operation. The
controller validates the observed base, creates a recoverable backup, closes
the matching GUI project, replaces the file, reopens it visibly, repeats the
session checks, and finalizes a new revision. It must be the only command in its
patch.

## Compatibility

Internal `video_ai_*` custom properties and `VP_RESULT` process markers remain
stable for timelines created by the original embedded implementation. They are
persistence and wire details, not the public Python namespace.

## External integrations

Proxy encoding and project-wide asset identity belong to the host application.
The package validates proxy hashes, source metadata, path containment, and
profile compatibility before attaching an external manifest. Asset operations
bind host-owned IDs to strips without importing the host registry.

See [Security](../SECURITY.md) for the local bridge threat model and
[Operations](operations.md) for the public/internal boundary.
