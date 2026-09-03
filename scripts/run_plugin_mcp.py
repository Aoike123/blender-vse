"""Launch the bundled MCP server from a read-only plugin source tree."""

from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def main() -> None:
    from blender_vse.mcp import main as run_server

    run_server()


if __name__ == "__main__":
    main()
