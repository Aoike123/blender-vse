# 配置

[English version](configuration.md)

所有设置都是可选项。推荐名称使用 `BLENDER_VSE_*`；列出的 `VP_*` 别名仅用于迁移兼容。

## 工程位置

工程始终保存在 `<workspace>/blender-vse-projects` 中，其中 workspace 是 MCP 宿主启动服务时
所在的文件夹。工具调用使用相对于该文件夹的路径。见[安装](installation_zh-CN.md#工程保存位置)。

## 运行时与执行

| 变量 | 旧别名 | 默认值 | 用途 |
| --- | --- | --- | --- |
| `BLENDER_VSE_BLENDER_EXECUTABLE` | `VP_BLENDER_EXECUTABLE` | `BLENDER_EXECUTABLE`、已知安装路径，然后 `PATH` | Blender 可执行文件 |
| `BLENDER_VSE_EXECUTION` | `VP_BLENDER_EXECUTION` | `live_session` | `live_session` 或 `headless`；交互编辑仍拒绝无头模式 |
| `BLENDER_VSE_STATE_DIR` | — | 操作系统的用户数据目录 | 运行时状态根目录 |
| `BLENDER_VSE_TMP_DIR` | `VP_TMP_DIR` | `<state>/tmp` | 生成的固定脚本与会话日志 |
| `BLENDER_VSE_TEST_MEDIA_DIR` | — | `<state>/test-media` | 可选外部测试媒体目录 |
| `BLENDER_VSE_FFMPEG` | `VP_FFMPEG` | `PATH`，然后已知 Windows 路径 | FFmpeg 可执行文件 |
| `BLENDER_VSE_FFPROBE` | `VP_FFPROBE` | `PATH`，然后已知 Windows 路径 | ffprobe 可执行文件 |

## 可见会话发现

| 变量 | 旧别名 | 默认值 | 用途 |
| --- | --- | --- | --- |
| `BLENDER_VSE_AUTOSTART` | `VP_BLENDER_AUTOSTART` | `1` | 需要时启动可见 Blender 会话 |
| `BLENDER_VSE_START_TIMEOUT` | `VP_BLENDER_START_TIMEOUT` | `45` | 完成 GUI 发现的最长时间，单位为秒 |
| `BLENDER_VSE_VISIBILITY_GRACE` | `VP_BLENDER_VISIBILITY_GRACE` | `5` | 尝试恢复隐藏会话前的宽限期 |
| `BLENDER_VSE_STABILITY_SAMPLES` | `VP_BLENDER_STABILITY_SAMPLES` | `3` | 窗口连续保持稳定所需的观察次数 |
| `BLENDER_VSE_STABILITY_INTERVAL` | `VP_BLENDER_STABILITY_INTERVAL` | `0.35` | 稳定性观察间隔，单位秒 |

## 本地 Bridge

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `BLENDER_BRIDGE_HOST` | `127.0.0.1` | Bridge 主机；只接受回环名称与地址 |
| `BLENDER_BRIDGE_PORT` | `10850` | 本地 TCP 端口 |
| `BLENDER_BRIDGE_TIMEOUT` | `30` | 套接字操作超时，单位为秒 |

Bridge 没有身份验证。非回环绑定会被拒绝，不要转发端口。见[安全策略](../SECURITY_zh-CN.md)。

## MCP 边界

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `BLENDER_VSE_WORKSPACE` | 服务的工作目录 | 工作文件夹；仅用于不在工作文件夹中启动 MCP 服务的宿主 |

MCP 适配器会把每个 `.blend` 路径解析到 `<workspace>/blender-vse-projects` 下；路径越出该文件夹
时，会在 Blender 启动前拒绝请求。见[本地 MCP 服务](mcp_zh-CN.md)。

本地插件只通过 `.mcp.json` 中明确的 `env_vars` 允许列表转发文档列出的 Blender VSE 变量，以及
基本的操作系统和 uv 运行时路径；它不会任意转发 Agent 宿主的环境变量。

## 仅测试开关

`BLENDER_VSE_ALLOW_DIRECT_MUTATION=1`（旧别名 `VP_ALLOW_DIRECT_MUTATION`）仅允许已明确登记的兼容性集成测试绕过公开 Patch 边界。生产应用绝不能设置此变量。公开 GUI 冒烟档位会在不使用该开关的情况下验证正常路径。

## 检查生效配置

```bash
blender-vse status
```

该命令只读，不会启动 Blender。它会报告已解析的可执行文件、执行策略、Bridge 就绪状态、状态目录、项目目录配置来源、允许的根目录，以及是否仍需完成安装后配置。
