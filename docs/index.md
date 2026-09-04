# Documentation

[Chinese documentation](index_zh-CN.md)

Blender VSE Control provides a local, revision-safe control layer for
Agent-assisted editing of persistent `.blend` timelines. Blender remains the
editable source of truth, while fresh observations prevent Agents from
silently overwriting human changes.

For end-to-end automation, pair it with an available director or
production-orchestration Skill. The upper layer owns creative direction,
storyboards, source-media work, and acceptance criteria; Blender VSE Control
executes concrete timeline edits and verifies the saved `.blend`. See
[Architecture](architecture.md) for the responsibility boundary.

Proxy encoding and rebuilding remain outside the project's scope; it only
validates and attaches externally generated proxy manifests. `blender_verify`
reopens the project in a fresh process and confirms saved structural facts. It
does not evaluate visual quality or creative correctness. The root
[README](../README.md) provides a concise overview; detailed contracts live
here.

## Use the project

| Document | Use it for |
| --- | --- |
| [Getting started](getting-started.md) | Install, detect Blender, create a project, apply the first patch |
| [Python and CLI API](api.md) | Public methods, result envelopes, errors, command-line syntax |
| [Operation catalog](operations.md) | Operation families, public/internal boundaries, and how to add an operation |
| [Configuration](configuration.md) | Environment variables, execution policy, runtime directories |
| [Context model](context-model.md) | Bounded reads, pagination, compaction, and resume rules |
| [Local MCP server](mcp.md) | Install, authorize roots, connect a host, and use the four tools |
| [`blender-vse` Skill](../skills/blender-vse/SKILL.md) | Prompt-level tool discipline, command routing, recovery, and resuming after compaction |
| [Local Codex plugin](plugin.md) | Build, install, configure, and validate the Skill + stdio bundle |
| [Multi-host installation](installation.md) | Install on Codex, Claude Code, or DSH and confirm project storage |
| [Client compatibility](clients.md) | Codex, Claude Code/Desktop, DSH, generic stdio, and public ChatGPT boundaries |

## Understand and integrate it

| Document | Use it for |
| --- | --- |
| [Architecture](architecture.md) | Components, trust boundaries, revision model, execution modes |
| [Security](../SECURITY.md) | Local bridge threat model and vulnerability reporting |

## Maintain and release it

| Document | Use it for |
| --- | --- |
| [Testing](testing.md) | Core, MCP, Harness, stateful, headless, GUI, and full profiles |
| [Stateful eval corpus](../evals/README.md) | Long-session, compaction, conflict, recovery, and negative-routing cases |
| [Test directory guide](../tests/README.md) | Where tests and the machine-readable plan live |
| [Contributing](../CONTRIBUTING.md) | Change workflow and acceptance criteria |
| [Release checklist](../RELEASING.md) | Exact pre-release gates and archive checks |
| [Changelog](../CHANGELOG.md) | User-visible changes by release |

## Canonical machine-readable sources

To avoid duplicating authoritative lists in prose, use these machine-readable
sources:

- `src/blender_vse/catalog.py` defines public operation families and execution
  classifications.
- `src/blender_vse/schemas/*.json` defines external JSON contracts.
- `src/blender_vse/context-policy.json` defines context budgets and compaction
  fields.
- `tests/test-plan.json` defines test profiles, requirements, timeouts, and
  budgets.
- `pyproject.toml` defines package, pytest, and coverage configuration.
- `CHANGELOG.md` records release-level behavior changes.
