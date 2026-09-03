# Local Codex plugin

[Chinese version](plugin_zh-CN.md)

The repository root is a valid local Codex plugin. It combines the
`blender-vse` Skill with the local four-tool stdio MCP server:

```text
blender-vse/
|-- .codex-plugin/plugin.json
|-- .mcp.json
|-- skills/blender-vse/
|-- src/blender_vse/
`-- pyproject.toml
```

This phase targets local Codex use. Public ChatGPT plugin submission requires a
reviewable HTTPS MCP endpoint; the local server intentionally remains stdio and
does not open a network listener.

## User installation contract

The supported user-facing installation request is:

```text
Install this plugin: https://github.com/Aoike123/blender-vse-control
```

The repository contains `.agents/plugins/marketplace.json`. Its one entry uses
the Git-backed `url` source because the plugin lives at the repository root.
The installing Agent performs the marketplace and plugin CLI operations on the
user's behalf, verifies success, and asks the user to start a new task. Those
internal operations are not steps the user should have to understand.

Before reporting the installation complete, the Agent must follow the
[required post-install conversation](installation.md#required-post-install-conversation):
ask the user for an absolute project directory, configure
`BLENDER_VSE_PROJECTS_DIR`, verify the effective value, and only then report
the plugin as `ready`.

The release ZIP and local-marketplace commands below are maintainer, offline,
and recovery paths. They are not the primary installation experience.

## Prerequisites

- Blender installed on the same machine and interactive desktop as Codex.
- No preinstalled Python is required. The installing Agent checks for
  [`uv`](https://docs.astral.sh/uv/), asks permission to install it from an
  official source when absent, and verifies it before enabling MCP.
- A persistent `BLENDER_VSE_ALLOWED_ROOTS` value for projects outside the
  default `BLENDER_VSE_PROJECTS_DIR`.

The plugin's `.mcp.json` launches:

```bash
uv run --no-project --managed-python --python "3.12" --with "mcp==2.1.1" python scripts/run_plugin_mcp.py
```

`uv` downloads a managed Python 3.12 when needed, creates a cached isolated run
environment, and supplies the MCP SDK on first use; the small launcher imports
the server from the plugin's own `src/`
tree. It does not create a virtual environment or lock file inside the installed
plugin, so a read-only plugin source remains usable. First start can require
network access; subsequent starts reuse the uv cache. The plugin launch pins
the SDK version that passed its protocol matrix, while the Python package extra
keeps a compatible `mcp>=2,<3` range. The config forwards only
documented Blender VSE and basic OS runtime variables. It does not forward
provider credentials or the test-only direct-mutation switch.

After one successful online start has populated the selected uv cache, hosts
that require offline startup may set `UV_OFFLINE=1`; the plugin explicitly
allows that setting through to uv.

`blender_patch` and `blender_acknowledge` are configured to prompt for approval.
The server still enforces allowed roots and revision tokens independently of
host approval settings.

## Build an installable local marketplace

From a checkout:

```bash
uv run --no-project --python ">=3.10" python scripts/build_plugin.py
uv run --no-project --python ">=3.10" python scripts/build_plugin.py --check
```

The deterministic archive is written to
`dist/blender-vse-plugin-<version>.zip`. It contains a local marketplace root:

```text
blender-vse-marketplace/
|-- .agents/plugins/marketplace.json
`-- plugins/blender-vse/
    |-- .codex-plugin/plugin.json
    |-- .mcp.json
    |-- skills/
    `-- source and license files
```

Unpack it, then add that non-default marketplace root and install the plugin:

```bash
codex plugin marketplace add /absolute/path/to/blender-vse-marketplace
codex plugin add blender-vse@blender-vse-local
```

Open the Codex Plugins Directory to confirm the local source and start a new
task so the Skill and MCP metadata are loaded from the installed version. Do
not edit Codex configuration files by hand.

## Develop from source

Run the declared command and plugin-specific gates before installing a local
build:

```bash
python -m pip install -e ".[dev]"
python tests/run.py fast
python tests/run.py mcp
python tests/run.py plugin
```

The `plugin` profile launches the exact command from `.mcp.json` and verifies
that it discovers only the four documented tools. The fast gate validates the
manifest, approvals, environment allowlist, deterministic archive, Skill, and
generated command index.

Also run the active Codex installation's bundled `plugin-creator`
`validate_plugin.py` against the repository root. During local iteration, use
`plugin-creator`'s cachebuster/reinstall flow rather than manually appending
version suffixes or editing marketplace state.

## Configure project access

The host must provide `BLENDER_VSE_ALLOWED_ROOTS` before it launches the plugin
process. On Windows, separate directories with `;`; on macOS/Linux, use `:`.
If it is absent, only the effective `BLENDER_VSE_PROJECTS_DIR` is allowed. See
[Configuration](configuration.md), [Local MCP server](mcp.md), and
[Client compatibility](clients.md).

Prefer `<workspace>/blender-vse-projects`. If Codex has no active workspace or
the user selects an external project/resource directory, show the workspace
advisory and obtain explicit confirmation before adding that directory to the
allowed roots.
