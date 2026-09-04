# Third-party notices

[Chinese version](THIRD_PARTY_NOTICES_zh-CN.md)

`src/blender_vse/blender/bridge/blender_bridge_addon.py` is derived from version
0.5.0 of Blender MCP Bridge by Sandra Schipal (`sandraschi/blender-mcp`) and is
distributed under the MIT License. The required copyright and permission notice
is preserved in
[LICENSES/blender-mcp-MIT.txt](LICENSES/blender-mcp-MIT.txt).

This distribution removes the upstream provider credentials, scene-inspection
commands, and viewport-screenshot commands; changes the add-on branding; and
rejects all non-loopback Bridge bindings. The remaining Bridge surface consists
of `ping` and the main-thread execution channel used only by fixed VSE operation
templates.

Blender itself is not included in this repository and must be installed
separately.
