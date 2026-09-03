# Blender VSE Control

[Chinese documentation](README_zh-CN.md)

![Blender VSE Control — revision-safe editable timelines](assets/social-preview.png)

> A low-context, focused Blender video-editing Skill. Install it, pair it with a
> creation Skill, and enjoy the edit.

A typed, revision-safe Python control layer for Blender's Video Sequence
Editor. Applications and agents can edit the visible timeline while the
`.blend` file remains the source of truth and manual edits remain protected.

> Status: alpha. Blender 5.1 is the primary verified target. The bundled bridge
> declares Blender 4.2+ compatibility, but release claims are based only on
> versions listed in the release notes.

## Install from GitHub

Send the repository link to Codex, Claude Code, or DeepSeek Harness (DSH) and
ask it to install the plugin:

```text
Install this plugin: https://github.com/Aoike123/blender-vse-control
```

That is the intended user flow. After copying the Skill and MCP integration,
the installing Agent must ask which absolute directory should contain editable
`.blend` projects. Installation is not `ready` until the user confirms that
directory and it is supplied as `BLENDER_VSE_PROJECTS_DIR`. The recommended
location is `<workspace>/blender-vse-projects`; an absent workspace or external
directory triggers an explicit advisory and confirmation.

See [installation](docs/installation.md) for the Codex marketplace, Claude
marketplace, DSH Skill/Cordis, configuration, and verification paths. Users
should not need to edit client manifests by hand.

## Core guarantees

- **Observed writes:** every patch requires a revision, timeline hash, and
  single-use token from a fresh read.
- **No silent overwrite:** a changed timeline fails with a stale-base error.
- **Atomic edits:** a command list commits one revision or rolls back.
- **Visible collaboration:** interactive edits require a proven Blender GUI,
  project identity, VSE timeline, and preview.
- **Recoverable output:** the `.blend` is canonical; final verification reopens
  it in a fresh Blender process.
- **Bounded surface:** callers select catalogued operations, never free-form
  Python.
- **Bounded context:** reads default to summaries; range/detail pages disclose
  only selected fields and carry revision-bound cursors; write, verify, and
  error receipts also have byte budgets.
- **Bounded resume:** compaction capsules keep durable intent and recent
  evidence under 4 KB while replacing old history with counts and digests.

## Install and try it

End users do not need a preinstalled Python. The installing Agent bootstraps
`uv` with permission when it is missing, and `uv` provisions a managed Python
3.12 runtime. Blender is installed separately; FFmpeg is guided when proxy or
media-fixture features are needed. Source contributors still use Python 3.10+.

```bash
python -m venv .venv
python -m pip install -e ".[dev]"
blender-vse status
```

To connect an Agent host directly, install `.[mcp]`, authorize project roots,
and configure the host to launch `blender-vse-mcp`. See the
[local MCP guide](docs/mcp.md).

The repository also ships a progressive-disclosure
[`blender-vse` Skill](skills/blender-vse/SKILL.md). It supplies the prompt-level
read/patch/recovery discipline while the MCP server supplies execution; neither
layer stores the host's conversation history.

For local Codex installation, the repository is also a validated plugin root
and can build a deterministic local-marketplace archive. See the
[plugin guide](docs/plugin.md).

Create or observe a project, then use the returned `revision`, `timeline_hash`,
and `observation_id` in a patch:

```bash
blender-vse read ./projects/demo.blend --create
blender-vse patch ./projects/demo.blend \
  --base-revision 0 \
  --base-timeline-hash HASH_FROM_READ \
  --read-token TOKEN_FROM_READ \
  --patch-id patch-title-001 \
  --commands '[{"op":"add_text","text":"Hello","channel":3,"frame_start":1,"length":90}]'
blender-vse verify ./projects/demo.blend
```

Read again before every subsequent patch. See the
[getting-started guide](docs/getting-started.md) for Python examples and setup
details.

For long-running Agent sessions, escalate from `summary` to a targeted
`range/detail` read. Use `--view full` only for explicit legacy debugging. See
the [context model](docs/context-model.md).

## Test profiles

One manifest, [`tests/test-plan.json`](tests/test-plan.json), defines every
test profile, performance target, and hard timeout:

| Profile | Purpose | Command | Target / timeout |
| --- | --- | --- | ---: |
| `fast` | Core unit + contracts; no MCP/Blender process | `python tests/run.py fast` | 3 / 10 s |
| `coverage` | Host-side branch coverage | `python tests/run.py coverage` | 5 / 15 s |
| `mcp` | Four-tool contract + one real stdio discovery | `python tests/run.py mcp` | 4 / 10 s |
| `plugin` | Exact plugin-declared stdio launch | `python tests/run.py plugin` | 60 / 180 s |
| `harness` | Real Claude + DSH package/config validation | `python tests/run.py harness` | 60 / 180 s |
| `stateful` | Scenario replay + 250-cycle compaction eval | `python tests/run.py stateful` | 5 / 15 s |
| `blender-headless` | Native media decode | `python tests/run.py blender-headless` | 15 / 60 s |
| `blender-smoke` | One public read/patch/read/verify GUI flow | `python tests/run.py blender-smoke` | 120 / 240 s |
| `blender-full` | Complete Blender regression suite | `python tests/run.py blender-full` | 900 / 1200 s |

Run `python tests/run.py list` to inspect the plan. The detailed safety and CI
rules are in [Testing](docs/testing.md).

## Documentation

- [Documentation index](docs/index.md)
- [Getting started](docs/getting-started.md)
- [Python and CLI API](docs/api.md)
- [Operation catalog](docs/operations.md)
- [Architecture](docs/architecture.md)
- [Configuration](docs/configuration.md)
- [Context model](docs/context-model.md)
- [Local MCP server](docs/mcp.md)
- [Agent Skill](skills/blender-vse/SKILL.md)
- [Local Codex plugin](docs/plugin.md)
- [Codex, Claude Code, and DSH installation](docs/installation.md)
- [Client compatibility](docs/clients.md)
- [Testing](docs/testing.md)
- [Security policy](SECURITY.md)
- [Contributing](CONTRIBUTING.md)
- [Release checklist](RELEASING.md)

## Project boundary

This repository owns Blender execution, timeline operations, revision safety,
and persistence verification. It does not own downloaders, transcoders, proxy
encoding, project-wide asset databases, or an agent framework. Those systems
integrate through typed operations and the
[external proxy manifest](src/blender_vse/schemas/proxy-manifest.schema.json).

## License

Blender VSE Control is free software under the
[GNU Affero General Public License v3.0](LICENSE). The vendored Blender MCP
Bridge remains MIT-licensed; see [Third-party notices](THIRD_PARTY_NOTICES.md).
