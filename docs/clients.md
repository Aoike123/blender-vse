# Client compatibility

[Chinese version](clients_zh-CN.md)

The four-tool MCP server and Agent Skill are portable, but installation and
approval metadata are host-specific. Do not treat one client's plugin manifest
as a universal configuration file.

| Surface | Status | Supported path |
| --- | --- | --- |
| Python / CLI | Verified | Install the package and call `blender-vse` |
| Generic local MCP host | Verified by official SDK client | Launch `blender-vse-mcp` or the uv launcher over stdio |
| Codex local plugin | Verified, including extracted bundle | Use [Local Codex plugin](plugin.md) |
| Claude Code | Verified with 2.1.259 in isolated state | Install the GitHub marketplace; its required directory option configures MCP |
| DeepSeek Harness (DSH) | Verified with 0.1.0-rc.6 in isolated state | Install the Skill and merge one generated `dsh-mcp-client` patch item |
| Claude Desktop | Configuration documented; app-level execution not tested here | Add the generated standard stdio server object |
| ChatGPT public plugin | Not yet supported | Requires a reviewed HTTPS MCP endpoint; local stdio is insufficient |

All Harness installs follow the [installation contract](installation.md).
Copying components produces `installed`; setup becomes `ready` only after the
user confirms an absolute `BLENDER_VSE_PROJECTS_DIR`.

## Generate a standard stdio config

The Codex plugin's root `.mcp.json` contains Codex-specific approval and
environment-inheritance fields. For another host, generate a standard config
with absolute paths:

```bash
uv run --no-project --managed-python --python 3.12 \
  python scripts/print_mcp_config.py \
  --workspace-root /absolute/path/to/workspace \
  --projects-dir /absolute/path/to/workspace/blender-vse-projects
```

Repeat `--allowed-root` only for additional directories. The command prints
JSON and does not modify host configuration. Review it, then merge the one
`blender-vse-control` entry through the host's normal configuration UI or CLI.

## Claude Code

Claude Code installs the repository root as a self-contained plugin, including
the canonical `skills/blender-vse` directory and a Claude-specific standard
stdio configuration:

```text
/plugin marketplace add Aoike123/blender-vse-control
/plugin install blender-vse@blender-vse
```

The manifest's required `projects_dir` user option prompts for the project
directory instead of requiring a manual settings edit. Its value is injected
as `BLENDER_VSE_PROJECTS_DIR` and the initial
`BLENDER_VSE_ALLOWED_ROOTS`. Reload the plugin or start a new session after
changing it. The installing Agent recommends the active workspace's
`blender-vse-projects` directory; a missing workspace or external selection
requires an advisory and explicit confirmation.

Use `claude mcp list` and `/mcp` to confirm that exactly four tools appear. Use
`/skills` and `/context` to confirm Skill discovery and observe context usage.
The server remains stateless with respect to the conversation; Claude owns the
growing/compacted context, while the Skill's 4 KB resume capsule defines what
survives compaction.

## DeepSeek Harness (DSH)

DSH discovers user and project Skills from its standard filesystem roots. Copy
the complete canonical Skill into `<DSH_HOME>/skills/blender-vse` for user
scope or `<project>/.dsh/skills/blender-vse` for project scope. Then render the
single-server Cordis patch after the user confirms project storage:

```bash
uv run --no-project --managed-python --python 3.12 \
  python scripts/print_dsh_config.py \
  --workspace-root /absolute/path/to/workspace \
  --projects-dir /absolute/path/to/workspace/blender-vse-projects \
  --output /absolute/path/to/blender-vse.cordis.yml
```

The generated patch uses `@deepseek-ai/dsh-mcp-client`, local stdio, the exact
MCP SDK version tested by this repository, and an absolute launcher path. Test
it with `dsh --profile <name> --patch <file> --dump-config`; then merge its one
item into the chosen profile or home `cordis.patch.yml` without overwriting
unrelated user entries. DSH exposes the four tools under the
`mcp__blender-vse-control__*` namespace.

If the user chooses an external directory, rerun the generator with
`--allow-external-projects` only after recording that explicit confirmation.

## Claude Desktop and other MCP hosts

Run `print_mcp_config.py` and use the emitted `mcpServers` object. It contains a
standard `type`, `command`, `args`, and `env` entry with an absolute launcher
path. Host-specific approval settings should protect `blender_patch` and
`blender_acknowledge`; server-side allowed-root and revision checks remain
authoritative.

## Public ChatGPT boundary

The local editor must share a machine and interactive desktop with Blender, so
stdio is the correct local transport. Public ChatGPT plugin submission requires
a reachable HTTPS MCP endpoint (or a development tunnel while testing). A
future remote design also needs an authenticated local companion and an
explicit trust model; exposing the unauthenticated Blender bridge or forwarding
its loopback port is not an acceptable shortcut.

Official references:

- [OpenAI plugin architecture](https://developers.openai.com/plugins/concepts/plugins)
- [OpenAI plugin packaging](https://developers.openai.com/plugins/build/plugins)
- [Claude Code plugins](https://code.claude.com/docs/en/plugins)
- [Claude Code marketplaces](https://code.claude.com/docs/en/plugin-marketplaces)
- [Claude Code MCP](https://code.claude.com/docs/en/mcp)
- [DSH Skills](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/skills.md)
- [DSH MCP client](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/mcp/mcp-client/README.md)
