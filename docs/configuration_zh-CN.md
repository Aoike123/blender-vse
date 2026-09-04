# 配置

[English version](configuration.md)

所有设置都是可选项。推荐名称使用 `BLENDER_VSE_*`；列出的 `VP_*` 别名仅用于迁移兼容。

## 项目存储就绪度

为保持向后兼容，运行时仍可省略 `BLENDER_VSE_PROJECTS_DIR`，但安装契约要求配置此变量。新安装的 Harness 必须让用户选择一个绝对目录。变量缺失、仅通过旧别名继承或设为相对路径时，都不得报告 `ready`。

系统会继续保留各操作系统的回退路径，以免破坏现有 CLI 调用，但回退路径不能证明用户已主动选择存储位置。插件缓存、市场检出目录、临时克隆和软件包目录绝不能用于保存可编辑项目。

Harness 有活跃工作区时，推荐使用 `<workspace>/blender-vse-projects`。没有工作区或选择工作区外的目录时，只需提醒用户，不应视为硬错误：说明沙盒与可移植性方面的取舍，取得明确确认，再授权所选的外部根目录。除非用户另行要求，否则绝不能迁移现有项目或媒体。

## 运行时与执行

| 变量 | 旧别名 | 默认值 | 用途 |
| --- | --- | --- | --- |
| `BLENDER_VSE_BLENDER_EXECUTABLE` | `VP_BLENDER_EXECUTABLE` | `BLENDER_EXECUTABLE`、已知安装路径，然后 `PATH` | Blender 可执行文件 |
| `BLENDER_VSE_EXECUTION` | `VP_BLENDER_EXECUTION` | `live_session` | `live_session` 或 `headless`；交互编辑仍拒绝无头模式 |
| `BLENDER_VSE_STATE_DIR` | — | 操作系统的用户数据目录 | 运行时状态根目录 |
| `BLENDER_VSE_PROJECTS_DIR` | `VP_PROJECTS_DIR` | `<state>/projects` | `status` 中显示的默认项目目录 |
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
| `BLENDER_VSE_ALLOWED_ROOTS` | 生效的 `BLENDER_VSE_PROJECTS_DIR` | 允许通过 MCP 调用的项目所在目录，以操作系统路径分隔符分隔 |

MCP 适配器会解析每个显式 `.blend` 路径；如果路径不在任何允许的根目录下，就会在 Blender 启动前拒绝请求。Windows 使用 `;` 分隔根目录，POSIX 系统使用 `:`。见[本地 MCP 服务](mcp_zh-CN.md)。

本地插件只通过 `.mcp.json` 中明确的 `env_vars` 允许列表转发文档列出的 Blender VSE 变量，以及基本的操作系统和 uv 运行时路径；它不会任意转发 Agent 宿主的环境变量。请在启动 Codex 前持久化项目根目录配置。插件启动后，即使修改交互式 Shell 环境，也不会更新正在运行的服务。

## 仅测试开关

`BLENDER_VSE_ALLOW_DIRECT_MUTATION=1`（旧别名 `VP_ALLOW_DIRECT_MUTATION`）仅允许已明确登记的兼容性集成测试绕过公开 Patch 边界。生产应用绝不能设置此变量。公开 GUI 冒烟档位会在不使用该开关的情况下验证正常路径。

## 检查生效配置

```bash
blender-vse status
```

该命令只读，不会启动 Blender。它会报告已解析的可执行文件、执行策略、Bridge 就绪状态、状态目录、项目目录配置来源、允许的根目录，以及是否仍需完成安装后配置。
