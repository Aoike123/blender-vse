# 第三方声明

[English version](THIRD_PARTY_NOTICES.md)

`src/blender_vse/blender/bridge/blender_bridge_addon.py` 源自 Sandra Schipal
（`sandraschi/blender-mcp`）开发的 Blender MCP Bridge 0.5.0，并依据 MIT License 分发。
必需的版权与许可声明保存在
[LICENSES/blender-mcp-MIT.txt](LICENSES/blender-mcp-MIT.txt)。

本分发包移除了上游服务商凭据、场景检查命令和视口截图命令，更改了插件品牌，并拒绝
所有非回环 Bridge 绑定。保留的 Bridge 接口仅包含 `ping`，以及仅供固定 VSE 操作模板
使用的主线程执行通道。

本仓库不包含 Blender，用户必须单独安装。
