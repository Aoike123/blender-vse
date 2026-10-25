# Installation

[Chinese version](installation_zh-CN.md)

## One-line install

Linux and macOS:

```bash
curl -LsSf https://raw.githubusercontent.com/Aoike123/blender-vse/main/install.sh | sh
```

Windows (PowerShell):

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/Aoike123/blender-vse/main/install.ps1 | iex"
```

The script:

1. Installs [uv](https://docs.astral.sh/uv/) from its official installer when
   it is missing.
2. Runs `uv tool install` to put the `blender-vse` and `blender-vse-mcp`
   commands on uv's managed Python 3.12. No system Python is required.
3. Looks for Blender and prints where it found it, or where to get it.

It never edits MCP host configuration. Set `BLENDER_VSE_REF` to install another
git ref, or `BLENDER_VSE_SOURCE` to install from a fork or local checkout.

## Register the server

Add `blender-vse-mcp` to your MCP host as a stdio server, the same way as any
other MCP server. It takes no arguments and needs no environment variables.
The server carries the `blender-vse` Skill itself: its core rules arrive as the
server instructions, and the full Skill is available as the `blender-vse`
prompt and as `blender-vse://skill/...` resources. FFmpeg is needed only for
proxy generation and media test fixtures.

## Where projects live

Projects always live in `blender-vse-projects/` inside the folder the host
starts the server in, which is normally your workspace. Tools take paths
relative to that folder, such as `demo.blend` or `cuts/v2.blend`, and reject
paths that leave it. The folder is created with the first project. Because
nothing stores an absolute path, moving or renaming the workspace keeps every
project working.

If a host starts MCP servers somewhere other than the workspace, set
`BLENDER_VSE_WORKSPACE` to the workspace folder in that host's server entry.

## Update and uninstall

Rerun the install command to update. To remove the commands:

```bash
uv tool uninstall blender-vse-control
```

## From source

Contributors install the package in editable mode instead:

```bash
python -m pip install -e ".[dev]"
blender-vse status
```
