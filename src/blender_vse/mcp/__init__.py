"""Optional Model Context Protocol adapter for Blender VSE Control.

The core package stays dependency-free. Install ``blender-vse-control[mcp]``
before calling :func:`create_server` or the ``blender-vse-mcp`` entry point.
"""

from __future__ import annotations

from typing import Any


def create_server(*args: Any, **kwargs: Any) -> Any:
    """Create the four-tool MCP server without importing MCP at package import."""

    from .server import create_server as _create_server

    return _create_server(*args, **kwargs)


def main() -> None:
    """Run the local stdio MCP server."""

    try:
        from .server import main as _main
    except ModuleNotFoundError as exc:
        if exc.name == "mcp":
            raise SystemExit(
                'MCP support is not installed. Run: pip install "blender-vse-control[mcp]"'
            ) from exc
        raise
    _main()


__all__ = ["create_server", "main"]
