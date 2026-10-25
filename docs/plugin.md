# Local Codex plugin

[Chinese version](plugin_zh-CN.md)

The repository root is itself a valid local Codex plugin. It combines the
`blender-vse` Skill with a local four-tool stdio MCP server:

```text
blender-vse/
|-- .codex-plugin/plugin.json
|-- .mcp.json
|-- skills/blender-vse/
|-- src/blender_vse/
`-- pyproject.toml
```

This release targets local Codex use. Submitting a public ChatGPT plugin
requires a reviewable HTTPS MCP endpoint; the local server intentionally uses
stdio and does not open a network listener.

## Marketplace entry

The repository contains `.agents/plugins/marketplace.json`. Its single entry
uses the Git-backed `url` source because the plugin lives at the repository
root, so Codex can install it like any other marketplace plugin. Most users
should use the [one-line installer](installation.md) and register the MCP
server directly instead.

The release ZIP and local-marketplace commands below are intended for
maintainers, offline installation, and recovery.

## Prerequisites

- Blender installed on the same machine and interactive desktop as Codex.
- [`uv`](https://docs.astral.sh/uv/) on `PATH`. No preinstalled Python is
  required; the [one-line installer](installation.md) installs uv when absent.

The plugin's `.mcp.json` launches:

```bash
uv run --no-project --managed-python --python "3.12" --with "mcp==2.1.1" python scripts/run_plugin_mcp.py
```

When necessary, `uv` downloads a managed Python 3.12, creates a cached and
isolated runtime environment, and supplies the MCP SDK on first use. The small
launcher imports the server from the plugin's own `src/` tree. It does not
create a virtual environment or lock file inside the installed plugin, so the
plugin remains usable even when its source is read-only. The first start may
require network access; later starts reuse the uv cache. The plugin launch pins
the SDK version that passed the protocol matrix, while the Python package extra
retains the compatible `mcp>=2,<3` range. The configuration forwards only the
documented Blender VSE and basic OS runtime variables. It does not forward
provider credentials or the test-only direct-mutation switch.

After one successful online start has populated the selected uv cache, hosts
that need to start offline may set `UV_OFFLINE=1`; the plugin explicitly passes
that setting through to uv.

`blender_patch` and `blender_acknowledge` are configured to prompt for approval.
Regardless of the host's approval settings, the server independently enforces
allowed-root, revision, timeline-hash, and observation-ID checks.

## Build an installable local marketplace

From a checkout:

```bash
uv run --no-project --python ">=3.10" python scripts/build_plugin.py
uv run --no-project --python ">=3.10" python scripts/build_plugin.py --check
```

The deterministic archive is written to
`dist/blender-vse-plugin-<version>.zip` and contains the following local
marketplace root:

```text
blender-vse-marketplace/
|-- .agents/plugins/marketplace.json
`-- plugins/blender-vse/
    |-- .codex-plugin/plugin.json
    |-- .mcp.json
    |-- skills/
    `-- source and license files
```

Unpack the archive, register its non-default marketplace root, and install the
plugin:

```bash
codex plugin marketplace add /absolute/path/to/blender-vse-marketplace
codex plugin add blender-vse@blender-vse-local
```

Open the Codex Plugins Directory to confirm the local source, then start a new
task so that Codex loads the Skill and MCP metadata from the installed version.
Do not edit Codex configuration files by hand.

## Develop from source

Before installing a local build, run the declared command and the
plugin-specific quality gates:

```bash
python -m pip install -e ".[dev]"
python tests/run.py fast
python tests/run.py mcp
python tests/run.py plugin
```

The `plugin` profile runs the exact command from `.mcp.json` and verifies that
it discovers only the four documented tools. The fast gate validates the
manifest, approvals, environment allowlist, deterministic archive, Skill, and
generated command index.

Also validate the repository root with the `validate_plugin.py` script bundled
with the active Codex installation's `plugin-creator`. During local iteration,
use `plugin-creator`'s cachebuster/reinstall flow instead of manually appending
version suffixes or editing marketplace state.

## Project access

Projects live in `<workspace>/blender-vse-projects` and tool calls use paths
relative to it. No project configuration is required. See
[Configuration](configuration.md) and [Local MCP server](mcp.md).
