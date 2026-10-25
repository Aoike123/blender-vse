# Local MCP server

[Chinese version](mcp_zh-CN.md)

Blender VSE Control includes an optional local Model Context Protocol server.
It is a thin adapter around the public Python API: the `.blend` file remains the
source of truth, and the MCP process stores neither conversation history nor a
global "current project."

## Install

Use the [one-line installer](installation.md), then register
`blender-vse-mcp` in your host as a stdio server. Contributors can instead run
`python -m pip install -e ".[mcp]"` or `.[dev]`. The adapter targets the
official Python MCP SDK 2.x.

`blender-vse-mcp` is a long-running protocol process launched by the host. Run
directly, it looks idle because it waits for messages on `stdin`.

## Project paths

Projects live in `<workspace>/blender-vse-projects`, where the workspace is the
folder the host starts the server in. Every tool call names a `.blend` path
relative to that folder, such as `demo.blend`. The server canonicalizes the path
before contacting Blender and rejects any path that leaves the folder with
`project_not_allowed`. Set `BLENDER_VSE_WORKSPACE` only when a host starts MCP
servers outside the workspace.

Contributors can inspect the generated tool schemas with:

```bash
mcp dev src/blender_vse/mcp/server.py --with-editable .
```

## Four-tool surface

| Tool | Purpose | Important rule |
| --- | --- | --- |
| `blender_read` | Read a bounded summary or targeted timeline page | `summary` is the default; `full` is explicit compatibility only |
| `blender_patch` | Apply one allowlisted command batch atomically | Requires a fresh revision, hash, single-use observation ID, and idempotent patch ID |
| `blender_acknowledge` | Adopt a manual Blender edit after observing it | Never acknowledge state that was not read and understood |
| `blender_verify` | Reopen and verify persisted project state | Use after the final read/patch cycle |

There is no MCP tool for arbitrary Python, raw bridge execution, operation
catalog internals, shell access, or implicit project selection.

## Stateful workflow

The Agent host owns the expanding conversation context. The server contributes
bounded observations to that context but does not replay the conversation:

```text
blender_read(summary)
        |
        +--> blender_read(range/detail, selectors)
                    |
                    +--> blender_patch(fresh observation)
                                  |
                                  +--> blender_read(summary) --> ... --> verify
```

After host compaction, handoff, a stale-base response, or any uncertainty about
the active observation, discard `observation_id` and call `blender_read` again.
Across compaction, retain only the explicit project path, user intent, last
confirmed revision and hash, bounded recent patch IDs, actions, and outputs with
counts and digests, and unresolved decisions. The canonical rules and byte
budgets are in
[Context model](context-model.md).

## Local execution and concurrency

The stdio server must run on the same machine and interactive desktop as the
visible Blender process. It intentionally does not expose an HTTP listener.
Calls targeting one canonical project path are serialized; calls for different
projects do not share a current-project variable. Blender's own visible-session
identity checks still fail closed if another project owns the editor.

The four-second `mcp` gate covers the MCP security boundary, tool surface, and
one real subprocess handshake in isolation. It runs on the minimum and maximum
Python versions without slowing core fast or coverage collection. Actual GUI
editing remains covered by `blender-smoke`; see [Testing](testing.md).

## Prompt and Skill layer

The bundled [`blender-vse` Skill](../skills/blender-vse/SKILL.md) supplies the
progressive read/patch/recovery workflow and declares this stdio server as its
dependency. The server also carries that Skill, so hosts without plugin
support still get it: the server instructions hold its core rules, the
`blender-vse` prompt returns `SKILL.md`, and every Skill file is a resource
under `blender-vse://skill/` (for example
`blender-vse://skill/references/recovery.md`). The [local plugin guide](plugin.md) packages both into a validated,
installable marketplace bundle. Public ChatGPT publication remains separate
because it requires an HTTPS MCP endpoint rather than this local stdio process.
