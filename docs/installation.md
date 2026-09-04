# Install in Codex, Claude Code, or DSH

[Chinese version](installation_zh-CN.md)

This repository provides one `blender-vse` Skill and one `blender-vse-control`
MCP server with four tools. The client manifests adapt those shared components
to each host; none contains a separate editing implementation.

## Runtime bootstrap and external applications

Do not assume that Python or `uv` is already installed. Before enabling the MCP
server, the Agent performing the installation must check for `uv`. If it is
missing, the Agent must ask for permission, use an installation method from the
[official uv guide](https://docs.astral.sh/uv/getting-started/installation/),
and verify the installation with `uv --version`. Never run a downloaded
installer without the user's knowledge.

The MCP launch command uses Python 3.12 managed by `uv`. On first use, `uv`
downloads and caches an isolated interpreter, so no system Python installation
is required. Initial setup therefore needs network access; subsequent launches
reuse the managed interpreter and package cache.

Blender and FFmpeg are external applications and must not be downloaded without
the user's knowledge. After configuring the project directory, run
`blender-vse status`:

- If Blender is unavailable, direct the user to the
  [official Blender download](https://www.blender.org/download/), then rerun the
  status check before editing.
- If FFmpeg or ffprobe is unavailable, direct the user to the
  [official FFmpeg download](https://ffmpeg.org/download.html). Basic timeline
  editing can proceed, but proxy generation and media-test fixtures are not yet
  ready.

## Required post-install conversation

Installation has two distinct states:

- `installed`: the client has copied or registered the Skill and MCP server.
- `ready`: the user has confirmed an absolute project directory and the MCP
  process receives it as `BLENDER_VSE_PROJECTS_DIR`.

### Prefer the active workspace

Before asking for a directory, check whether the Harness has an active
workspace. If it does, recommend `<workspace>/blender-vse-projects` for the
`.blend` files and their referenced media. Keeping them together improves
sandbox access, handoff portability, and path clarity.

If no workspace is available, recommend opening or selecting one before
continuing with configuration. If the selected directory is outside the
workspace, show both the selected and recommended paths. Explain that host
sandboxes may require additional authorization and that handoffs will be less
portable, then ask for explicit confirmation. External directories remain
supported after confirmation and must be added to
`BLENDER_VSE_ALLOWED_ROOTS`. Never move existing projects or media
automatically.

After installation, the Agent must inspect `BLENDER_VSE_PROJECTS_DIR`. If it is
missing, the Agent must not report setup as complete and must ask:

> Blender VSE is installed, but project storage is not configured. Which
> absolute directory should contain your editable `.blend` projects?

Validate the answer as an absolute directory path. Create the directory only
with the user's approval. Set `BLENDER_VSE_PROJECTS_DIR` in the client's launch
environment and, unless the user requests additional locations, use the same
directory as the sole `BLENDER_VSE_ALLOWED_ROOTS` entry. Never use a plugin cache,
marketplace checkout, temporary clone, or package directory for user projects.

For a user-scoped Windows configuration, the Agent may offer the following
command only after the user confirms the path:

```powershell
[Environment]::SetEnvironmentVariable(
  "BLENDER_VSE_PROJECTS_DIR",
  "D:\VideoProjects",
  "User"
)
```

On macOS or Linux, export the variable in the environment used to launch the
client. An export in a shell profile affects only clients launched from that
shell; desktop launchers need their own persistent environment configuration.
Claude uses its plugin option directly, while the DSH generator embeds the
confirmed value in an isolated Cordis patch.

If `BLENDER_VSE_PROJECTS_DIR` is already set, report its effective value and ask
the user to confirm that it should remain in use. If a persistent Windows user
environment variable changes while a desktop client is running, fully exit and
relaunch the client; opening a new task alone does not refresh the parent
process environment. Finish by running `blender-vse status` or an equivalent
configuration check, then report the Skill, MCP server, four tools, project
directory, and configuration source.

The machine-readable version of this workflow is
[`install-contract.json`](../install-contract.json).

## Codex

Give Codex the repository URL and ask it to install the plugin. Behind the
scenes, Codex registers the repository as a marketplace and installs
`blender-vse@blender-vse`. The repository's [Codex guide](plugin.md) documents
the maintainer commands.

After installation, Codex must complete the required project-directory
conversation above. The bundled `.mcp.json` inherits
`BLENDER_VSE_PROJECTS_DIR` and `BLENDER_VSE_ALLOWED_ROOTS` from the Codex launch
environment. Fully exit and relaunch Codex after setting these variables, then
start a new task so that both the installed Skill and the MCP process reload
from the new parent environment.

## Claude Code

The repository also serves as a Claude Code marketplace and plugin:

```text
/plugin marketplace add Aoike123/blender-vse-control
/plugin install blender-vse@blender-vse
```

The Claude manifest declares `projects_dir` as a required directory option, so
Claude Code prompts for it when the plugin is enabled. For a non-interactive
installation, pass the option with Claude's supported
`--config projects_dir=/absolute/path` flag. Claude injects the value into the
bundled MCP server as both `BLENDER_VSE_PROJECTS_DIR` and the initial allowed
root. Reload the plugins or start a new session, then confirm that one Skill,
one MCP server, and four tools are available.

## DeepSeek Harness (DSH)

Clone the repository to a durable location. First, run the safe DSH installer
without a project directory. It copies the complete Skill and deliberately
returns `ready: false` along with the required user prompt:

```bash
uv run --no-project --managed-python --python 3.12 \
  python scripts/install_dsh.py --apply
```

The destination depends on the installation scope:

- User scope: `<DSH_HOME>/skills/blender-vse` (normally
  `~/.dsh/skills/blender-vse`).
- Project scope: `<project>/.dsh/skills/blender-vse`.

For project scope, add `--scope project --project-root /absolute/project`.
After the user responds, rerun the installer with the confirmed directory. It
leaves the installed Skill unchanged and writes an isolated patch without
overwriting the user's main DSH configuration:

```bash
uv run --no-project --managed-python --python 3.12 \
  python scripts/install_dsh.py \
  --workspace-root /absolute/workspace \
  --projects-dir /absolute/workspace/blender-vse-projects \
  --apply
```

Add `--allow-external-projects` only after the user explicitly confirms that no
workspace is available or that an external directory should be used. Never add
it preemptively.

The output is a single-entry Cordis patch that uses DSH's official
`@deepseek-ai/dsh-mcp-client`. The installer reports `configured` rather than
`ready` because the patch has not yet been activated. Test it without changing
user state:

```bash
dsh --profile web --patch <DSH_HOME>/integrations/blender-vse/cordis.patch.yml --dump-config
```

For a persistent installation, merge that single patch entry into the selected
profile's `cordis.patch.yml` or the home-level `$DSH_HOME/cordis.patch.yml`.
Never overwrite an existing patch file. Restart DSH and confirm that the Skill
is discoverable and that the four tools are registered under the
`mcp__blender-vse-control__*` namespace. Only after this final verification may
the Agent report `ready`.

## Portable MCP-only hosts

Hosts without Skill or plugin support can still use the MCP server. Specify an
explicit project directory and generate a standard stdio configuration object:

```bash
uv run --no-project --managed-python --python 3.12 \
  python scripts/print_mcp_config.py \
  --workspace-root /absolute/workspace \
  --projects-dir /absolute/workspace/blender-vse-projects
```

The generator rejects a missing workspace, an external project directory, or
an external allowed root unless `--allow-external-projects` records the user's
prior confirmation.

This provides execution capability only; it does not install the Agent Skill.
