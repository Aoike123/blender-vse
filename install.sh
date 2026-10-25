#!/bin/sh
# Blender VSE Control one-line installer for Linux and macOS.
#
#   curl -LsSf https://raw.githubusercontent.com/Aoike123/blender-vse/main/install.sh | sh
#
# Installs uv when missing, then installs the `blender-vse-mcp` command with
# uv's managed Python 3.12. It never edits MCP host configuration; register the
# printed command in your host yourself.
#
# Overrides: BLENDER_VSE_SOURCE (pip-style source: git URL or local path),
#            BLENDER_VSE_REF (git ref, default main).
set -eu

REPO_URL="https://github.com/Aoike123/blender-vse"
REF="${BLENDER_VSE_REF:-main}"
SOURCE="${BLENDER_VSE_SOURCE:-git+${REPO_URL}@${REF}}"

say() { printf '%s\n' "$*"; }
fail() { printf 'error: %s\n' "$*" >&2; exit 1; }

case "$(uname -s)" in
  Linux|Darwin) ;;
  *) fail "unsupported system $(uname -s); on Windows run install.ps1" ;;
esac

if ! command -v uv >/dev/null 2>&1; then
  say "==> uv not found; installing it from https://astral.sh/uv"
  if command -v curl >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
  elif command -v wget >/dev/null 2>&1; then
    wget -qO- https://astral.sh/uv/install.sh | sh
  else
    fail "curl or wget is required to install uv"
  fi
  PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  export PATH
  command -v uv >/dev/null 2>&1 || fail "uv was installed but is not on PATH; open a new shell and rerun"
fi

say "==> Installing blender-vse-mcp from ${SOURCE}"
uv tool install --force --python 3.12 "blender-vse-control[mcp] @ ${SOURCE}"

BIN_DIR="$(uv tool dir --bin)"
MCP_BIN="${BIN_DIR}/blender-vse-mcp"
[ -x "$MCP_BIN" ] || fail "install finished but ${MCP_BIN} is missing"

BLENDER=""
if [ -n "${BLENDER_VSE_BLENDER_EXECUTABLE:-}" ]; then
  BLENDER="$BLENDER_VSE_BLENDER_EXECUTABLE"
elif command -v blender >/dev/null 2>&1; then
  BLENDER="$(command -v blender)"
elif [ -x /Applications/Blender.app/Contents/MacOS/Blender ]; then
  BLENDER=/Applications/Blender.app/Contents/MacOS/Blender
fi

say ""
say "Installed: ${MCP_BIN}"
if [ -n "$BLENDER" ]; then
  say "Blender:   ${BLENDER}"
else
  say "Blender:   not found. Install Blender 4.2+ from https://www.blender.org/download/"
  say "           or set BLENDER_VSE_BLENDER_EXECUTABLE to its executable."
fi
case ":$PATH:" in
  *":${BIN_DIR}:"*) ;;
  *) say "PATH:      add ${BIN_DIR} to PATH, or use the full path above." ;;
esac
say ""
say "Register it as a stdio MCP server named blender-vse, command: blender-vse-mcp"
say "Projects are kept in <workspace>/blender-vse-projects of the folder the host runs in."
