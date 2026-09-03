# Install on Codex, Claude Code, or DSH

[Chinese version](installation_zh-CN.md)

This repository distributes one `blender-vse` Skill and one
`blender-vse-control` MCP server exposing four tools. Client manifests are
adapters around those shared components; they do not contain independent
editing implementations.

## Runtime bootstrap and external applications

Do not assume that Python or `uv` is already installed. Before enabling the MCP
server, the installing Agent checks for `uv`. If it is missing, the Agent must
ask permission, use an installation method from the
[official uv guide](https://docs.astral.sh/uv/getting-started/installation/),
and verify `uv --version`. Do not silently execute a downloaded installer.

The MCP launch command requires uv-managed Python 3.12. `uv` downloads and
caches that isolated interpreter on first use, so a system Python installation
is not required. First setup therefore needs network access; subsequent starts
reuse the managed interpreter and package cache.

Blender and FFmpeg are external applications and are not downloaded silently.
After project-directory configuration, run `blender-vse status`:

- if Blender is unavailable, guide the user to the
  [official Blender download](https://www.blender.org/download/), then rerun
  status before editing;
- if FFmpeg or ffprobe is unavailable, guide the user to the
  [official FFmpeg download](https://ffmpeg.org/download.html). Basic timeline
  editing may proceed, but proxy generation and media-test fixtures are not
  ready.

## Required post-install conversation

Installation has two distinct states:

- `installed`: the client has copied or registered the Skill and MCP server.
- `ready`: the user has confirmed an absolute project directory and the MCP
  process receives it as `BLENDER_VSE_PROJECTS_DIR`.

### Prefer the active workspace

Before asking for a directory, determine whether the Harness has an active
workspace. When it does, recommend
`<workspace>/blender-vse-projects` for the `.blend` file and referenced media.
Keeping them together improves sandbox access, handoff portability, and path
clarity.

If no workspace is available, recommend opening or selecting one before
configuration. If the selected directory is outside the workspace, show both
the selected and recommended paths, explain that host sandboxes may require
extra authorization and that handoffs are less portable, and ask for explicit
confirmation. An external directory remains supported after confirmation and
must be added to `BLENDER_VSE_ALLOWED_ROOTS`. Never move existing projects or
media automatically.

An installing Agent must inspect the variable after installing. If it is
missing, it must not report the setup as complete. Ask:

> Blender VSE is installed, but project storage is not configured. Which
> absolute directory should contain your editable `.blend` projects?

Validate the answer as an absolute directory. Create it only with the user's
approval. Set `BLENDER_VSE_PROJECTS_DIR` in the client launch environment and,
unless the user requests additional locations, use the same directory as the
sole `BLENDER_VSE_ALLOWED_ROOTS` entry. Never select a plugin cache, marketplace
checkout, temporary clone, or package directory for user projects.

For a user-scoped Windows configuration, the installing Agent may offer this
only after the user confirms the path:

```powershell
[Environment]::SetEnvironmentVariable(
  "BLENDER_VSE_PROJECTS_DIR",
  "D:\VideoProjects",
  "User"
)
```

On macOS or Linux, export the variable in the environment that launches the
client. A shell-profile export affects only clients launched from that shell;
desktop launchers need their own persistent environment configuration. Claude
uses its plugin option directly, while the DSH generator embeds the confirmed
value in the isolated Cordis patch.

If `BLENDER_VSE_PROJECTS_DIR` is already set, report its effective value and
ask the user to confirm that it should remain in use. When a persistent Windows
user environment variable changes while a desktop client is running, fully
exit and relaunch that client; opening a new task alone does not refresh the
parent process environment. Finish by running
`blender-vse status` or equivalent configuration inspection and report the
Skill, MCP server, four tools, project directory, and configuration source.

The machine-readable version of this workflow is
[`install-contract.json`](../install-contract.json).

## Codex

Give Codex the repository URL and ask it to install the plugin. Internally it
registers the repository marketplace and installs `blender-vse@blender-vse`.
The repository's [Codex guide](plugin.md) documents the maintainer commands.

After installation, Codex must perform the required project-directory
conversation above. The bundled `.mcp.json` inherits
`BLENDER_VSE_PROJECTS_DIR` and `BLENDER_VSE_ALLOWED_ROOTS` from the Codex launch
environment. Fully exit and relaunch Codex after setting them, then start a new
task so the installed Skill and MCP process are both reloaded with the new
parent environment.

## Claude Code

The repository is also a Claude Code marketplace and plugin:

```text
/plugin marketplace add Aoike123/blender-vse-control
/plugin install blender-vse@blender-vse
```

The Claude manifest declares a required `projects_dir` directory option, so
Claude Code prompts for it when enabling the plugin. For a non-interactive
install, supply the option through Claude's supported `--config
projects_dir=/absolute/path` flag. Claude injects that value into the bundled
MCP server as both `BLENDER_VSE_PROJECTS_DIR` and the initial allowed root.
Reload plugins or start a new session, then confirm one Skill, one MCP server,
and four tools.

## DeepSeek Harness (DSH)

Clone the repository into a durable location. Run the safe DSH installer once
without a project directory; it copies the complete Skill and deliberately
returns `ready: false` with the required user prompt:

```bash
uv run --no-project --managed-python --python 3.12 \
  python scripts/install_dsh.py --apply
```

The destination is either:

- user scope: `<DSH_HOME>/skills/blender-vse` (normally
  `~/.dsh/skills/blender-vse`);
- project scope: `<project>/.dsh/skills/blender-vse`.

For project scope, add `--scope project --project-root /absolute/project`.
After the user answers, rerun it with the confirmed directory; it keeps an
identical installed Skill and writes an isolated patch without overwriting the
user's main DSH configuration:

```bash
uv run --no-project --managed-python --python 3.12 \
  python scripts/install_dsh.py \
  --workspace-root /absolute/workspace \
  --projects-dir /absolute/workspace/blender-vse-projects \
  --apply
```

If the user explicitly confirms a missing workspace or an external directory,
add `--allow-external-projects`; never add it preemptively.

The output is a one-entry Cordis patch using DSH's official
`@deepseek-ai/dsh-mcp-client`. The installer reports `configured`, not `ready`,
because the patch has not yet been activated. Test it without changing user
state:

```bash
dsh --profile web --patch <DSH_HOME>/integrations/blender-vse/cordis.patch.yml --dump-config
```

For a persistent installation, merge that single patch item into the selected
profile's `cordis.patch.yml` or the home-level `$DSH_HOME/cordis.patch.yml`.
Do not overwrite an existing patch file. Restart DSH and confirm that the Skill
is discoverable and the four tools are registered under the
`mcp__blender-vse-control__*` namespace. Only that final verification permits
the Agent to report `ready`.

## Portable MCP-only hosts

Hosts without Skill or plugin support can still use the MCP server. Generate a
standard stdio object with an explicit project directory:

```bash
uv run --no-project --managed-python --python 3.12 \
  python scripts/print_mcp_config.py \
  --workspace-root /absolute/workspace \
  --projects-dir /absolute/workspace/blender-vse-projects
```

The generator refuses a missing workspace or an external project/allowed root
unless `--allow-external-projects` records the user's prior confirmation.

This installs execution capability only; it does not install the Agent Skill.
